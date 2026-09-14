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
- `MockEntraTokenValidator`: valida contra uma chave de teste fixa, local,
  sem qualquer chamada de rede — usada exclusivamente em testes
  automatizados. **Nunca alcançável em staging/produção**:
  `Settings._enforce_hardening_in_non_local_envs` (app/config.py, D-024)
  exige `ENTRA_VALIDATION_MODE=real` nesses ambientes, e a aplicação
  recusa-se a arrancar caso contrário — por isso `entra_validation_mode`
  nunca chega a valer `'mock'` num processo em staging/produção.

A "chave de teste" abaixo (`_TEST_PRIVATE_KEY_PEM`/`_TEST_PUBLIC_KEY_PEM`)
**não é um segredo real**: é um par de chaves RSA gerado uma única vez só
para este repositório, usado apenas para assinar/validar tokens sintéticos
em testes — nunca aceite por um Entra ID real, nunca usada para autenticar
nada fora deste código. Documentado aqui de propósito, sem ambiguidade.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache
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


class TokenValidationError(Exception):
    """Levantado por qualquer falha de validação. O chamador HTTP
    (`app/security/current_user.py`) converte isto sempre num 401 genérico
    — a mensagem detalhada fica só em log/exceção, nunca na resposta, para
    não ajudar um atacante a "afinar" um token inválido."""


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

    def __init__(self, *, issuer: str, audience: str, jwks_url: str, tenant_id: str = "", required_scope: str = ""):
        if not issuer or not audience or not jwks_url:
            raise TokenValidationError(
                "configuração Entra ID incompleta — issuer/audience/jwks_url em falta "
                "(ENTRA_TENANT_ID/ENTRA_CLIENT_ID por definir?)"
            )
        self._issuer = issuer
        self._audience = audience
        self._tenant_id = tenant_id
        self._required_scope = required_scope
        self._jwks_client = PyJWKClient(jwks_url)

    def validate(self, token: str) -> EntraClaims:
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
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
# Mock — só para testes automatizados. Ver aviso no docstring do módulo.
# --------------------------------------------------------------------------

_TEST_PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQDGKU43F6T5dV5l
y6DD+gEunsR5yu84wpCAb4guuW45jmO8DxaN37nkIpxHqNgeH2WWyLLDe9IuzsMP
m6UQbIheAfxM/zBPdBmXGTw+f389oGFxITynLacJ/Y8KBnVpZ71k7xhdmveeeQ5X
ehJR2cwhJoboWOM5wZh+SweVP/zqfGPmYEHL+rrMynNrwYDLRco6OA8ULAdb/r5N
0irVR0ge8qLxqkby0hipsa3Kh4lc/qxaXWfSh7MZQUqHi8QotqP/ioNxdMjOR4As
gBhz1SQW6wHgF23FhaU9Th0p0vLORUBOBZoQXCtVr/Gxik+8XC0PbvzSVPLO7700
jUodPcRlAgMBAAECggEAGBC2HfyyHVWCpEwpdwNql1XSuJPLn5IJaH+jA0GjwDup
oxIWBB7SfYEyh4Va0bWwabJv+0uTR/n2OHQHhMoZeYk2Mcef/1YzMWVwKorjUgGj
M9D8g7UIny766xXDtoxRtOtQgzWpssYy1q7NgME5iCEcqyT4W3BGa7gC8L43oeZI
qf4V+1V2/WojpMANy4jkv6J0jbpt2N/L1q/G62GpQGiIyhN3dFTow+mUZxnfqIiN
ooZENNtTYzE2YYhiZOFNGXPcKY2x2naqeTfQenSa+cHxm9rTYNo2F52Hamgrd8g3
Y0peUAktOuGSIgbowVUAxETWqMrbILb2nXHaoHN3NQKBgQDjl55E3lLW6CJbbWQp
KqoAvR44BlvTMl3rDv6AX/MHpu49JE/ULIlpL+UxkFFnwvafMhNhwwEvO3XbR7DF
303W1FTLsOlaEDSFCGzIURAv0wtiCUzpBd9wt1UBbOPdOfbimlx9psjH0wnvaygm
liymi0Z1NPEuUZiY6TW1sVqZdwKBgQDe5UPe1zj5tG/21dCBzwhNWPknjoFhoko/
JJe5Jw2pa6P+Rqu+dwSfHA8vXRn2bGH6mIP2Eh0aYZY/ZXa0pyXFQ5/PUM7/cnAZ
q0mFQ3I2WiqWvivHDPyaCold3vpIHKGBtcqTP532X4fm8p/012O5z3gLJhLgIg27
ImGUqz/IAwKBgAs3h8dhJbgNzNOwuoUE40gSChE8zv3Dt7lEDesJz5KK+abtyTlt
0H/sqmEc+cYhZ8JE14uz7rUDOzXJfL7j2JRD9sHrQDT+I3iDB8l/pUqWHjOAvdem
QHLvtjLRyRE4MCDO9swCkla24gB4yYvNTvoOVzSjnVdpEhpHNCx2Rz7VAoGAGVFJ
SEKCAjrwjMT0jgoKE18LzeZt470fWdS6Nxmsf5XuZq94SoYSTFBPmT2l+UuORXyV
YJnmHF0BR+oqdZKWw7VOramsGW/SM9g03aIvkuTi+YRYTJ+5AXY47CSroQ0/exA/
FkKfmqB3O1BLwu/EMBLUu89zTWoQzTS2iMB62ikCgYBGXpImpDzfH4GwmGt2NM1M
idIikatPH3xZS8MdcWlL7xc3Lyx0CZOYe7po5kd+r/zoEsoVPjJOEL8rvorTYnC1
d5EZUvnNibfpdkeDCVqlD2K64tuqIWUnowxcQTyUmgnOeupjHAnRExN71BkimIeT
Pl0LYzc5jCVc4r7zzq78TA==
-----END PRIVATE KEY-----"""

_TEST_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxilONxek+XVeZcugw/oB
Lp7EecrvOMKQgG+ILrluOY5jvA8Wjd+55CKcR6jYHh9llsiyw3vSLs7DD5ulEGyI
XgH8TP8wT3QZlxk8Pn9/PaBhcSE8py2nCf2PCgZ1aWe9ZO8YXZr3nnkOV3oSUdnM
ISaG6FjjOcGYfksHlT/86nxj5mBBy/q6zMpza8GAy0XKOjgPFCwHW/6+TdIq1UdI
HvKi8apG8tIYqbGtyoeJXP6sWl1n0oezGUFKh4vEKLaj/4qDcXTIzkeALIAYc9Uk
FusB4BdtxYWlPU4dKdLyzkVATgWaEFwrVa/xsYpPvFwtD2780lTyzu+9NI1KHT3E
ZQIDAQAB
-----END PUBLIC KEY-----"""

