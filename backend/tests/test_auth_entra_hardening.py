"""Reforço da autenticação Entra ID (D-029): oid obrigatório sem fallback
para sub, tenant/scp/nbf validados, JIT linking configurável e auditado,
validador cacheado no processo.
"""
from __future__ import annotations

from app.config import Settings
from app.models.identity import AuthAuditLog, User
from app.security.entra_auth import get_token_validator
from tests.entra_mock import issue_mock_token


def _mock_settings(**overrides) -> Settings:
    base = dict(app_env="test", auth_enabled=True, entra_validation_mode="mock")
    base.update(overrides)
    return Settings(**base)


# --------------------------------------------------------------------------
# oid obrigatório, nunca sub como recurso.
# --------------------------------------------------------------------------


def test_token_without_oid_is_rejected_even_with_sub_present(make_api_client):
    client = make_api_client(_mock_settings())
    token = issue_mock_token(object_id="oid-x", include_oid=False, include_sub=True)
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_token_with_empty_oid_is_rejected(make_api_client):
    client = make_api_client(_mock_settings())
    token = issue_mock_token(object_id="", include_oid=True)
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


# --------------------------------------------------------------------------
# nbf, quando presente, é sempre validado (comportamento por omissão do
# PyJWT, nunca desativado neste código).
# --------------------------------------------------------------------------


def test_token_not_yet_valid_nbf_in_the_future_is_rejected(make_api_client):
    client = make_api_client(_mock_settings())
    token = issue_mock_token(object_id="oid-x", not_before_seconds_from_now=3600)
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_token_already_valid_nbf_in_the_past_is_accepted(db_session, make_api_client):
    db = db_session
    user = db.query(User).filter(User.email == "pm.um.sintetico@example.invalid").one()
    client = make_api_client(_mock_settings())
    token = issue_mock_token(object_id="oid-nbf-passado", email=user.email, not_before_seconds_from_now=-10)
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


# --------------------------------------------------------------------------
# Só tokens delegados (scp) — nunca tokens de aplicação (roles sem scp).
# --------------------------------------------------------------------------


def test_token_without_scp_is_rejected_as_app_only_token(make_api_client):
    client = make_api_client(_mock_settings())
    token = issue_mock_token(object_id="oid-x", scope=None, extra_claims={"roles": ["Admin.All"]})
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_token_with_required_scope_configured_and_matching_is_accepted(db_session, make_api_client):
    db = db_session
    user = db.query(User).filter(User.email == "pm.um.sintetico@example.invalid").one()
    client = make_api_client(_mock_settings(entra_required_scope="access_as_user"))
    token = issue_mock_token(object_id="oid-scope-ok", email=user.email, scope="access_as_user")
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_token_with_required_scope_configured_and_not_matching_is_rejected(make_api_client):
    client = make_api_client(_mock_settings(entra_required_scope="admin_access"))
    token = issue_mock_token(object_id="oid-scope-bad", scope="access_as_user")
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


# --------------------------------------------------------------------------
# Tenant (tid) validado quando ENTRA_TENANT_ID está configurado.
# --------------------------------------------------------------------------


def test_token_from_wrong_tenant_is_rejected_when_tenant_configured(make_api_client):
    client = make_api_client(_mock_settings(entra_tenant_id="tenant-esperado-sintetico"))
    token = issue_mock_token(object_id="oid-x", extra_claims={"tid": "tenant-diferente-sintetico"})
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_token_from_configured_tenant_is_accepted(db_session, make_api_client):
    db = db_session
    user = db.query(User).filter(User.email == "pm.um.sintetico@example.invalid").one()
    client = make_api_client(_mock_settings(entra_tenant_id="tenant-esperado-sintetico"))
    token = issue_mock_token(
        object_id="oid-tenant-ok", email=user.email, extra_claims={"tid": "tenant-esperado-sintetico"}
    )
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_no_tenant_check_when_not_configured(db_session, make_api_client):
    """Sem ENTRA_TENANT_ID configurado, o claim 'tid' (se existir) não é
    verificado — comportamento existente, preservado de propósito."""
    db = db_session
    user = db.query(User).filter(User.email == "pm.um.sintetico@example.invalid").one()
    client = make_api_client(_mock_settings())  # entra_tenant_id="" (omisso)
    token = issue_mock_token(object_id="oid-sem-tenant-check", email=user.email, extra_claims={"tid": "qualquer-coisa"})
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


# --------------------------------------------------------------------------
# JIT linking por email: configurável, desligado por omissão em
# staging/produção, e auditado quando acontece.
# --------------------------------------------------------------------------


