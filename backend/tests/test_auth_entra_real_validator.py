"""`RealEntraTokenValidator` com um `PyJWKClient` falso (sem rede).

Até aqui só o validador mock estava testado (tests/test_auth_entra.py). Estes
testes exercitam o validador real — a lógica de `kid`, assinatura RS256,
`tid`, `exp`/`iat` — contra um JWKS fabricado em memória, e fixam a regra de
M3 (docs/ANALISE_OP_PM.md): um token inválido é 401, mas uma falha de rede ou
do JWKS é 503 (nunca 401, para o frontend não a mostrar como "sessão
expirada").

O `PyJWKClient` falso herda do real e só substitui `fetch_data`, para que a
procura por `kid`, a cache e o comportamento de recarga sejam os do PyJWT.
"""
from __future__ import annotations

import json
import logging
import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClient
from jwt.algorithms import RSAAlgorithm

from app.config import Settings
from app.security import current_user as current_user_module
from app.security.entra_auth import (
    JWKS_TIMEOUT_SECONDS,
    TokenValidationError,
    TokenValidationUnavailableError,
    RealEntraTokenValidator,
    issue_mock_token,
)

TENANT = "tenant-sintetico-1111"
OTHER_TENANT = "tenant-sintetico-9999"
CLIENT_ID = "cliente-sintetico-2222"
ISSUER = f"https://login.example.invalid/{TENANT}/v2.0"
JWKS_URL = "https://login.example.invalid/discovery/v2.0/keys"
KID = "kid-sintetico-1"


def _new_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def signing_key():
    return _new_key()


@pytest.fixture(scope="module")
def other_key():
    return _new_key()


def _jwks_for(key, kid: str = KID) -> dict:
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


class FakeJWKClient(PyJWKClient):
    """`PyJWKClient` sem rede: devolve `payload`, ou levanta `error`."""

    def __init__(self, payload=None, error: Exception | None = None):
        super().__init__(JWKS_URL, timeout=JWKS_TIMEOUT_SECONDS)
        self._payload = payload
        self._error = error
        self.fetches = 0

    def fetch_data(self):
        self.fetches += 1
        if self._error is not None:
            raise self._error
        return self._payload


def _validator(jwks_client, **overrides) -> RealEntraTokenValidator:
    kwargs = dict(
        issuer=ISSUER,
        audience=CLIENT_ID,
        jwks_url=JWKS_URL,
        tenant_id=TENANT,
        required_scope="access_as_user",
        jwks_client=jwks_client,
    )
    kwargs.update(overrides)
    return RealEntraTokenValidator(**kwargs)


def _claims(**overrides) -> dict:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "tid": TENANT,
        "sub": "sub-sintetico",
        "oid": "oid-sintetico",
        "scp": "access_as_user",
        "preferred_username": "pm.um.sintetico@example.invalid",
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def _sign(key, claims: dict | None = None, *, kid: str | None = KID, algorithm: str = "RS256") -> str:
    headers = {"kid": kid} if kid else None
    return pyjwt.encode(_claims() if claims is None else claims, key, algorithm=algorithm, headers=headers)


@pytest.fixture()
def validator(signing_key):
    return _validator(FakeJWKClient(_jwks_for(signing_key)))


# --------------------------------------------------------------------------
# Caminho feliz — a base de todas as comparações abaixo.
# --------------------------------------------------------------------------


def test_valid_token_is_accepted(validator, signing_key):
    claims = validator.validate(_sign(signing_key))
    assert claims.object_id == "oid-sintetico"
    assert claims.email == "pm.um.sintetico@example.invalid"


def test_default_jwks_client_has_explicit_timeout():
    """Sem timeout o PyJWKClient espera 30 s por omissão: um JWKS lento
    prenderia os workers. O validador cria o cliente com 5 s."""
    real = RealEntraTokenValidator(issuer=ISSUER, audience=CLIENT_ID, jwks_url=JWKS_URL)
    assert real._jwks_client.timeout == JWKS_TIMEOUT_SECONDS == 5


# --------------------------------------------------------------------------
# Token inválido -> TokenValidationError (401).
# --------------------------------------------------------------------------


