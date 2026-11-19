"""Assinatura de tokens sintéticos para o modo `ENTRA_VALIDATION_MODE=mock`.

O código da aplicação não tem chave nenhuma (M13): este módulo gera um par RSA
efémero em cada processo de teste e o `conftest.py` grava a parte pública num
ficheiro, apontado por `ENTRA_MOCK_PUBLIC_KEY_FILE`. Os tokens assinados aqui
nunca seriam aceites por um Entra ID real (issuer/audience diferentes)."""
from __future__ import annotations

import time

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.security.entra_auth import TEST_AUDIENCE, TEST_ISSUER, TEST_SCOPE

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)

TEST_PRIVATE_KEY_PEM = _PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode("ascii")

TEST_PUBLIC_KEY_PEM = (
    _PRIVATE_KEY.public_key()
    .public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode("ascii")
)


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
    return jwt.encode(payload, TEST_PRIVATE_KEY_PEM, algorithm="RS256")
