"""Migração Alembic das duas capacidades de preços, sem dados privados."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def _alembic(db_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.update(
        {
            "APP_ENV": "test",
            "AUTH_ENABLED": "false",
            "DATABASE_URL": f"sqlite:///{db_path}",
            "EXPECTED_DB_DIALECT": "sqlite",
        }
    )
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_price_permissions_migration_is_tracked_and_reversible(tmp_path: Path):
    database = tmp_path / "permissions.db"
    upgraded = _alembic(database, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT code FROM permissions WHERE code LIKE 'price.%' ORDER BY code"
        ).fetchall() == [("price.manage",), ("price.view",)]
        assert connection.execute(
            "SELECT COUNT(*) FROM material_prices_permission_provisioning"
        ).fetchone()[0] == 2

    downgraded = _alembic(database, "downgrade", "a1c3e5f7b9d0")
    assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM permissions WHERE code LIKE 'price.%'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'material_prices_permission_provisioning'"
        ).fetchone() is None