def test_rs256_signed_with_another_key_is_rejected(validator, other_key):
    """Mesmo `kid` e claims válidas, mas assinado por outra chave."""
    with pytest.raises(TokenValidationError):
        validator.validate(_sign(other_key))


def test_unknown_kid_is_rejected_as_invalid_token_not_as_unavailable(signing_key):
    jwk_client = FakeJWKClient(_jwks_for(signing_key))
    with pytest.raises(TokenValidationError):
        _validator(jwk_client).validate(_sign(signing_key, kid="kid-que-o-jwks-nao-tem"))


def test_token_without_kid_is_rejected(validator, signing_key):
    with pytest.raises(TokenValidationError):
        validator.validate(_sign(signing_key, kid=None))


def test_token_issued_by_the_mock_is_rejected_in_real_mode(validator):
    """O token do mock (chave de teste pública no repo) nunca pode ser
    aceite pelo validador real — nem sem `kid`, nem com o `kid` verdadeiro."""
    mock_token = issue_mock_token(object_id="oid-sintetico")
    with pytest.raises(TokenValidationError):
        validator.validate(mock_token)

    header = pyjwt.get_unverified_header(mock_token)
    claims = pyjwt.decode(mock_token, options={"verify_signature": False})
    from app.security.entra_auth import _TEST_PRIVATE_KEY_PEM

    forged = pyjwt.encode(claims, _TEST_PRIVATE_KEY_PEM, algorithm="RS256", headers={**header, "kid": KID})
    with pytest.raises(TokenValidationError):
        validator.validate(forged)


@pytest.mark.parametrize("missing", ["exp", "iat"])
def test_token_without_exp_or_iat_is_rejected(validator, signing_key, missing):
    claims = _claims(**{missing: None})
    assert missing not in claims
    with pytest.raises(TokenValidationError):
        validator.validate(_sign(signing_key, claims))


def test_expired_token_is_rejected(validator, signing_key):
    now = int(time.time())
    with pytest.raises(TokenValidationError):
        validator.validate(_sign(signing_key, _claims(iat=now - 7200, exp=now - 3600)))


def test_token_from_another_tenant_is_rejected(validator, signing_key):
    with pytest.raises(TokenValidationError, match="tenant"):
        validator.validate(_sign(signing_key, _claims(tid=OTHER_TENANT)))


def test_token_without_tid_is_rejected(validator, signing_key):
    with pytest.raises(TokenValidationError, match="tenant"):
        validator.validate(_sign(signing_key, _claims(tid=None)))


def test_application_token_without_scp_is_rejected(validator, signing_key):
    with pytest.raises(TokenValidationError):
        validator.validate(_sign(signing_key, _claims(scp=None, roles=["Tarefa.Aplicacao"])))


def test_alg_none_token_is_rejected(validator):
    unsigned = pyjwt.encode(_claims(), None, algorithm="none", headers={"kid": KID})
    with pytest.raises(TokenValidationError):
        validator.validate(unsigned)


def test_hs256_token_using_public_key_as_secret_is_rejected(validator, signing_key):
    """Confusão de algoritmo: HS256 com a chave pública do JWKS como segredo."""
    from cryptography.hazmat.primitives import serialization

    public_pem = signing_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    # O PyJWT recusa-se a assinar HS256 com uma chave PEM; monta-se à mão.
    import base64
    import hashlib
    import hmac

    def b64(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    signing_input = (
        b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode())
        + b"."
        + b64(json.dumps(_claims()).encode())
    )
    signature = b64(hmac.new(public_pem, signing_input, hashlib.sha256).digest())
    forged = (signing_input + b"." + signature).decode()
    with pytest.raises(TokenValidationError):
        validator.validate(forged)


def test_malformed_token_is_rejected(validator):
    with pytest.raises(TokenValidationError):
        validator.validate("isto-nao-e-um-jwt")


# --------------------------------------------------------------------------
# Falha do JWKS/da rede -> TokenValidationUnavailableError (503), M3.
# --------------------------------------------------------------------------