def test_jit_link_writes_audit_log_entry(db_session, api_client_with_mock_entra_auth):
    db = db_session
    user = db.query(User).filter(User.email == "financeiro.sintetico@example.invalid").one()
    assert user.entra_object_id is None
    audit_before = db.query(AuthAuditLog).filter(AuthAuditLog.user_id == user.id).count()

    token = issue_mock_token(object_id="oid-financeiro-sintetico", email=user.email)
    resp = api_client_with_mock_entra_auth.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200

    audit_after = db.query(AuthAuditLog).filter(AuthAuditLog.user_id == user.id).count()
    assert audit_after == audit_before + 1
    entry = (
        db.query(AuthAuditLog)
        .filter(AuthAuditLog.user_id == user.id)
        .order_by(AuthAuditLog.occurred_at.desc())
        .first()
    )
    assert entry.event == "jit_link_by_email"
    assert "oid-financeiro-sintetico" in entry.detail


def test_jit_link_disabled_rejects_unlinked_user_by_email(db_session, make_api_client):
    db = db_session
    user = db.query(User).filter(User.email == "admin.sintetico@example.invalid").one()
    assert user.entra_object_id is None

    client = make_api_client(_mock_settings(entra_jit_link_by_email=False))
    token = issue_mock_token(object_id="oid-admin-sem-jit", email=user.email)
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401

    db.refresh(user)
    assert user.entra_object_id is None  # não foi ligado


def test_jit_link_disabled_by_default_in_staging_and_production():
    """resolved_entra_jit_link_by_email() nunca resolve True em
    staging/produção a menos que explicitamente configurado — testado
    diretamente na Settings (sem passar pela validação de arranque, que
    bloquearia esta combinação por outros motivos antes de lá chegar)."""
    settings = Settings.model_construct(app_env="staging", entra_jit_link_by_email=None)
    assert settings.resolved_entra_jit_link_by_email() is False

    settings_local = Settings.model_construct(app_env="local", entra_jit_link_by_email=None)
    assert settings_local.resolved_entra_jit_link_by_email() is True

    settings_explicit = Settings.model_construct(app_env="staging", entra_jit_link_by_email=True)
    assert settings_explicit.resolved_entra_jit_link_by_email() is True


# --------------------------------------------------------------------------
# Validador cacheado no processo — nunca um PyJWKClient novo por pedido.
# --------------------------------------------------------------------------


def test_get_token_validator_is_cached_for_equivalent_settings():
    settings_a = _mock_settings()
    settings_b = _mock_settings()  # configuração equivalente, instância diferente
    validator_a = get_token_validator(settings_a)
    validator_b = get_token_validator(settings_b)
    assert validator_a is validator_b  # mesma instância cacheada


def test_get_token_validator_differs_for_different_required_scope():
    validator_default = get_token_validator(_mock_settings())
    validator_scoped = get_token_validator(_mock_settings(entra_required_scope="admin_access"))
    assert validator_default is not validator_scoped


# --- Validador mock sem chave no código da aplicação (M13) -----------------


def test_app_code_has_no_embedded_private_key():
    from pathlib import Path

    import app

    for path in Path(app.__file__).parent.rglob("*.py"):
        assert "PRIVATE KEY-----" not in path.read_text(encoding="utf-8"), path


def test_mock_validator_rejects_everything_without_a_public_key_file():
    import pytest

    from app.security.entra_auth import MockEntraTokenValidator, TokenValidationUnavailableError

    with pytest.raises(TokenValidationUnavailableError, match="ENTRA_MOCK_PUBLIC_KEY_FILE"):
        MockEntraTokenValidator().validate(issue_mock_token(object_id="oid-x"))


def test_mock_validator_rejects_an_unreadable_public_key_file(tmp_path):
    import pytest

    from app.security.entra_auth import MockEntraTokenValidator, TokenValidationUnavailableError

    validator = MockEntraTokenValidator(public_key_file=str(tmp_path / "nao-existe.pem"))
    with pytest.raises(TokenValidationUnavailableError, match="não foi possível ler"):
        validator.validate(issue_mock_token(object_id="oid-x"))


def test_mock_validator_rejects_a_token_signed_by_another_key(tmp_path):
    import jwt
    import pytest
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from app.security.entra_auth import MockEntraTokenValidator, TokenValidationError
    from tests.entra_mock import TEST_PUBLIC_KEY_PEM

    key_file = tmp_path / "pub.pem"
    key_file.write_text(TEST_PUBLIC_KEY_PEM, encoding="ascii")
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    from app.security.entra_auth import TEST_AUDIENCE, TEST_ISSUER

    forged = jwt.encode(
        {"iss": TEST_ISSUER, "aud": TEST_AUDIENCE, "sub": "x", "oid": "x", "iat": 0, "exp": 99999999999, "scp": "access_as_user"},
        other,
        algorithm="RS256",
    )
    validator = MockEntraTokenValidator(public_key_file=str(key_file))
    with pytest.raises(TokenValidationError):
        validator.validate(forged)
    # E o token legítimo da suite passa com o mesmo ficheiro.
    assert validator.validate(issue_mock_token(object_id="oid-ok")).object_id == "oid-ok"
