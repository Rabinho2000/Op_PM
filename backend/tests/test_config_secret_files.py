"""Segredos por ficheiro (`*_FILE`): SECRET_KEY_FILE, DATABASE_URL_FILE e
DATABASE_PASSWORD_FILE. Constrói `Settings` com kwargs, sem tocar no ambiente
global dos testes. Nenhum valor aqui é um segredo real."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.fixture(autouse=True)
def _clean_secret_env(monkeypatch):
    for name in ("SECRET_KEY", "SECRET_KEY_FILE", "DATABASE_URL", "DATABASE_URL_FILE", "DATABASE_PASSWORD_FILE"):
        monkeypatch.delenv(name, raising=False)


def _write(tmp_path, name: str, content: str):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def _production_kwargs(**overrides) -> dict:
    base = dict(
        app_env="production",
        auth_enabled=True,
        entra_tenant_id="11111111-1111-1111-1111-111111111111",
        entra_client_id="22222222-2222-2222-2222-222222222222",
        entra_required_scope="access_as_user",
        cors_allowed_origins="https://op-pm.example.invalid",
    )
    base.update(overrides)
    return base


def test_secret_key_file_is_read_and_stripped(tmp_path):
    key_file = _write(tmp_path, "secret_key", "valor-de-teste-do-ficheiro\n")
    settings = Settings(
        **_production_kwargs(
            secret_key_file=key_file,
            database_url="postgresql+psycopg://u:p@db:5432/x",
        )
    )
    assert settings.secret_key == "valor-de-teste-do-ficheiro"


def test_secret_key_and_secret_key_file_together_is_an_error(tmp_path):
    key_file = _write(tmp_path, "secret_key", "abc")
    with pytest.raises(ValidationError, match="SECRET_KEY_FILE"):
        Settings(secret_key="outro", secret_key_file=key_file)


def test_missing_secret_file_fails_without_leaking_anything(tmp_path):
    with pytest.raises(ValidationError, match="SECRET_KEY_FILE") as excinfo:
        Settings(secret_key_file=str(tmp_path / "nao_existe"))
    assert "não foi possível ler" in str(excinfo.value)


def test_empty_secret_file_is_rejected(tmp_path):
    with pytest.raises(ValidationError, match="vazio"):
        Settings(secret_key_file=_write(tmp_path, "vazio", "  \n"))


def test_production_still_rejects_the_dev_secret_when_file_holds_it(tmp_path):
    from app.config import DEFAULT_DEV_SECRET_KEY

    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(
            **_production_kwargs(
                secret_key_file=_write(tmp_path, "k", DEFAULT_DEV_SECRET_KEY),
                database_url="postgresql+psycopg://u:p@db:5432/x",
            )
        )


def test_database_url_file_replaces_database_url(tmp_path):
    url_file = _write(tmp_path, "url", "postgresql+psycopg://u:p@db:5432/x\n")
    settings = Settings(database_url_file=url_file)
    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/x"


def test_database_url_and_url_file_together_is_an_error(tmp_path):
    url_file = _write(tmp_path, "url", "postgresql+psycopg://u:p@db:5432/x")
    with pytest.raises(ValidationError, match="DATABASE_URL_FILE"):
        Settings(database_url="postgresql+psycopg://u:p@db:5432/y", database_url_file=url_file)


def test_database_password_file_is_injected_and_escaped(tmp_path):
    pw_file = _write(tmp_path, "pw", "p@ss/w:rd%1\n")
    settings = Settings(
        database_url="postgresql+psycopg://op_pm@db:5432/op_pm",
        database_password_file=pw_file,
    )
    from sqlalchemy.engine import make_url

    url = make_url(settings.database_url)
    assert url.password == "p@ss/w:rd%1"
    assert url.username == "op_pm" and url.host == "db" and url.database == "op_pm"


def test_database_password_file_conflicts_with_password_in_url(tmp_path):
    pw_file = _write(tmp_path, "pw", "abc")
    with pytest.raises(ValidationError, match="DATABASE_PASSWORD_FILE"):
        Settings(database_url="postgresql+psycopg://u:p@db:5432/x", database_password_file=pw_file)


def test_database_password_file_rejected_for_sqlite(tmp_path):
    pw_file = _write(tmp_path, "pw", "abc")
    with pytest.raises(ValidationError, match="SQLite"):
        Settings(database_url="sqlite:///./x.db", database_password_file=pw_file)


def test_production_with_all_secrets_from_files_boots(tmp_path):
    settings = Settings(
        **_production_kwargs(
            secret_key_file=_write(tmp_path, "k", "um-segredo-de-teste-qualquer"),
            database_url="postgresql+psycopg://op_pm@db:5432/op_pm",
            database_password_file=_write(tmp_path, "pw", "pw-de-teste"),
        )
    )
    assert settings.is_production
    assert settings.database_url.startswith("postgresql+psycopg://op_pm:pw-de-teste@db")


def test_env_vars_are_honoured(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRET_KEY_FILE", _write(tmp_path, "k", "via-ambiente"))
    assert Settings().secret_key == "via-ambiente"
