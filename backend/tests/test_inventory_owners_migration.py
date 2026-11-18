"""SQLite round-trip for inventory location ownership."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BASE_REVISION = "c3e5a7b9d1f2"
THIS_REVISION = "d4f6b8c0e2a3"


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


def _assert_ok(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


def test_inventory_ownership_migration_backfills_and_round_trips_on_sqlite(tmp_path: Path):
    database_path = tmp_path / "inventory-ownership.db"
    _assert_ok(_run_alembic(database_path, "upgrade", BASE_REVISION))
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO inventory_locations "
            "(id, code, name, location_type, project_id, is_active, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            ("00000000-0000-0000-0000-000000000001", "OLD-CENTRAL", "Central existente", "central"),
        )
        connection.execute(
            "INSERT INTO inventory_locations "
            "(id, code, name, location_type, project_id, is_active, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            ("00000000-0000-0000-0000-000000000002", "OLD-OFFICE", "Escritório existente", "office"),
        )

    _assert_ok(_run_alembic(database_path, "upgrade", THIS_REVISION))
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute("SELECT owner FROM inventory_locations ORDER BY code").fetchall()
        assert rows == [("solcor",), ("solcor",)]
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(inventory_locations)")}
        assert "uq_inventory_locations_one_active_central_per_owner" in indexes
        assert "uq_inventory_locations_one_active_central" not in indexes
        columns = [row[2] for row in connection.execute(
            "PRAGMA index_info('uq_inventory_locations_one_active_central_per_owner')"
        )]
        assert columns == ["owner"]
        connection.execute(
            "INSERT INTO inventory_locations "
            "(id, code, name, location_type, owner, project_id, is_active, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            ("00000000-0000-0000-0000-000000000003", "NEW-VERDE-CENTRAL", "Central Verde", "central", "verde_milenar"),
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM inventory_locations WHERE location_type = 'central' AND is_active = 1"
        ).fetchone() == (2,)

    failed_downgrade = _run_alembic(database_path, "downgrade", BASE_REVISION)
    assert failed_downgrade.returncode != 0
    assert "cannot downgrade inventory ownership" in (failed_downgrade.stdout + failed_downgrade.stderr).lower()
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (THIS_REVISION,)
        assert "owner" in {row[1] for row in connection.execute("PRAGMA table_info(inventory_locations)")}
        connection.execute("DELETE FROM inventory_locations WHERE owner = 'verde_milenar'")

    _assert_ok(_run_alembic(database_path, "downgrade", BASE_REVISION))
    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(inventory_locations)")}
        assert "owner" not in columns
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(inventory_locations)")}
        assert "uq_inventory_locations_one_active_central" in indexes
        assert connection.execute("SELECT COUNT(*) FROM inventory_locations").fetchone() == (2,)

    _assert_ok(_run_alembic(database_path, "upgrade", THIS_REVISION))
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM inventory_locations WHERE owner = 'solcor'"
        ).fetchone() == (2,)
