"""Migração das preferências de obras: SQLite fresco e reversibilidade."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BASE_REVISION = "f5a7c9d1e3b2"


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


def test_works_preferences_migration_up_down_up_on_fresh_sqlite(tmp_path: Path):
    database_path = tmp_path / "works-preferences-migration.db"

    first = _run_alembic(database_path, "upgrade", "head")
    assert first.returncode == 0, first.stdout + first.stderr
    with sqlite3.connect(database_path) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("works_calendar_preferences",),
        ).fetchone()
    assert table == ("works_calendar_preferences",)

    down = _run_alembic(database_path, "downgrade", BASE_REVISION)
    assert down.returncode == 0, down.stdout + down.stderr
    with sqlite3.connect(database_path) as connection:
        removed = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("works_calendar_preferences",),
        ).fetchone()
    assert removed is None

    second = _run_alembic(database_path, "upgrade", "head")
    assert second.returncode == 0, second.stdout + second.stderr
    with sqlite3.connect(database_path) as connection:
        recreated = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("works_calendar_preferences",),
        ).fetchone()
    assert recreated == ("works_calendar_preferences",)
