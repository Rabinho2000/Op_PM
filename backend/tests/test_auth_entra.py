"""Autenticação real via Microsoft Entra ID (mock — ver
app/security/entra_auth.py) e o mecanismo de utilizador de desenvolvimento
fora do seu ambiente permitido. Cobre os cenários pedidos explicitamente
para a Fase 1: token válido, inválido, expirado, utilizador sem papel, e
X-Dev-User-Email em staging/produção.
"""
from __future__ import annotations

import jwt as pyjwt
import pytest
from fastapi import HTTPException

from app.config import Settings
from app.models.identity import User
from app.models.people import Person
from app.security.entra_auth import TEST_AUDIENCE, TEST_ISSUER, issue_mock_token
from app.security.current_user import get_current_user


def test_valid_token_resolves_user_and_links_entra_object_id(db_session, api_client_with_mock_entra_auth):
    db = db_session
    user = db.query(User).filter(User.email == "pm.um.sintetico@example.invalid").one()
    assert user.entra_object_id is None  # ainda não ligado

    token = issue_mock_token(object_id="oid-pm-um-sintetico", email=user.email)
    resp = api_client_with_mock_entra_auth.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "pm.um.sintetico@example.invalid"
    assert "project_manager" in body["roles"]

    # Ligação "just-in-time" por email aconteceu e ficou persistida.
    db.refresh(user)
    assert user.entra_object_id == "oid-pm-um-sintetico"


def test_second_login_resolves_directly_by_entra_object_id(db_session, api_client_with_mock_entra_auth):
    """Depois de ligado, uma segunda autenticação nem precisa do email —
    o object_id já é suficiente (o caminho principal, não o de recurso)."""
    db = db_session
    user = db.query(User).filter(User.email == "chefe.sintetico@example.invalid").one()
    user.entra_object_id = "oid-chefe-ja-ligado"
    db.commit()

    token = issue_mock_token(object_id="oid-chefe-ja-ligado")  # sem email desta vez
    resp = api_client_with_mock_entra_auth.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json()["email"] == "chefe.sintetico@example.invalid"


def test_invalid_token_signature_is_rejected(api_client_with_mock_entra_auth):
    bad_token = pyjwt.encode(
        {"iss": TEST_ISSUER, "aud": TEST_AUDIENCE, "sub": "x", "oid": "x", "iat": 0, "exp": 99999999999},
        "chave-completamente-errada",
        algorithm="HS256",
    )
    resp = api_client_with_mock_entra_auth.get("/me", headers={"Authorization": f"Bearer {bad_token}"})
    assert resp.status_code == 401


def test_malformed_token_is_rejected(api_client_with_mock_entra_auth):
    resp = api_client_with_mock_entra_auth.get("/me", headers={"Authorization": "Bearer isto-nao-e-um-jwt"})
    assert resp.status_code == 401


def test_missing_authorization_header_is_rejected(api_client_with_mock_entra_auth):
    resp = api_client_with_mock_entra_auth.get("/me")
    assert resp.status_code == 401


def test_expired_token_is_rejected(api_client_with_mock_entra_auth):
    token = issue_mock_token(object_id="oid-qualquer", expires_in_seconds=-60)
    resp = api_client_with_mock_entra_auth.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_wrong_audience_is_rejected(api_client_with_mock_entra_auth):
    token = issue_mock_token(object_id="oid-x", audience="outra-aplicacao-qualquer")
    resp = api_client_with_mock_entra_auth.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_wrong_issuer_is_rejected(api_client_with_mock_entra_auth):
    token = issue_mock_token(object_id="oid-x", issuer="https://nao-e-o-tenant-esperado.test/v2.0")
    resp = api_client_with_mock_entra_auth.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_user_without_any_role_has_empty_permissions(db_session, api_client_with_mock_entra_auth):
    db = db_session
    person = Person(display_name="Pessoa Sintética Sem Papel")
    db.add(person)
    db.flush()
    orphan_user = User(person_id=person.id, email="sem.papel.sintetico@example.invalid", is_active=True)
    db.add(orphan_user)
    db.commit()

    token = issue_mock_token(object_id="oid-sem-papel", email=orphan_user.email)
    resp = api_client_with_mock_entra_auth.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["roles"] == []
    assert body["permissions"] == []


def test_token_for_unknown_email_and_unknown_object_id_is_rejected(api_client_with_mock_entra_auth):
    token = issue_mock_token(object_id="oid-completamente-desconhecido", email="ninguem@example.invalid")
    resp = api_client_with_mock_entra_auth.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


# --------------------------------------------------------------------------
# X-Dev-User-Email nunca deve funcionar fora de local/test — mesmo quando
# AUTH_ENABLED=true (o cabeçalho de dev nem é consultado nesse caminho).
# --------------------------------------------------------------------------


def test_dev_header_ignored_when_auth_enabled_is_true(db_session):
    """Com AUTH_ENABLED=true, o mecanismo de dev nem é considerado — só o
    token Bearer importa. Chamar a função diretamente prova isto sem
    depender de HTTP: o cabeçalho X-Dev-User-Email é passado mas nunca
    chega a ser lido."""
    db = db_session
    settings = Settings(app_env="test", auth_enabled=True, entra_validation_mode="mock")
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(
            authorization=None,
            x_dev_user_email="chefe.sintetico@example.invalid",  # ignorado de propósito
            db=db,
            settings=settings,
        )
    assert exc_info.value.status_code == 401
    assert "Authorization" in exc_info.value.detail


def test_dev_header_rejected_outside_local_and_test_even_with_auth_disabled(db_session):
    """Complementa tests/test_config_hardening.py: repete o cenário aqui,
    junto dos outros testes de autenticação pedidos explicitamente para a
    Fase 1 ('tentativa de usar X-Dev-User-Email em staging/produção')."""
    db = db_session
    any_user = db.query(User).first()
    assert any_user is not None

    staging_settings = Settings.model_construct(
        app_env="staging",
        auth_enabled=False,
        secret_key="irrelevante-para-este-teste",
        database_url="postgresql+psycopg://irrelevante",
        entra_validation_mode="real",
        app_name="Op_PM API",
        graph_fallback_dir="./data/outbox",
        cors_allowed_origins="",
        entra_tenant_id="",
        entra_client_id="",
        entra_client_secret="",
        entra_issuer="",
        entra_jwks_url="",
        entra_audience="",
        graph_enabled=False,
        graph_tenant_id="",
        graph_client_id="",
        graph_client_secret="",
        clickup_enabled=False,
        clickup_token="",
        clickup_list_id="",
        financial_enabled=False,
        financial_mode="mock",
        financial_csv_path="",
        financial_api_base_url="",
        financial_api_key="",
        claude_enabled=False,
        claude_api_key="",
        claude_model="claude-sonnet-5",
    )

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(
            authorization=None,
            x_dev_user_email=any_user.email,
            db=db,
            settings=staging_settings,
        )
    assert exc_info.value.status_code == 403