TEST_ISSUER = "https://mock-entra.test/tenant-sintetico/v2.0"
TEST_AUDIENCE = "mock-client-id-sintetico"
TEST_SCOPE = "access_as_user"


class MockEntraTokenValidator:
    """Só para testes — ver aviso no topo do módulo. Nunca faz nenhuma
    chamada de rede; a "chave pública" usada aqui é o par da chave de
    teste embutida, não algo obtido de um IdP. Aplica exatamente as mesmas
    regras de negócio do validador real (oid obrigatório, token delegado,
    tenant quando configurado) — só a origem da chave/rede muda."""

    def __init__(
        self,
        *,
        issuer: str = TEST_ISSUER,
        audience: str = TEST_AUDIENCE,
        tenant_id: str = "",
        required_scope: str = "",
    ):
        self._issuer = issuer
        self._audience = audience
        self._tenant_id = tenant_id
        self._required_scope = required_scope

    def validate(self, token: str) -> EntraClaims:
        try:
            payload = jwt.decode(
                token,
                _TEST_PUBLIC_KEY_PEM,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.PyJWTError as exc:
            raise TokenValidationError(str(exc)) from exc
        _validate_delegated_token(payload, required_scope=self._required_scope)
        return _claims_from_payload(payload, tenant_id=self._tenant_id)


def issue_mock_token(
    *,
    object_id: str | None = "oid-sintetico-omisso",
    email: str | None = None,
    expires_in_seconds: int = 3600,
    issued_seconds_ago: int = 0,
    not_before_seconds_from_now: int | None = None,
    issuer: str = TEST_ISSUER,
    audience: str = TEST_AUDIENCE,
    scope: str | None = TEST_SCOPE,
    include_oid: bool = True,
    include_sub: bool = True,
    extra_claims: dict | None = None,
) -> str:
    """Só para testes automatizados: assina um token sintético com a chave
    de teste local (nunca válido contra um Entra ID real, e nunca aceite
    pelo validador real — issuer/audience diferentes). Por omissão já
    inclui `scp='access_as_user'` (token delegado válido) e `oid`/`sub` —
    usar `include_oid=False`/`scope=None`/etc. para construir cenários de
    rejeição (claim em falta, token de aplicação, ...) sem ter de montar o
    payload à mão em cada teste."""
    now = int(time.time()) - issued_seconds_ago
    payload: dict = {
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    if include_sub:
        payload["sub"] = object_id
    if include_oid:
        payload["oid"] = object_id
    if not_before_seconds_from_now is not None:
        payload["nbf"] = now + not_before_seconds_from_now
    if email:
        payload["preferred_username"] = email
    if scope is not None:
        payload["scp"] = scope
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, _TEST_PRIVATE_KEY_PEM, algorithm="RS256")


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
def _cached_mock_validator(tenant_id: str, required_scope: str) -> MockEntraTokenValidator:
    return MockEntraTokenValidator(tenant_id=tenant_id, required_scope=required_scope)


def get_token_validator(settings) -> TokenValidator:
    """Fábrica única — nunca instanciar `RealEntraTokenValidator`/
    `MockEntraTokenValidator` diretamente fora daqui, para que a escolha
    fique sempre centrada em `Settings.entra_validation_mode`. Cacheada no
    processo por `(issuer, audience, jwks_url, tenant_id, required_scope)`
    — um `PyJWKClient` (que já faz o seu próprio cache de chaves) só é
    criado uma vez por configuração distinta, nunca a cada pedido HTTP."""
    if settings.entra_validation_mode == "mock":
        return _cached_mock_validator(settings.entra_tenant_id, settings.entra_required_scope)
    return _cached_real_validator(
        settings.resolved_entra_issuer(),
        settings.resolved_entra_audience(),
        settings.resolved_entra_jwks_url(),
        settings.entra_tenant_id,
        settings.entra_required_scope,
    )
