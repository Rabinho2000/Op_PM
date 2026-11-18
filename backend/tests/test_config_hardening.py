"""Bloqueio de configuração insegura em staging/produção (ver
docs/DECISIONS.md D-020). Constrói `Settings` diretamente com kwargs
explícitos, sem tocar nas variáveis de ambiente globais do processo de
teste (que continuam a apontar para 'test'/SQLite — ver conftest.py).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

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
        entra_tenant_id="11111111-1111-1111-1111-111111111111",
        entra_client_id="22222222-2222-2222-2222-222222222222",
        entra_required_scope="access_as_user",
        cors_allowed_origins="https://op-pm.example.invalid",
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


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_blocks_startup_without_entra_tenant_id(app_env):
    with pytest.raises(ValidationError, match="ENTRA_TENANT_ID"):
        Settings(**_valid_production_kwargs(app_env=app_env, entra_tenant_id=""))


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_blocks_startup_without_entra_client_id(app_env):
    with pytest.raises(ValidationError, match="ENTRA_CLIENT_ID"):
        Settings(**_valid_production_kwargs(app_env=app_env, entra_client_id=""))


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_blocks_startup_without_entra_required_scope(app_env):
    with pytest.raises(ValidationError, match="ENTRA_REQUIRED_SCOPE"):
        Settings(**_valid_production_kwargs(app_env=app_env, entra_required_scope=""))


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_blocks_startup_without_cors_allowed_origins(app_env):
    with pytest.raises(ValidationError, match="CORS_ALLOWED_ORIGINS"):
        Settings(**_valid_production_kwargs(app_env=app_env, cors_allowed_origins=""))


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_blocks_startup_with_empty_secret_key(app_env):
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(**_valid_production_kwargs(app_env=app_env, secret_key="   "))


@pytest.mark.parametrize(
    "override_field,override_value",
    [
        ("entra_issuer", "https://issuer.example.invalid/v2.0"),
        ("entra_jwks_url", "https://issuer.example.invalid/keys"),
        ("entra_audience", "api://alguma-audiencia"),
    ],
)
@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_blocks_startup_with_partial_entra_issuer_audience_jwks_override(app_env, override_field, override_value):
    """Definir só um de ENTRA_ISSUER/ENTRA_JWKS_URL/ENTRA_AUDIENCE é quase
    sempre um erro de configuração — os outros dois cairiam para o valor
    derivado de ENTRA_TENANT_ID/ENTRA_CLIENT_ID, uma mistura inesperada."""
    with pytest.raises(ValidationError, match="ENTRA_ISSUER/ENTRA_JWKS_URL/ENTRA_AUDIENCE"):
        Settings(**_valid_production_kwargs(app_env=app_env, **{override_field: override_value}))


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_allows_startup_with_complete_entra_issuer_audience_jwks_override(app_env):
    settings = Settings(
        **_valid_production_kwargs(
            app_env=app_env,
            entra_issuer="https://issuer.example.invalid/v2.0",
            entra_jwks_url="https://issuer.example.invalid/keys",
            entra_audience="api://alguma-audiencia",
        )
    )
    assert settings.resolved_entra_issuer() == "https://issuer.example.invalid/v2.0"


def test_blocks_startup_reports_all_problems_at_once():
    """Vários problemas em simultâneo devem aparecer todos na mesma
    mensagem, não só o primeiro — poupa ciclos de tentativa-erro a quem
    configura."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            app_env="production",
            auth_enabled=False,
            secret_key=DEFAULT_DEV_SECRET_KEY,
            database_url="sqlite:///./data/x.db",
            entra_validation_mode="mock",
            entra_tenant_id="",
            entra_client_id="",
            entra_required_scope="",
            cors_allowed_origins="",
        )
    message = str(exc_info.value)
    assert "AUTH_ENABLED" in message
    assert "SECRET_KEY" in message
    assert "DATABASE_URL" in message
    assert "ENTRA_VALIDATION_MODE" in message
    assert "ENTRA_TENANT_ID" in message
    assert "ENTRA_CLIENT_ID" in message
    assert "ENTRA_REQUIRED_SCOPE" in message
    assert "CORS_ALLOWED_ORIGINS" in message


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


# --- A7: APP_ENV obrigatório (fail-closed) ---

_BACKEND_DIR = Path(__file__).resolve().parents[1]


def _run_python_without_app_env(code: str, tmp_path: Path, **extra_env: str) -> subprocess.CompletedProcess:
    """Corre `code` num processo novo, sem APP_ENV e a partir de uma pasta
    vazia (sem `.env` que o possa fornecer)."""
    env = {k: v for k, v in os.environ.items() if k != "APP_ENV"}
    env["PYTHONPATH"] = str(_BACKEND_DIR)
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60
    )


def test_settings_require_app_env(monkeypatch, tmp_path):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.chdir(tmp_path)  # sem .env à mão
    with pytest.raises(ValidationError, match="APP_ENV"):
        Settings()


def test_app_refuses_to_start_without_app_env(tmp_path):
    result = _run_python_without_app_env("import app.main", tmp_path)
    assert result.returncode != 0
    assert "ConfigurationError" in result.stderr
    assert "APP_ENV não está definido" in result.stderr


def test_app_refuses_to_start_with_unknown_app_env(tmp_path):
    result = _run_python_without_app_env("import app.main", tmp_path, APP_ENV="prod")
    assert result.returncode != 0
    assert "APP_ENV não está definido (ou tem um valor inválido)" in result.stderr


def test_cli_refuses_to_start_without_app_env(tmp_path):
    # As CLIs partilham o `get_settings()`; o `demo` é a que mexe em dados.
    result = _run_python_without_app_env("from app.cli import demo; demo.main(['setup'])", tmp_path)
    assert result.returncode != 0
    assert "APP_ENV não está definido" in result.stderr


def test_alembic_refuses_to_run_without_app_env(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(_BACKEND_DIR / "alembic.ini"), "current"],
        cwd=tmp_path,
        env={**{k: v for k, v in os.environ.items() if k != "APP_ENV"}, "PYTHONPATH": str(_BACKEND_DIR)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "APP_ENV não está definido" in result.stderr


def test_error_message_never_leaks_other_settings(tmp_path):
    result = _run_python_without_app_env(
        "import app.main", tmp_path, SECRET_KEY="valor-secreto-que-nao-deve-aparecer"
    )
    assert result.returncode != 0
    assert "valor-secreto-que-nao-deve-aparecer" not in result.stderr + result.stdout
