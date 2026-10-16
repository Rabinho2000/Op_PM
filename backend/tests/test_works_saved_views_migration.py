"""Migração das vistas guardadas do calendário de obras."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BASE_REVISION = "a9d4f6c2e8b1"
TABLE = "works_calendar_saved_views"


def _run_alembic(database_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "APP_ENV": "test",
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
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row == (name,)


def test_saved_views_migration_up_down_up_on_fresh_sqlite(tmp_path: Path):
    database_path = tmp_path / "works-saved-views-migration.db"

    first = _run_alembic(database_path, "upgrade", "head")
    assert first.returncode == 0, first.stdout + first.stderr
    with sqlite3.connect(database_path) as connection:
        assert _table_exists(connection, TABLE)
        assert _table_exists(connection, "works_calendar_preferences")
        columns = {
            row[1]: row for row in connection.execute(f"PRAGMA table_info({TABLE})")
        }
        assert set(columns) == {
            "id",
            "user_id",
            "name",
            "zoom",
            "lifecycle_status",
            "pm_person_id",
            "installer_id",
            "team_id",
            "show_idle",
            "created_at",
            "updated_at",
        }
        unique_indexes = connection.execute(f"PRAGMA index_list({TABLE})").fetchall()
        assert any(row[2] for row in unique_indexes)

    down = _run_alembic(database_path, "downgrade", BASE_REVISION)
    assert down.returncode == 0, down.stdout + down.stderr
    with sqlite3.connect(database_path) as connection:
        assert not _table_exists(connection, TABLE)
        assert _table_exists(connection, "works_calendar_preferences")

    second = _run_alembic(database_path, "upgrade", "head")
    assert second.returncode == 0, second.stdout + second.stderr
    with sqlite3.connect(database_path) as connection:
        assert _table_exists(connection, TABLE)
