"""Upgrade/downgrade contract for multi-installer calendar filters."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

BASE_REVISION = "d1f3b5c7e9a2"
REVISION = "c2a4e6b8d0f1"
PREFERENCE_TABLE = "works_calendar_preferences"
SAVED_VIEW_TABLE = "works_calendar_saved_views"


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


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def test_multi_installer_migration_preserves_legacy_rows_and_round_trips(tmp_path: Path):
    database_path = tmp_path / "multi-installer-migration.db"
    base = _run_alembic(database_path, "upgrade", BASE_REVISION)
    assert base.returncode == 0, base.stdout + base.stderr

    preference_user = str(uuid.uuid4())
    preference_id = str(uuid.uuid4())
    legacy_installer = str(uuid.uuid4())
    saved_view_user = str(uuid.uuid4())
    saved_view_id = str(uuid.uuid4())
    saved_view_installer = str(uuid.uuid4())
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            """INSERT INTO works_calendar_preferences
               (id, user_id, zoom, lifecycle_status, installer_id, show_idle)
               VALUES (?, ?, 'weeks', '[]', ?, 0)""",
            (preference_id, preference_user, legacy_installer),
        )
        connection.execute(
            """INSERT INTO works_calendar_saved_views
               (id, user_id, name, zoom, lifecycle_status, installer_id, show_idle)
               VALUES (?, ?, 'Legacy', 'weeks', '[]', ?, 0)""",
            (saved_view_id, saved_view_user, saved_view_installer),
        )

    upgraded = _run_alembic(database_path, "upgrade", REVISION)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == REVISION
        for table in (PREFERENCE_TABLE, SAVED_VIEW_TABLE):
            assert "installer_id" in _columns(connection, table)
            assert "installer_ids" in _columns(connection, table)
        assert connection.execute(
            "SELECT installer_id, installer_ids FROM works_calendar_preferences WHERE id = ?",
            (preference_id,),
        ).fetchone() == (legacy_installer, None)
        assert connection.execute(
            "SELECT installer_id, installer_ids FROM works_calendar_saved_views WHERE id = ?",
            (saved_view_id,),
        ).fetchone() == (saved_view_installer, None)

    downgraded = _run_alembic(database_path, "downgrade", BASE_REVISION)
    assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == BASE_REVISION
        for table in (PREFERENCE_TABLE, SAVED_VIEW_TABLE):
            assert "installer_ids" not in _columns(connection, table)
            assert "installer_id" in _columns(connection, table)
        assert connection.execute(
            "SELECT installer_id FROM works_calendar_preferences WHERE id = ?",
            (preference_id,),
        ).fetchone() == (legacy_installer,)
        assert connection.execute(
            "SELECT installer_id FROM works_calendar_saved_views WHERE id = ?",
            (saved_view_id,),
        ).fetchone() == (saved_view_installer,)

    upgraded_again = _run_alembic(database_path, "upgrade", REVISION)
    assert upgraded_again.returncode == 0, upgraded_again.stdout + upgraded_again.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == REVISION
        assert "installer_ids" in _columns(connection, PREFERENCE_TABLE)
        assert "installer_ids" in _columns(connection, SAVED_VIEW_TABLE)


def test_multi_installer_downgrade_keeps_first_id_in_legacy_column(tmp_path: Path):
    database_path = tmp_path / "multi-installer-downgrade.db"
    base = _run_alembic(database_path, "upgrade", BASE_REVISION)
    assert base.returncode == 0, base.stdout + base.stderr
    upgraded = _run_alembic(database_path, "upgrade", REVISION)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr

    preference_id, preference_user = str(uuid.uuid4()), str(uuid.uuid4())
    view_id, view_user = str(uuid.uuid4()), str(uuid.uuid4())
    first_installer, second_installer = str(uuid.uuid4()), str(uuid.uuid4())
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            """INSERT INTO works_calendar_preferences
               (id, user_id, zoom, lifecycle_status, installer_id, installer_ids, show_idle)
               VALUES (?, ?, 'weeks', '[]', NULL, ?, 0)""",
            (preference_id, preference_user, f'["{first_installer}", "{second_installer}"]'),
        )
        connection.execute(
            """INSERT INTO works_calendar_saved_views
               (id, user_id, name, zoom, lifecycle_status, installer_id, installer_ids, show_idle)
               VALUES (?, ?, 'Multi', 'weeks', '[]', NULL, ?, 0)""",
            (view_id, view_user, f'["{first_installer}", "{second_installer}"]'),
        )

    downgraded = _run_alembic(database_path, "downgrade", BASE_REVISION)
    assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT installer_id FROM works_calendar_preferences WHERE id = ?", (preference_id,)
        ).fetchone() == (first_installer,)
        assert connection.execute(
            "SELECT installer_id FROM works_calendar_saved_views WHERE id = ?", (view_id,)
        ).fetchone() == (first_installer,)