def test_jwks_connection_failure_is_unavailable_not_invalid(signing_key):
    jwk_client = FakeJWKClient(error=pyjwt.PyJWKClientConnectionError("Fail to fetch data from the url, err: timeout"))
    with pytest.raises(TokenValidationUnavailableError):
        _validator(jwk_client).validate(_sign(signing_key))


@pytest.mark.parametrize(
    "payload, error",
    [
        (["isto", "nao", "e", "um", "objeto"], None),  # JWKS que não é um objeto JSON
        ({"keys": []}, None),  # JWKS sem chaves utilizáveis
        (None, json.JSONDecodeError("Expecting value", "<html>502</html>", 0)),  # corpo não-JSON (ex. página de erro)
    ],
    ids=["jwks-nao-objeto", "jwks-sem-chaves", "jwks-nao-json"],
)
def test_unusable_jwks_is_unavailable_not_invalid(signing_key, payload, error):
    jwk_client = FakeJWKClient(payload=payload, error=error)
    with pytest.raises(TokenValidationUnavailableError):
        _validator(jwk_client).validate(_sign(signing_key))


def test_jwks_failure_is_not_a_token_validation_error(signing_key):
    """As duas exceções são irmãs: um `except TokenValidationError` (401)
    nunca apanha por engano uma falha de infraestrutura."""
    assert not issubclass(TokenValidationUnavailableError, TokenValidationError)


# --------------------------------------------------------------------------
# HTTP: 401 vs 503 (e log) através de `get_current_user`.
# --------------------------------------------------------------------------


def _real_settings() -> Settings:
    return Settings(
        app_env="test",
        auth_enabled=True,
        entra_validation_mode="real",
        entra_tenant_id=TENANT,
        entra_client_id=CLIENT_ID,
        entra_required_scope="access_as_user",
    )


def _client_with_validator(make_api_client, monkeypatch, real_validator):
    monkeypatch.setattr(current_user_module, "get_token_validator", lambda settings: real_validator)
    return make_api_client(_real_settings())


def test_http_jwks_outage_returns_503_with_generic_message_and_warning(
    make_api_client, monkeypatch, signing_key, caplog
):
    jwk_client = FakeJWKClient(error=pyjwt.PyJWKClientConnectionError("Fail to fetch data: <urlopen error ligacao-recusada>"))
    client = _client_with_validator(make_api_client, monkeypatch, _validator(jwk_client))

    with caplog.at_level(logging.WARNING, logger="app.security.current_user"):
        resp = client.get("/me", headers={"Authorization": f"Bearer {_sign(signing_key)}"})

    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "indisponível" in detail
    # Mensagem genérica: nada do erro técnico chega ao cliente.
    assert "ligacao-recusada" not in resp.text and "urlopen" not in resp.text
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and r.name == "app.security.current_user"]
    assert warnings and "ligacao-recusada" in warnings[0].getMessage()


def test_http_invalid_tokens_remain_401(make_api_client, monkeypatch, signing_key, other_key):
    client = _client_with_validator(make_api_client, monkeypatch, _validator(FakeJWKClient(_jwks_for(signing_key))))
    for bad in (
        _sign(other_key),  # assinatura de outra chave
        _sign(signing_key, kid="kid-desconhecido"),  # kid desconhecido
        _sign(signing_key, _claims(tid=OTHER_TENANT)),  # outro tenant
        _sign(signing_key, _claims(exp=None)),  # sem exp
        issue_mock_token(object_id="oid-sintetico"),  # token do mock
    ):
        resp = client.get("/me", headers={"Authorization": f"Bearer {bad}"})
        assert resp.status_code == 401, resp.text


def test_http_valid_token_reaches_the_user_lookup(make_api_client, monkeypatch, signing_key):
    """Token válido mas utilizador não provisionado: já passou o JWKS, por isso
    é o 401 de "não provisionado" e não um 503."""
    client = _client_with_validator(make_api_client, monkeypatch, _validator(FakeJWKClient(_jwks_for(signing_key))))
    token = _sign(signing_key, _claims(oid="oid-sem-utilizador", preferred_username="ninguem@example.invalid"))
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert "não provisionado" in resp.json()["detail"]
