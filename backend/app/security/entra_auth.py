"""Validação de token Microsoft Entra ID (OIDC/OAuth2) — Fase 1, reforçada
numa revisão de hardening (D-029).

Duas implementações atrás da mesma interface (`TokenValidator`), escolhidas
por `get_token_validator()` a partir de `Settings.entra_validation_mode`,
e cacheadas no processo (`functools.lru_cache`) — nunca se cria um
`PyJWKClient`/validador novo a cada pedido:

- `RealEntraTokenValidator`: busca as chaves públicas (JWKS) do tenant real
  via rede (com cache do `PyJWKClient`), e valida assinatura RS256,
  issuer, audience, tenant (`tid`), validade temporal (`exp`/`iat`/`nbf`
  quando presente), e que o token é delegado (claim `scp`, nunca só
  `roles` — esta API não aceita tokens de aplicação/client credentials).
  A identidade persistente vem sempre do claim `oid` — nunca de `sub`
  como recurso, porque `sub` pode variar por aplicação/tenant para o
  mesmo utilizador (é `pairwise` por desenho no protocolo OIDC).
- `MockEntraTokenValidator`: valida contra uma chave PÚBLICA local
  (`ENTRA_MOCK_PUBLIC_KEY_FILE`), sem qualquer chamada de rede — usada em
  testes automatizados e em desenvolvimento local. **Nunca alcançável em
  staging/produção**: `Settings._enforce_hardening_in_non_local_envs`
  (app/config.py, D-024) exige `ENTRA_VALIDATION_MODE=real` nesses
  ambientes, e a aplicação recusa-se a arrancar caso contrário — por isso
  `entra_validation_mode` nunca chega a valer `'mock'` num processo em
  staging/produção.

O código da aplicação não contém nenhuma chave, pública ou privada: sem
`ENTRA_MOCK_PUBLIC_KEY_FILE` o validador mock rejeita todos os tokens (503).
Quem assina os tokens de teste é a suite (`tests/entra_mock.py`, que gera um
par de chaves efémero em cada execução); em desenvolvimento local, ver o
README.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import jwt
from jwt import PyJWKClient

# 'oid' e 'sub' são ambos exigidos como presentes (boa prática OIDC), mas
# só 'oid' é usado como identidade persistente — ver _claims_from_payload.
# 'nbf' NÃO está na lista de obrigatórios (nem todos os emissores o
# incluem), mas se estiver presente no token, o PyJWT valida-o sempre por
# omissão (verify_nbf=True é o comportamento padrão, nunca desativado
# aqui) — testado explicitamente em tests/test_auth_entra.py.
REQUIRED_CLAIMS = ["exp", "iat", "iss", "aud", "sub", "oid"]


# Tempo máximo (s) de cada pedido ao endpoint JWKS. Sem isto o PyJWKClient
# espera 30 s por omissão e um problema de rede prende os workers da API.
JWKS_TIMEOUT_SECONDS = 5

# Mensagem do PyJWT quando o `kid` do token não está no JWKS (token que
# nunca foi emitido por este tenant, ou chave já retirada) — é um problema do
# token (401), não do serviço. Qualquer outro erro do cliente JWKS é um
# problema do JWKS/da rede (503).
_UNKNOWN_KID_MARKER = "Unable to find a signing key that matches"


class TokenValidationError(Exception):
    """Levantado por qualquer falha de validação do token. O chamador HTTP
    (`app/security/current_user.py`) converte isto sempre num 401 genérico
    — a mensagem detalhada fica só em log/exceção, nunca na resposta, para
    não ajudar um atacante a "afinar" um token inválido."""


class TokenValidationUnavailableError(Exception):
    """Não foi possível validar o token por um problema do serviço, não do
    token: o endpoint JWKS está inacessível (rede, DNS, timeout, HTTP de
    erro) ou devolveu um conjunto de chaves inutilizável. O chamador HTTP
    converte isto em 503 (com log), nunca em 401 — para que o frontend não
    trate uma falha transitória como "sessão expirada"."""


@dataclass(frozen=True)
class EntraClaims:
    # SEMPRE o claim 'oid' — nunca 'sub' como recurso (D-029): 'sub' é
    # "pairwise" por desenho no OIDC e pode não ser estável entre
    # aplicações/tenants para a mesma pessoa; 'oid' é o identificador de
    # objeto do Entra ID, estável.
    object_id: str
    email: str | None  # 'preferred_username' / 'upn' / 'email', o que estiver presente
    raw: dict


class TokenValidator(Protocol):
    def validate(self, token: str) -> EntraClaims: ...


def _validate_delegated_token(payload: dict, *, required_scope: str) -> None:
    """Esta API só aceita tokens delegados (utilizador interativo via
    Authorization Code + PKCE) — nunca tokens só de aplicação (client
    credentials), que trazem `roles` sem `scp`. Ver docs/DECISIONS.md
    D-029."""
    scp = payload.get("scp")
    if not scp or not str(scp).strip():
        raise TokenValidationError(
            "token sem claim 'scp' — só são aceites tokens delegados (utilizador "
            "interativo), nunca tokens de aplicação (client credentials)"
        )
    if required_scope:
        scopes = str(scp).split()
        if required_scope not in scopes:
            raise TokenValidationError(f"token não contém o scope delegado exigido {required_scope!r}")


def _claims_from_payload(payload: dict, *, tenant_id: str = "") -> EntraClaims:
    object_id = payload.get("oid")
    if not object_id or not str(object_id).strip():
        # Nunca cai para 'sub' — um token sem 'oid' é rejeitado, mesmo que
        # tenha 'sub' (D-029).
        raise TokenValidationError("token sem claim 'oid' (identidade persistente exigida)")

    if tenant_id:
        tid = payload.get("tid")
        if tid != tenant_id:
            raise TokenValidationError(f"token emitido para um tenant diferente do configurado (tid={tid!r})")

    email = payload.get("preferred_username") or payload.get("upn") or payload.get("email")
    return EntraClaims(object_id=str(object_id), email=email, raw=payload)


class RealEntraTokenValidator:
    """Validação real contra um tenant Microsoft Entra ID — usa o endpoint
    JWKS público do tenant (`resolved_entra_jwks_url()`), nunca um segredo
    local. `PyJWKClient` faz cache das chaves, evitando pedido de rede em
    cada validação; esta classe é ela própria cacheada por
    `get_token_validator()`, para não recriar o `PyJWKClient` a cada
    pedido HTTP."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        tenant_id: str = "",
        required_scope: str = "",
        jwks_client: PyJWKClient | None = None,
    ):
        if not issuer or not audience or not jwks_url:
            raise TokenValidationError(
                "configuração Entra ID incompleta — issuer/audience/jwks_url em falta "
                "(ENTRA_TENANT_ID/ENTRA_CLIENT_ID por definir?)"
            )
        self._issuer = issuer
        self._audience = audience
        self._tenant_id = tenant_id
        self._required_scope = required_scope
        # `jwks_client` só existe para os testes poderem injetar um cliente
        # falso, sem rede; em produção cria-se sempre o cliente real, com
        # timeout explícito.
        self._jwks_client = jwks_client or PyJWKClient(jwks_url, timeout=JWKS_TIMEOUT_SECONDS)

    def _signing_key(self, token: str):
        """Obtém a chave pública do `kid` do token, separando um token
        inválido (`TokenValidationError` -> 401) de uma falha do JWKS ou da
        rede (`TokenValidationUnavailableError` -> 503)."""
        try:
            return self._jwks_client.get_signing_key_from_jwt(token)
        except jwt.PyJWKClientConnectionError as exc:
            raise TokenValidationUnavailableError(f"JWKS inacessível: {exc}") from exc
        except jwt.PyJWKClientError as exc:
            if _UNKNOWN_KID_MARKER in str(exc):
                raise TokenValidationError(str(exc)) from exc
            raise TokenValidationUnavailableError(f"JWKS inutilizável: {exc}") from exc
        except (jwt.PyJWKError, jwt.PyJWKSetError) as exc:
            # Chave do JWKS que o PyJWT não consegue carregar (inclui
            # PyJWKSetError): o conjunto de chaves está avariado.
            raise TokenValidationUnavailableError(f"JWKS inutilizável: {exc}") from exc
        except jwt.PyJWTError as exc:
            # Cabeçalho do token ilegível (DecodeError, ...): token inválido.
            raise TokenValidationError(str(exc)) from exc
        except ValueError as exc:
            # JSON inválido na resposta do endpoint JWKS.
            raise TokenValidationUnavailableError(f"JWKS com resposta inválida: {exc}") from exc

    def validate(self, token: str) -> EntraClaims:
        signing_key = self._signing_key(token)
        try:
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._audience,
                # options por omissão do PyJWT já validam exp/iat/nbf
                # (quando presente) — nunca desativados aqui.
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.PyJWTError as exc:
            raise TokenValidationError(str(exc)) from exc
        _validate_delegated_token(payload, required_scope=self._required_scope)
        return _claims_from_payload(payload, tenant_id=self._tenant_id)


