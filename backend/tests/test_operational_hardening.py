"""Correções operacionais da Fase 0 (docs/ANALISE_OP_PM.md): migração do envio
único por semana e /docs fechado em instâncias com dados reais."""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.config import Settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS_HEAD = "a6c8e0f2d4b1"
THIS_REVISION = "b9e1d3f5a7c2"


def _alembic(database_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "APP_ENV": "test",
            "AUTH_ENABLED": "false",
            "DATABASE_URL": f"sqlite:///{database_path}",
            "EXPECTED_DB_DIALECT": "sqlite",
        }
    )
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR, env=environment, capture_output=True, text=True, check=False,
    )


def _insert_send(engine: sa.Engine, project_id: str, status: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO client_report_sends (id, project_id, iso_week, status, \"trigger\", subject, "
                "body_html, from_email, to_emails, cc_emails, created_at) VALUES "
                "(:id, :project_id, '2026-W40', :status, 'manual', 's', 'b', 'pm@example.invalid', '[]', '[]', CURRENT_TIMESTAMP)"
            ),
            {"id": uuid.uuid4().hex, "project_id": project_id, "status": status},
        )


def _project(_engine: sa.Engine) -> str:
    # Sem PRAGMA foreign_keys, o SQLite não exige o projeto: basta um ID estável.
    return uuid.uuid4().hex


def test_migration_creates_partial_unique_index_and_downgrades(tmp_path):
    database = tmp_path / "migration.db"
    result = _alembic(database, "upgrade", PREVIOUS_HEAD)
    assert result.returncode == 0, result.stdout + result.stderr
    engine = sa.create_engine(f"sqlite:///{database}")
    project_id = _project(engine)
    _insert_send(engine, project_id, "sent")
    _insert_send(engine, project_id, "failed")

    result = _alembic(database, "upgrade", THIS_REVISION)
    assert result.returncode == 0, result.stdout + result.stderr
    _insert_send(engine, project_id, "outbox_local")  # estado inativo: permitido
    with pytest.raises(sa.exc.IntegrityError):
        _insert_send(engine, project_id, "pending")

    result = _alembic(database, "downgrade", PREVIOUS_HEAD)
    assert result.returncode == 0, result.stdout + result.stderr
    _insert_send(engine, project_id, "pending")
    engine.dispose()


def test_migration_refuses_to_run_over_existing_duplicates(tmp_path):
    database = tmp_path / "duplicates.db"
    assert _alembic(database, "upgrade", PREVIOUS_HEAD).returncode == 0
    engine = sa.create_engine(f"sqlite:///{database}")
    project_id = _project(engine)
    _insert_send(engine, project_id, "sent")
    _insert_send(engine, project_id, "pending_review")
    engine.dispose()

    result = _alembic(database, "upgrade", THIS_REVISION)
    assert result.returncode != 0
    assert "mais de um envio ativo" in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"app_env": "local"}, True),
        ({"app_env": "test"}, True),
        ({"app_env": "local", "demo_real_data": True}, False),
        ({"app_env": "local", "demo_real_data": True, "api_docs_enabled": True}, True),
        ({"app_env": "test", "api_docs_enabled": False}, False),
    ],
)
def test_api_docs_are_closed_on_instances_with_real_data(overrides, expected):
    assert Settings(**overrides).resolved_api_docs_enabled() is expected
