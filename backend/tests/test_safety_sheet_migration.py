from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

BASE_REVISION = "d4f6b8c0e2a3"
FEATURE_REVISION = "e5a7c9d1f3b4"


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


def test_safety_sheet_migration_upgrade_downgrade_upgrade_sqlite(tmp_path: Path):
    database_path = tmp_path / "safety-sheet.db"
    base = _run_alembic(database_path, "upgrade", BASE_REVISION)
    assert base.returncode == 0, base.stdout + base.stderr

    with sqlite3.connect(database_path) as connection:
        existing_roles = {
            row[0] for row in connection.execute("SELECT code FROM roles").fetchall()
        }
        for code in ("administrador", "chefe_operacoes", "project_manager", "suporte_operacoes"):
            if code not in existing_roles:
                connection.execute(
                    "INSERT INTO roles (id, code, name, description) VALUES (?, ?, ?, '')",
                    (str(uuid.uuid4()), code, code),
                )

    upgraded = _run_alembic(database_path, "upgrade", FEATURE_REVISION)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"project_safety_sheets", "project_safety_sheet_workers", "project_safety_sheet_history"} <= tables
        permission = connection.execute(
            "SELECT id FROM permissions WHERE code = 'project.safety_sheet.edit'"
        ).fetchone()
        assert permission is not None
        grants = connection.execute(
            """
            SELECT r.code FROM role_permissions rp
            JOIN roles r ON r.id = rp.role_id
            WHERE rp.permission_id = ? ORDER BY r.code
            """,
            permission,
        ).fetchall()
        assert [row[0] for row in grants] == [
            "administrador",
            "chefe_operacoes",
            "project_manager",
            "suporte_operacoes",
        ]

    downgraded = _run_alembic(database_path, "downgrade", BASE_REVISION)
    assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert not {
            "project_safety_sheets",
            "project_safety_sheet_workers",
            "project_safety_sheet_history",
            "project_safety_sheet_permission_provisioning",
        } & tables
        assert connection.execute(
            "SELECT COUNT(*) FROM permissions WHERE code = 'project.safety_sheet.edit'"
        ).fetchone()[0] == 0

    upgraded_again = _run_alembic(database_path, "upgrade", FEATURE_REVISION)
    assert upgraded_again.returncode == 0, upgraded_again.stdout + upgraded_again.stderr
