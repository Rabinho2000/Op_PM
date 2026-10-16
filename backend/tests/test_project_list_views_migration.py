"""Alembic round-trip for the Projects-list persistence tables."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BASE_REVISION = "d9e1f3a5b7c2"
PREFERENCE_TABLE = "project_list_preferences"
VIEW_TABLE = "project_list_views"


def _run_alembic(database_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
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
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone() == (name,)


def test_project_list_migration_up_down_up_on_sqlite(tmp_path: Path):
    database_path = tmp_path / "project-list-migration.db"

    first = _run_alembic(database_path, "upgrade", "head")
    assert first.returncode == 0, first.stdout + first.stderr
    with sqlite3.connect(database_path) as connection:
        assert _table_exists(connection, PREFERENCE_TABLE)
        assert _table_exists(connection, VIEW_TABLE)
        preference_columns = {
            row[1] for row in connection.execute(f"PRAGMA table_info({PREFERENCE_TABLE})")
        }
        assert preference_columns == {
            "id", "user_id", "config", "created_at", "updated_at"
        }
        view_columns = {
            row[1] for row in connection.execute(f"PRAGMA table_info({VIEW_TABLE})")
        }
        assert view_columns == {
            "id", "user_id", "name", "config", "is_active", "created_at", "updated_at"
        }

    down = _run_alembic(database_path, "downgrade", BASE_REVISION)
    assert down.returncode == 0, down.stdout + down.stderr
    with sqlite3.connect(database_path) as connection:
        assert not _table_exists(connection, PREFERENCE_TABLE)
        assert not _table_exists(connection, VIEW_TABLE)

    second = _run_alembic(database_path, "upgrade", "head")
    assert second.returncode == 0, second.stdout + second.stderr
    with sqlite3.connect(database_path) as connection:
        assert _table_exists(connection, PREFERENCE_TABLE)
        assert _table_exists(connection, VIEW_TABLE)
