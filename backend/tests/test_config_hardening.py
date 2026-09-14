"""Bloqueio de configuração insegura em staging/produção (ver
docs/DECISIONS.md D-020). Constrói `Settings` diretamente com kwargs
explícitos, sem tocar nas variáveis de ambiente globais do processo de
teste (que continuam a apontar para 'test'/SQLite — ver conftest.py).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import DEFAULT_DEV_SECRET_KEY, Settings
from app.db import SessionLocal
from app.models.identity import User
from app.security.current_user import get_current_user


def _valid_production_kwargs(**overrides) -> dict:
    base = dict(
        app_env="production",
        auth_enabled=True,
        secret_key="a-real-production-secret-value",
        database_url="postgresql+psycopg://user:pass@host:5432/op_pm",
    )
    base.update(overrides)
    return base


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_blocks_startup_without_auth_enabled(app_env):
    with pytest.raises(ValidationError, match="AUTH_ENABLED"):
        Settings(**_valid_production_kwargs(app_env=app_env, auth_enabled=False))


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_blocks_startup_with_default_dev_secret_key(app_env):
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(**_valid_production_kwargs(app_env=app_env, secret_key=DEFAULT_DEV_SECRET_KEY))


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_blocks_startup_with_sqlite_database(app_env):
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(**_valid_production_kwargs(app_env=app_env, database_url="sqlite:///./data/x.db"))


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_blocks_startup_with_mock_entra_validation(app_env):
    """D-024: o validador de token 'mock' (app/security/entra_auth.py)
    nunca pode ser alcançável em staging/produção — só a chave de teste
    local, nunca um Entra ID real, validaria contra ele."""
    with pytest.raises(ValidationError, match="ENTRA_VALIDATION_MODE"):
        Settings(**_valid_production_kwargs(app_env=app_env, entra_validation_mode="mock"))


def test_blocks_startup_reports_all_problems_at_once():
    """Quatro problemas em simultâneo devem aparecer todos na mesma
    mensagem, não só o primeiro — poupa ciclos de tentativa-erro a quem
    configura."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            app_env="production",
            auth_enabled=False,
            secret_key=DEFAULT_DEV_SECRET_KEY,
            database_url="sqlite:///./data/x.db",
            entra_validation_mode="mock",
        )
    message = str(exc_info.value)
    assert "AUTH_ENABLED" in message
    assert "SECRET_KEY" in message
    assert "DATABASE_URL" in message
    assert "ENTRA_VALIDATION_MODE" in message


def test_valid_production_config_does_not_raise():
    settings = Settings(**_valid_production_kwargs())
    assert settings.app_env == "production"
    assert settings.auth_enabled is True


@pytest.mark.parametrize("app_env", ["local", "test"])
def test_local_and_test_environments_are_never_blocked(app_env):
    """As mesmas condições 'inseguras' são o comportamento por omissão
    esperado em local/test — nunca devem ser bloqueadas."""
    settings = Settings(
        app_env=app_env,
        auth_enabled=False,
        secret_key=DEFAULT_DEV_SECRET_KEY,
        database_url="sqlite:///./data/x.db",
    )
    assert settings.app_env == app_env


def test_dev_header_mechanism_rejected_outside_local_and_test(db_session):
    """Segunda barreira independente (D-020): mesmo chamando a dependência
    diretamente com uma Settings 'staging' válida (AUTH_ENABLED=true não
    aplicável aqui porque queremos testar precisamente o caminho
    AUTH_ENABLED=false + APP_ENV=staging, que a validação de arranque já
    bloquearia em condições normais — testado aqui de forma isolada, como
    defesa em profundidade)."""
    from fastapi import HTTPException

    staging_settings = Settings.model_construct(
        app_env="staging",
        auth_enabled=False,
        secret_key="irrelevante-para-este-teste",
        database_url="postgresql+psycopg://irrelevante",
        app_name="Op_PM API",
        graph_fallback_dir="./data/outbox",
        entra_tenant_id="",
        entra_client_id="",
        entra_client_secret="",
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

    db = db_session
    any_user = db.query(User).first()
    assert any_user is not None, "seed de desenvolvimento devia ter criado pelo menos um User"

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(x_dev_user_email=any_user.email, db=db, settings=staging_settings)
    assert exc_info.value.status_code == 403
    assert "local" in exc_info.value.detail.lower() or "test" in exc_info.value.detail.lower()


def test_dev_header_mechanism_works_in_test_environment(db_session):
    """Confirma o caminho positivo com a mesma chamada direta — evita que o
    teste anterior passe só porque a função está sempre a rejeitar."""
    from app.config import get_settings

    db = db_session
    any_user = db.query(User).first()
    assert any_user is not None

    resolved = get_current_user(x_dev_user_email=any_user.email, db=db, settings=get_settings())
    assert resolved.id == any_user.id
