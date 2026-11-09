from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import uuid
from pathlib import Path

import app.db
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.security.catalog import PERMISSIONS, ROLE_PERMISSIONS, ROLES

PREVIOUS_HEAD = "f9c2a4e6b8d0"
THIS_REVISION = "a6c8e0f2d4b1"
PAYMENT_PERMISSION_ROLES = {
    "payment.view": {"administrador", "chefe_operacoes", "financeiro", "project_manager"},
    "payment.edit": {"administrador", "financeiro"},
}
BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATION_PATH = BACKEND_DIR / "alembic" / "versions" / "a6c8e0f2d4b1_marcos_pagamento_projeto.py"


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


def _invoke_upgrade_function(engine: sa.Engine) -> None:
    spec = importlib.util.spec_from_file_location("project_payment_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()


def _seed_previous_catalog(engine: sa.Engine) -> dict[str, uuid.UUID]:
    roles = sa.table(
        "roles",
        sa.column("id", app.db.GUID()),
        sa.column("code", sa.String(length=64)),
        sa.column("name", sa.String(length=128)),
        sa.column("description", sa.String(length=512)),
    )
    permissions = sa.table(
        "permissions",
        sa.column("id", app.db.GUID()),
        sa.column("code", sa.String(length=128)),
        sa.column("description", sa.String(length=512)),
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
            role_id = connection.execute(sa.select(roles.c.id).where(roles.c.code == code)).scalar_one_or_none()
            if role_id is None:
                role_id = uuid.uuid4()
                connection.execute(roles.insert().values(id=role_id, code=code, name=name, description=""))
            role_ids[code] = role_id

        permission_ids: dict[str, uuid.UUID] = {}
        for code, description in PERMISSIONS.items():
            if code in PAYMENT_PERMISSION_ROLES:
                continue
            permission_id = connection.execute(
                sa.select(permissions.c.id).where(permissions.c.code == code)
            ).scalar_one_or_none()
            if permission_id is None:
                permission_id = uuid.uuid4()
                connection.execute(
                    permissions.insert().values(id=permission_id, code=code, description=description)
                )
            permission_ids[code] = permission_id

        for role_code, permission_codes in ROLE_PERMISSIONS.items():
            for code in permission_codes:
                if code in PAYMENT_PERMISSION_ROLES:
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


def _permission_grants(connection: sa.Connection, code: str) -> set[str]:
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


def test_empty_database_upgrade_downgrade_upgrade_is_noop_without_roles(tmp_path: Path):
    database_path = tmp_path / "payment-milestones-empty.db"
    _alembic_ok(database_path, "upgrade", PREVIOUS_HEAD)
    engine = sa.create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM role_permissions"))
        connection.execute(sa.text("DELETE FROM user_roles"))
        connection.execute(sa.text("DELETE FROM permissions"))
        connection.execute(sa.text("DELETE FROM roles"))

    _alembic_ok(database_path, "upgrade", THIS_REVISION)
    with engine.connect() as connection:
        assert sa.inspect(connection).has_table("project_payment_milestones")
        assert connection.execute(sa.text("SELECT COUNT(*) FROM roles")).scalar_one() == 0
        assert connection.execute(
            sa.text("SELECT COUNT(*) FROM permissions WHERE code IN ('payment.view', 'payment.edit')")
        ).scalar_one() == 0
        assert connection.execute(
            sa.text(f"SELECT COUNT(*) FROM { 'project_payment_permission_provisioning' }")
        ).scalar_one() == 0

    _alembic_ok(database_path, "downgrade", PREVIOUS_HEAD)
    with engine.connect() as connection:
        assert not sa.inspect(connection).has_table("project_payment_milestones")
        assert not sa.inspect(connection).has_table("project_payment_permission_provisioning")
        assert connection.execute(sa.text("SELECT COUNT(*) FROM roles")).scalar_one() == 0

    _alembic_ok(database_path, "upgrade", THIS_REVISION)
    with engine.connect() as connection:
        assert sa.inspect(connection).has_table("project_payment_milestones")
        assert connection.execute(
            sa.text("SELECT COUNT(*) FROM permissions WHERE code IN ('payment.view', 'payment.edit')")
        ).scalar_one() == 0


def test_existing_database_upgrade_downgrade_upgrade_preserves_data_and_catalog_parity(tmp_path: Path):
    database_path = tmp_path / "payment-milestones-existing.db"
    _alembic_ok(database_path, "upgrade", PREVIOUS_HEAD)
    engine = sa.create_engine(f"sqlite:///{database_path}")
    _seed_previous_catalog(engine)
    project_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO projects (id, name, is_active, notes, work_dates_estimated) "
                "VALUES (:id, :name, :active, :notes, :estimated)"
            ),
            {
                "id": str(project_id),
                "name": "Projeto sintético existente",
                "active": True,
                "notes": "",
                "estimated": False,
            },
        )
        old_permission_count = connection.execute(sa.text("SELECT COUNT(*) FROM permissions")).scalar_one()
        old_grant_count = connection.execute(sa.text("SELECT COUNT(*) FROM role_permissions")).scalar_one()

    _alembic_ok(database_path, "upgrade", THIS_REVISION)
    _invoke_upgrade_function(engine)
    with engine.connect() as connection:
        for code, expected_roles in PAYMENT_PERMISSION_ROLES.items():
            catalog_roles = {
                role_code for role_code, codes in ROLE_PERMISSIONS.items() if code in codes
            }
            assert catalog_roles == expected_roles
            assert _permission_grants(connection, code) == catalog_roles
        assert connection.execute(sa.text("SELECT name FROM projects WHERE id = :id"), {"id": str(project_id)}).scalar_one() == "Projeto sintético existente"
        assert connection.execute(
            sa.text("SELECT COUNT(*) FROM project_payment_permission_provisioning")
        ).scalar_one() == 8
        assert connection.execute(sa.text("SELECT COUNT(*) FROM permissions")).scalar_one() == old_permission_count + 2
        assert connection.execute(sa.text("SELECT COUNT(*) FROM role_permissions")).scalar_one() == old_grant_count + 6

    _alembic_ok(database_path, "downgrade", PREVIOUS_HEAD)
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT name FROM projects WHERE id = :id"), {"id": str(project_id)}).scalar_one() == "Projeto sintético existente"
        assert connection.execute(sa.text("SELECT COUNT(*) FROM permissions")).scalar_one() == old_permission_count
        assert connection.execute(sa.text("SELECT COUNT(*) FROM role_permissions")).scalar_one() == old_grant_count
        assert not sa.inspect(connection).has_table("project_payment_milestones")

    _alembic_ok(database_path, "upgrade", THIS_REVISION)
    with engine.connect() as connection:
        for code, expected_roles in PAYMENT_PERMISSION_ROLES.items():
            assert _permission_grants(connection, code) == expected_roles
        assert connection.execute(sa.text("SELECT name FROM projects WHERE id = :id"), {"id": str(project_id)}).scalar_one() == "Projeto sintético existente"


