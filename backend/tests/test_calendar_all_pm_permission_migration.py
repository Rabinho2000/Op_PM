"""Provisioning checks for the Planning-only cross-PM read capability."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import uuid
from pathlib import Path

import app.db
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.security.catalog import PERMISSIONS, ROLE_PERMISSIONS, ROLE_PM, ROLES

PREVIOUS_HEAD = "f2a4b6c8d0e1"
THIS_REVISION = "f9c2a4e6b8d0"
PERMISSION = "calendar.view_all_pm"
PROVISIONING_TABLE = "calendar_pm_read_permission_provisioning"
BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATION_PATH = BACKEND_DIR / "alembic" / "versions" / "f9c2a4e6b8d0_planeamento_leitura_todos_pm.py"


def _invoke_upgrade_function(engine: sa.Engine) -> None:
    spec = importlib.util.spec_from_file_location("calendar_pm_read_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()


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
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _alembic_ok(database_path: Path, *arguments: str) -> None:
    result = _run_alembic(database_path, *arguments)
    assert result.returncode == 0, result.stdout + result.stderr


def _seed_previous_catalog(engine: sa.Engine) -> dict[str, uuid.UUID]:
    roles = sa.table(
        "roles",
        sa.column("id", app.db.GUID()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
    )
    permissions = sa.table(
        "permissions",
        sa.column("id", app.db.GUID()),
        sa.column("code", sa.String()),
        sa.column("description", sa.String()),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("id", app.db.GUID()),
        sa.column("role_id", app.db.GUID()),
        sa.column("permission_id", app.db.GUID()),
    )
    with engine.begin() as connection:
        role_ids: dict[str, uuid.UUID] = {}
        for code, name in ROLES.items():
            role_id = connection.execute(
                sa.select(roles.c.id).where(roles.c.code == code)
            ).scalar_one_or_none()
            if role_id is None:
                role_id = uuid.uuid4()
                connection.execute(
                    roles.insert().values(id=role_id, code=code, name=name, description="")
                )
            role_ids[code] = role_id

        permission_ids: dict[str, uuid.UUID] = {}
        for code, description in PERMISSIONS.items():
            if code == PERMISSION:
                continue
            permission_id = connection.execute(
                sa.select(permissions.c.id).where(permissions.c.code == code)
            ).scalar_one_or_none()
            if permission_id is None:
                permission_id = uuid.uuid4()
                connection.execute(
                    permissions.insert().values(
                        id=permission_id, code=code, description=description
                    )
                )
            permission_ids[code] = permission_id

        for role_code, codes in ROLE_PERMISSIONS.items():
            for code in codes:
                if code == PERMISSION:
                    continue
                existing = connection.execute(
                    sa.select(role_permissions.c.id).where(
                        role_permissions.c.role_id == role_ids[role_code],
                        role_permissions.c.permission_id == permission_ids[code],
                    )
                ).first()
                if existing is None:
                    connection.execute(
                        role_permissions.insert().values(
                            id=uuid.uuid4(),
                            role_id=role_ids[role_code],
                            permission_id=permission_ids[code],
                        )
                    )
        return role_ids


def _permission_grants(connection: sa.Connection) -> set[str]:
    return set(
        connection.execute(
            sa.text(
                "SELECT r.code FROM role_permissions rp "
                "JOIN permissions p ON p.id = rp.permission_id "
                "JOIN roles r ON r.id = rp.role_id WHERE p.code = :code"
            ),
            {"code": PERMISSION},
        ).scalars()
    )


def test_catalog_grants_cross_pm_calendar_read_only_to_project_managers():
    assert PERMISSIONS[PERMISSION]
    catalog_grants = {
        role_code
        for role_code, permissions in ROLE_PERMISSIONS.items()
        if PERMISSION in permissions
    }
    assert catalog_grants == {ROLE_PM}
    assert PERMISSION not in ROLE_PERMISSIONS["administrador"]


def test_migration_upgrade_downgrade_and_repeat_preserve_existing_grants(tmp_path: Path):
    database_path = tmp_path / "calendar-pm-read.db"
    _alembic_ok(database_path, "upgrade", PREVIOUS_HEAD)
    engine = sa.create_engine(f"sqlite:///{database_path}")
    role_ids = _seed_previous_catalog(engine)

    with engine.begin() as connection:
        before_permissions = connection.execute(sa.text("SELECT COUNT(*) FROM permissions")).scalar_one()
        before_grants = connection.execute(sa.text("SELECT COUNT(*) FROM role_permissions")).scalar_one()
        before_manage_grants = _permission_grants_for(connection, "calendar.manage")
        assert connection.execute(
            sa.text("SELECT COUNT(*) FROM permissions WHERE code = :code"), {"code": PERMISSION}
        ).scalar_one() == 0

    _invoke_upgrade_function(engine)
    _alembic_ok(database_path, "upgrade", THIS_REVISION)
    with engine.connect() as connection:
        permission_count = connection.execute(sa.text("SELECT COUNT(*) FROM permissions")).scalar_one()
        grant_count = connection.execute(sa.text("SELECT COUNT(*) FROM role_permissions")).scalar_one()
        catalog_grants = {
            role_code
            for role_code, permissions in ROLE_PERMISSIONS.items()
            if PERMISSION in permissions
        }
        assert permission_count == before_permissions + 1
        assert grant_count == before_grants + 1
        assert _permission_grants(connection) == catalog_grants == {ROLE_PM}
        assert _permission_grants_for(connection, "calendar.manage") == before_manage_grants
        assert connection.execute(
            sa.text(f"SELECT COUNT(*) FROM {PROVISIONING_TABLE}")
        ).scalar_one() == 2
        db_pm_role_id = connection.execute(
            sa.text("SELECT id FROM roles WHERE code = :code"), {"code": ROLE_PM}
        ).scalar_one()
        assert str(db_pm_role_id) == str(role_ids[ROLE_PM])

    _alembic_ok(database_path, "downgrade", PREVIOUS_HEAD)
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM permissions")).scalar_one() == before_permissions
        assert connection.execute(sa.text("SELECT COUNT(*) FROM role_permissions")).scalar_one() == before_grants
        assert _permission_grants(connection) == set()
        assert _permission_grants_for(connection, "calendar.manage") == before_manage_grants
        assert not sa.inspect(connection).has_table(PROVISIONING_TABLE)


def test_migration_preserves_preexisting_permission_and_pm_assignment(tmp_path: Path):
    database_path = tmp_path / "calendar-pm-read-existing.db"
    _alembic_ok(database_path, "upgrade", PREVIOUS_HEAD)
    engine = sa.create_engine(f"sqlite:///{database_path}")
    role_ids = _seed_previous_catalog(engine)
    existing_permission_id = uuid.uuid4()
    existing_grant_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO permissions (id, code, description) "
                "VALUES (:id, :code, :description)"
            ),
            {
                "id": str(existing_permission_id),
                "code": PERMISSION,
                "description": "Preexisting description",
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO role_permissions (id, role_id, permission_id) "
                "VALUES (:id, :role_id, :permission_id)"
            ),
            {
                "id": str(existing_grant_id),
                "role_id": str(role_ids[ROLE_PM]),
                "permission_id": str(existing_permission_id),
            },
        )

    _alembic_ok(database_path, "upgrade", THIS_REVISION)
    with engine.connect() as connection:
        assert _permission_grants(connection) == {ROLE_PM}
        assert connection.execute(
            sa.text("SELECT description FROM permissions WHERE code = :code"), {"code": PERMISSION}
        ).scalar_one() == "Preexisting description"
        assert connection.execute(
            sa.text(f"SELECT COUNT(*) FROM {PROVISIONING_TABLE}")
        ).scalar_one() == 0

    _alembic_ok(database_path, "downgrade", PREVIOUS_HEAD)
    with engine.connect() as connection:
        assert _permission_grants(connection) == {ROLE_PM}
        assert connection.execute(
            sa.text("SELECT id FROM permissions WHERE code = :code"), {"code": PERMISSION}
        ).scalar_one() == str(existing_permission_id)
        assert connection.execute(
            sa.text("SELECT id FROM role_permissions WHERE id = :id"), {"id": str(existing_grant_id)}
        ).scalar_one() == str(existing_grant_id)


def test_unexpected_existing_role_grant_fails_before_any_migration_writes(tmp_path: Path):
    database_path = tmp_path / "calendar-pm-read-conflict.db"
    _alembic_ok(database_path, "upgrade", PREVIOUS_HEAD)
    engine = sa.create_engine(f"sqlite:///{database_path}")
    role_ids = _seed_previous_catalog(engine)
    existing_permission_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO permissions (id, code, description) "
                "VALUES (:id, :code, :description)"
            ),
            {"id": str(existing_permission_id), "code": PERMISSION, "description": "Preexisting"},
        )
        for role_code in (ROLE_PM, "comercial"):
            connection.execute(
                sa.text(
                    "INSERT INTO role_permissions (id, role_id, permission_id) "
                    "VALUES (:id, :role_id, :permission_id)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "role_id": str(role_ids[role_code]),
                    "permission_id": str(existing_permission_id),
                },
            )

    with engine.connect() as connection:
        before_tables = set(sa.inspect(connection).get_table_names())
        before_permissions = connection.execute(
            sa.text("SELECT id, code, description FROM permissions ORDER BY code, id")
        ).all()
        before_grants = connection.execute(
            sa.text("SELECT id, role_id, permission_id FROM role_permissions ORDER BY id")
        ).all()
        before_revision = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()

    result = _run_alembic(database_path, "upgrade", THIS_REVISION)
    assert result.returncode != 0
    assert "Unexpected role grants" in result.stdout + result.stderr

    with engine.connect() as connection:
        assert set(sa.inspect(connection).get_table_names()) == before_tables
        assert connection.execute(
            sa.text("SELECT id, code, description FROM permissions ORDER BY code, id")
        ).all() == before_permissions
        assert connection.execute(
            sa.text("SELECT id, role_id, permission_id FROM role_permissions ORDER BY id")
        ).all() == before_grants
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == before_revision
        assert _permission_grants(connection) == {ROLE_PM, "comercial"}
        assert not sa.inspect(connection).has_table(PROVISIONING_TABLE)


def _permission_grants_for(connection: sa.Connection, code: str) -> set[str]:
    return set(
        connection.execute(
            sa.text(
                "SELECT r.code FROM role_permissions rp "
                "JOIN permissions p ON p.id = rp.permission_id "
                "JOIN roles r ON r.id = rp.role_id WHERE p.code = :code"
            ),
            {"code": code},
        ).scalars()
    )
