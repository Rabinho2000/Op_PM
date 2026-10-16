"""Alembic and capability provisioning checks for cable studies."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BASE_REVISION = "f3b5d7e9a1c2"


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


def test_cable_design_migration_round_trip_on_sqlite(tmp_path: Path):
    database_path = tmp_path / "cable-design-migration.db"
    upgraded = _run_alembic(database_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "cable_designs",
            "cable_design_revisions",
            "cable_design_history",
            "cable_design_permission_provisioning",
        } <= tables
        assert {
            row[1]
            for row in connection.execute("PRAGMA table_info(cable_designs)")
        } == {
            "id",
            "project_id",
            "title",
            "status",
            "current_revision",
            "version",
            "is_active",
            "created_by_person_id",
            "created_at",
            "updated_at",
        }
        assert {
            row[1]
            for row in connection.execute("PRAGMA table_info(cable_design_revisions)")
        } == {
            "id",
            "design_id",
            "rev",
            "input_json",
            "result_json",
            "engine_version",
            "content_sha256",
            "unresolved_circuits",
            "status",
            "approved_by_person_id",
            "approved_at",
            "created_by_person_id",
            "created_at",
            "updated_at",
        }

    downgraded = _run_alembic(database_path, "downgrade", BASE_REVISION)
    assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'cable_designs'"
        ).fetchone() is None
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'cable_design_permission_provisioning'"
        ).fetchone() is None

    upgraded_again = _run_alembic(database_path, "upgrade", "head")
    assert upgraded_again.returncode == 0, upgraded_again.stdout + upgraded_again.stderr


def test_cable_design_migration_tracks_only_new_role_grants(tmp_path: Path):
    database_path = tmp_path / "cable-design-permissions.db"
    before = _run_alembic(database_path, "upgrade", BASE_REVISION)
    assert before.returncode == 0, before.stdout + before.stderr

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
    seed_roles = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import uuid; "
                "from sqlalchemy import insert; "
                "from app.db import SessionLocal; "
                "from app.models.identity import Role, Permission; "
                "db=SessionLocal(); "
                "db.add(Permission(code='existing_permission', description='existing')); "
                "db.commit(); db.close()"
            ),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert seed_roles.returncode == 0, seed_roles.stdout + seed_roles.stderr

    upgraded = _run_alembic(database_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr

    with sqlite3.connect(database_path) as connection:
        grants = connection.execute(
            """
            SELECT r.code, p.code
            FROM role_permissions rp
            JOIN roles r ON r.id = rp.role_id
            JOIN permissions p ON p.id = rp.permission_id
            WHERE p.code LIKE 'cable_design.%'
            ORDER BY r.code, p.code
            """
        ).fetchall()
        assert grants == [("suporte_operacoes", "cable_design.view")]
        tracked = connection.execute(
            "SELECT COUNT(*) FROM cable_design_permission_provisioning"
        ).fetchone()[0]
        assert tracked == 3

    downgraded = _run_alembic(database_path, "downgrade", BASE_REVISION)
    assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id WHERE p.code LIKE 'cable_design.%'"
        ).fetchone()[0] == 0
        # The migration created these permissions, so it is safe to remove them;
        # the pre-existing project.view_all permission remains.
        assert connection.execute(
            "SELECT COUNT(*) FROM permissions WHERE code LIKE 'cable_design.%'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM permissions WHERE code = 'existing_permission'"
        ).fetchone()[0] == 1