def test_migration_preserves_preexisting_payment_permission_and_grant(tmp_path: Path):
    database_path = tmp_path / "payment-milestones-preexisting-permission.db"
    _alembic_ok(database_path, "upgrade", PREVIOUS_HEAD)
    engine = sa.create_engine(f"sqlite:///{database_path}")
    role_ids = _seed_previous_catalog(engine)
    existing_permission_id = uuid.uuid4()
    existing_grant_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            sa.text("INSERT INTO permissions (id, code, description) VALUES (:id, :code, :description)"),
            {"id": str(existing_permission_id), "code": "payment.view", "description": "Synthetic preexisting"},
        )
        connection.execute(
            sa.text("INSERT INTO role_permissions (id, role_id, permission_id) VALUES (:id, :role_id, :permission_id)"),
            {
                "id": str(existing_grant_id),
                "role_id": str(role_ids["project_manager"]),
                "permission_id": str(existing_permission_id),
            },
        )

    _alembic_ok(database_path, "upgrade", THIS_REVISION)
    with engine.connect() as connection:
        assert _permission_grants(connection, "payment.view") == PAYMENT_PERMISSION_ROLES["payment.view"]
        assert connection.execute(
            sa.text("SELECT COUNT(*) FROM project_payment_permission_provisioning WHERE kind = 'permission' AND permission_id = :id"),
            {"id": str(existing_permission_id)},
        ).scalar_one() == 0

    _alembic_ok(database_path, "downgrade", PREVIOUS_HEAD)
    with engine.connect() as connection:
        assert _permission_grants(connection, "payment.view") == {"project_manager"}
        assert connection.execute(
            sa.text("SELECT id FROM permissions WHERE code = 'payment.view'")
        ).scalar_one() == str(existing_permission_id)
        assert connection.execute(
            sa.text("SELECT id FROM role_permissions WHERE id = :id"), {"id": str(existing_grant_id)}
        ).scalar_one() == str(existing_grant_id)


def test_unexpected_existing_grant_fails_before_migration_writes(tmp_path: Path):
    database_path = tmp_path / "payment-milestones-conflicting-grant.db"
    _alembic_ok(database_path, "upgrade", PREVIOUS_HEAD)
    engine = sa.create_engine(f"sqlite:///{database_path}")
    role_ids = _seed_previous_catalog(engine)
    permission_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            sa.text("INSERT INTO permissions (id, code, description) VALUES (:id, 'payment.view', 'Synthetic conflict')"),
            {"id": str(permission_id)},
        )
        connection.execute(
            sa.text("INSERT INTO role_permissions (id, role_id, permission_id) VALUES (:id, :role_id, :permission_id)"),
            {
                "id": str(uuid.uuid4()),
                "role_id": str(role_ids["comercial"]),
                "permission_id": str(permission_id),
            },
        )

    with pytest.raises(RuntimeError, match="Unexpected role grants"):
        _invoke_upgrade_function(engine)
    with engine.connect() as connection:
        assert not sa.inspect(connection).has_table("project_payment_milestones")
        assert not sa.inspect(connection).has_table("project_payment_permission_provisioning")
        assert _permission_grants(connection, "payment.view") == {"comercial"}
