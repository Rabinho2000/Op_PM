from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import app.db
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATION_PATH = BACKEND_DIR / "alembic" / "versions" / "d3f5a7c9e1b2_pm_cross_project_read_status.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("pm_cross_project_status_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_preserves_preexisting_permission_and_pm_grant_on_downgrade():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    permissions = sa.Table(
        "permissions", metadata,
        sa.Column("id", app.db.GUID(), primary_key=True),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("description", sa.String(512), nullable=False),
    )
    roles = sa.Table(
        "roles", metadata,
        sa.Column("id", app.db.GUID(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
    )
    role_permissions = sa.Table(
        "role_permissions", metadata,
        sa.Column("id", app.db.GUID(), primary_key=True),
        sa.Column("role_id", app.db.GUID(), nullable=False),
        sa.Column("permission_id", app.db.GUID(), nullable=False),
    )
    metadata.create_all(engine)
    pm_role_id, permission_id, grant_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(roles.insert().values(id=pm_role_id, code="project_manager"))
        connection.execute(permissions.insert().values(id=permission_id, code="project.view_all_pm_status", description="pre-existing"))
        connection.execute(role_permissions.insert().values(id=grant_id, role_id=pm_role_id, permission_id=permission_id))
    migration = _load_migration()
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    with engine.connect() as connection:
        assert connection.execute(sa.select(permissions.c.id)).all() == [(permission_id,)]
        assert connection.execute(sa.select(role_permissions.c.id)).all() == [(grant_id,)]
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    with engine.connect() as connection:
        assert connection.execute(sa.select(permissions.c.id)).all() == [(permission_id,)]
        assert connection.execute(sa.select(role_permissions.c.id)).all() == [(grant_id,)]
    engine.dispose()


def test_migration_refuses_preexisting_grant_to_unexpected_role_before_provisioning():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    permissions = sa.Table("permissions", metadata, sa.Column("id", app.db.GUID(), primary_key=True), sa.Column("code", sa.String(128)), sa.Column("description", sa.String(512)))
    roles = sa.Table("roles", metadata, sa.Column("id", app.db.GUID(), primary_key=True), sa.Column("code", sa.String(64)))
    role_permissions = sa.Table("role_permissions", metadata, sa.Column("id", app.db.GUID(), primary_key=True), sa.Column("role_id", app.db.GUID()), sa.Column("permission_id", app.db.GUID()))
    metadata.create_all(engine)
    perm_id, role_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(permissions.insert().values(id=perm_id, code="project.view_all_pm_status", description="collision"))
        connection.execute(roles.insert().values(id=role_id, code="financeiro"))
        connection.execute(role_permissions.insert().values(id=uuid.uuid4(), role_id=role_id, permission_id=perm_id))
    migration = _load_migration()
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            try:
                migration.upgrade()
            except RuntimeError as exc:
                assert "Unexpected role grants" in str(exc)
            else:
                raise AssertionError("migration accepted cross-role permission collision")
    with engine.connect() as connection:
        assert not sa.inspect(engine).has_table("pm_cross_project_status_provisioning")
        assert connection.execute(sa.select(permissions.c.id)).all() == [(perm_id,)]
    engine.dispose()


def test_migration_grants_new_permission_only_to_project_managers_and_rolls_back_its_rows():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    permissions = sa.Table(
        "permissions", metadata,
        sa.Column("id", app.db.GUID(), primary_key=True),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("description", sa.String(512), nullable=False),
    )
    roles = sa.Table(
        "roles", metadata,
        sa.Column("id", app.db.GUID(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
    )
    role_permissions = sa.Table(
        "role_permissions", metadata,
        sa.Column("id", app.db.GUID(), primary_key=True),
        sa.Column("role_id", app.db.GUID(), nullable=False),
        sa.Column("permission_id", app.db.GUID(), nullable=False),
    )
    metadata.create_all(engine)
    role_ids = {code: uuid.uuid4() for code in ("project_manager", "financeiro", "administrador")}
    with engine.begin() as connection:
        connection.execute(roles.insert(), [{"id": role_id, "code": code} for code, role_id in role_ids.items()])

    migration = _load_migration()
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    with engine.connect() as connection:
        permission_id, = connection.execute(
            sa.select(permissions.c.id).where(permissions.c.code == "project.view_all_pm_status")
        ).one()
        granted_role_codes = set(connection.execute(
            sa.select(roles.c.code)
            .select_from(role_permissions.join(roles, role_permissions.c.role_id == roles.c.id))
            .where(role_permissions.c.permission_id == permission_id)
        ).scalars())
    assert granted_role_codes == {"project_manager"}

    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    with engine.connect() as connection:
        assert connection.execute(sa.select(permissions.c.id).where(permissions.c.code == "project.view_all_pm_status")).first() is None
        assert connection.execute(sa.select(role_permissions.c.id)).first() is None
    engine.dispose()