# --------------------------------------------------------------------------
# Mock — só para testes e desenvolvimento local. Ver o docstring do módulo.
# --------------------------------------------------------------------------

TEST_ISSUER = "https://mock-entra.test/tenant-sintetico/v2.0"
TEST_AUDIENCE = "mock-client-id-sintetico"
TEST_SCOPE = "access_as_user"


class MockEntraTokenValidator:
    """Só para testes e desenvolvimento local — ver o docstring do módulo.
    Nunca faz nenhuma chamada de rede; a chave pública vem de um ficheiro
    local (`public_key_file`), nunca de um IdP nem do código. Sem ficheiro,
    rejeita tudo. Aplica exatamente as mesmas regras de negócio do validador
    real (oid obrigatório, token delegado, tenant quando configurado) — só a
    origem da chave/rede muda."""

    def __init__(
        self,
        *,
        issuer: str = TEST_ISSUER,
        audience: str = TEST_AUDIENCE,
        tenant_id: str = "",
        required_scope: str = "",
        public_key_file: str = "",
    ):
        self._issuer = issuer
        self._audience = audience
        self._tenant_id = tenant_id
        self._required_scope = required_scope
        self._public_key_file = public_key_file

    def _public_key(self) -> str:
        if not self._public_key_file.strip():
            raise TokenValidationUnavailableError(
                "ENTRA_VALIDATION_MODE=mock exige ENTRA_MOCK_PUBLIC_KEY_FILE"
            )
        try:
            return Path(self._public_key_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise TokenValidationUnavailableError(
                f"ENTRA_MOCK_PUBLIC_KEY_FILE: não foi possível ler o ficheiro ({exc.strerror or type(exc).__name__})"
            ) from None

    def validate(self, token: str) -> EntraClaims:
        try:
            payload = jwt.decode(
                token,
                self._public_key(),
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.PyJWTError as exc:
            raise TokenValidationError(str(exc)) from exc
        _validate_delegated_token(payload, required_scope=self._required_scope)
        return _claims_from_payload(payload, tenant_id=self._tenant_id)


# --------------------------------------------------------------------------
# Fábrica cacheada — nunca criar um PyJWKClient/validador novo por pedido.
# --------------------------------------------------------------------------


@lru_cache(maxsize=8)
def _cached_real_validator(
    issuer: str, audience: str, jwks_url: str, tenant_id: str, required_scope: str
) -> RealEntraTokenValidator:
    return RealEntraTokenValidator(
        issuer=issuer,
        audience=audience,
        jwks_url=jwks_url,
        tenant_id=tenant_id,
        required_scope=required_scope,
    )


@lru_cache(maxsize=8)
def _cached_mock_validator(
    tenant_id: str, required_scope: str, public_key_file: str
) -> MockEntraTokenValidator:
    return MockEntraTokenValidator(
        tenant_id=tenant_id, required_scope=required_scope, public_key_file=public_key_file
    )


def get_token_validator(settings) -> TokenValidator:
    """Fábrica única — nunca instanciar `RealEntraTokenValidator`/
    `MockEntraTokenValidator` diretamente fora daqui, para que a escolha
    fique sempre centrada em `Settings.entra_validation_mode`. Cacheada no
    processo por `(issuer, audience, jwks_url, tenant_id, required_scope)`
    — um `PyJWKClient` (que já faz o seu próprio cache de chaves) só é
    criado uma vez por configuração distinta, nunca a cada pedido HTTP."""
    if settings.entra_validation_mode == "mock":
        return _cached_mock_validator(
            settings.entra_tenant_id, settings.entra_required_scope, settings.entra_mock_public_key_file
        )
    return _cached_real_validator(
        settings.resolved_entra_issuer(),
        settings.resolved_entra_audience(),
        settings.resolved_entra_jwks_url(),
        settings.entra_tenant_id,
        settings.entra_required_scope,
    )
