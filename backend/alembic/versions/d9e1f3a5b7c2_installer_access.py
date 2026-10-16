"""Scoped external installer collaborator access.

This revision provisions only catalog rows and the two membership/audit tables.
It never creates users, persons, user_roles, or real account links.
"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa

import app.db

revision: str = "d9e1f3a5b7c2"
down_revision: Union[str, Sequence[str], None] = "c8f0a2b4d6e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PROVISIONING_TABLE = "installer_access_provisioning"
_ROLE_CODE = "instalador_colaborador"
_ROLE_PERMISSIONS = (
    "project.view_assigned_installer",
    "task.view_assigned_installer",
    "works_calendar.view_assigned_installer",
    "installer_team.view_assigned_installer",
    "inventory.view_assigned_installer",
    "time_bank.view_own",
)
_PERMISSION_DESCRIPTIONS = {
    "project.view_assigned_installer": "Ver projetos atribuídos aos instaladores associados",
    "task.view_assigned_installer": "Ver tarefas básicas dos projetos dos instaladores associados",
    "works_calendar.view_assigned_installer": "Ver obras e calendário dos instaladores associados",
    "installer_team.view_assigned_installer": "Ver equipas dos instaladores associados",
    "inventory.view_assigned_installer": "Ver inventário por projeto dos instaladores associados",
    "time_bank.view_own": "Consultar os próprios lançamentos e saldo do Banco de Horas",
}


def _tables():
    permissions = sa.table("permissions", sa.column("id", app.db.GUID()), sa.column("code", sa.String()), sa.column("description", sa.String()))
    roles = sa.table("roles", sa.column("id", app.db.GUID()), sa.column("code", sa.String()), sa.column("name", sa.String()), sa.column("description", sa.String()))
    role_permissions = sa.table("role_permissions", sa.column("id", app.db.GUID()), sa.column("role_id", app.db.GUID()), sa.column("permission_id", app.db.GUID()))
    provisioning = sa.table(_PROVISIONING_TABLE, sa.column("id", app.db.GUID()), sa.column("kind", sa.String()), sa.column("owned_row_id", app.db.GUID()), sa.column("permission_id", app.db.GUID()), sa.column("role_id", app.db.GUID()))
    return permissions, roles, role_permissions, provisioning


def _ensure_permission(bind, permissions, provisioning, code):
    row = bind.execute(sa.select(permissions.c.id).where(permissions.c.code == code)).first()
    if row is not None:
        return row[0]
    permission_id = uuid.uuid4()
    bind.execute(permissions.insert().values(id=permission_id, code=code, description=_PERMISSION_DESCRIPTIONS[code]))
    bind.execute(provisioning.insert().values(id=uuid.uuid4(), kind="permission", owned_row_id=permission_id, permission_id=permission_id, role_id=None))
    return permission_id


def _ensure_role_permission(bind, role_permissions, provisioning, role_id, permission_id):
    existing = bind.execute(sa.select(role_permissions.c.id).where(role_permissions.c.role_id == role_id, role_permissions.c.permission_id == permission_id)).first()
    if existing is not None:
        return
    grant_id = uuid.uuid4()
    bind.execute(role_permissions.insert().values(id=grant_id, role_id=role_id, permission_id=permission_id))
    bind.execute(provisioning.insert().values(id=uuid.uuid4(), kind="role_permission", owned_row_id=grant_id, permission_id=permission_id, role_id=role_id))


def upgrade() -> None:
    op.create_table(
        "installer_access_memberships",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("person_id", app.db.GUID(), nullable=False),
        sa.Column("installer_id", app.db.GUID(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("granted_by_person_id", app.db.GUID(), nullable=True),
        sa.Column("revoked_by_person_id", app.db.GUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"]),
        sa.ForeignKeyConstraint(["installer_id"], ["installers.id"]),
        sa.ForeignKeyConstraint(["granted_by_person_id"], ["people.id"]),
        sa.ForeignKeyConstraint(["revoked_by_person_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("person_id", "installer_id", name="uq_installer_access_membership_pair"),
    )
    op.create_index("ix_installer_access_memberships_person_active", "installer_access_memberships", ["person_id", "is_active"])
    op.create_index("ix_installer_access_memberships_installer_active", "installer_access_memberships", ["installer_id", "is_active"])
    op.create_table(
        "installer_access_membership_history",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("membership_id", app.db.GUID(), nullable=False),
        sa.Column("person_id", app.db.GUID(), nullable=False),
        sa.Column("installer_id", app.db.GUID(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("old_is_active", sa.Boolean(), nullable=True),
        sa.Column("new_is_active", sa.Boolean(), nullable=False),
        sa.Column("changed_by_person_id", app.db.GUID(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["membership_id"], ["installer_access_memberships.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"]),
        sa.ForeignKeyConstraint(["installer_id"], ["installers.id"]),
        sa.ForeignKeyConstraint(["changed_by_person_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_installer_access_membership_history_pair", "installer_access_membership_history", ["person_id", "installer_id"])
    op.create_table(
        _PROVISIONING_TABLE,
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("owned_row_id", app.db.GUID(), nullable=False),
        sa.Column("permission_id", app.db.GUID(), nullable=True),
        sa.Column("role_id", app.db.GUID(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    bind = op.get_bind()
    permissions, roles, role_permissions, provisioning = _tables()
    row = bind.execute(sa.select(roles.c.id).where(roles.c.code == _ROLE_CODE)).first()
    if row is None:
        role_id = uuid.uuid4()
        bind.execute(roles.insert().values(id=role_id, code=_ROLE_CODE, name="Colaborador externo por instalador", description=""))
        bind.execute(provisioning.insert().values(id=uuid.uuid4(), kind="role", owned_row_id=role_id, permission_id=None, role_id=None))
    else:
        role_id = row[0]
    permission_ids = {code: _ensure_permission(bind, permissions, provisioning, code) for code in _ROLE_PERMISSIONS}
    for code in _ROLE_PERMISSIONS:
        _ensure_role_permission(bind, role_permissions, provisioning, role_id, permission_ids[code])


def downgrade() -> None:
    bind = op.get_bind()
    permissions, roles, role_permissions, provisioning = _tables()
    user_roles = sa.table("user_roles", sa.column("role_id", app.db.GUID()))
    owned = bind.execute(sa.select(provisioning.c.kind, provisioning.c.owned_row_id, provisioning.c.permission_id)).all()
    created_roles = set()
    created_permissions = set()
    for kind, owned_row_id, permission_id in owned:
        if kind == "role_permission":
            bind.execute(role_permissions.delete().where(role_permissions.c.id == owned_row_id))
        elif kind == "role":
            created_roles.add(owned_row_id)
        elif kind == "permission" and permission_id is not None:
            created_permissions.add(permission_id)
    for permission_id in created_permissions:
        if bind.execute(sa.select(role_permissions.c.id).where(role_permissions.c.permission_id == permission_id).limit(1)).first() is None:
            bind.execute(permissions.delete().where(permissions.c.id == permission_id))
    for role_id in created_roles:
        if bind.execute(sa.select(user_roles.c.role_id).where(user_roles.c.role_id == role_id).limit(1)).first() is None:
            bind.execute(roles.delete().where(roles.c.id == role_id))
    op.drop_table(_PROVISIONING_TABLE)
    op.drop_index("ix_installer_access_membership_history_pair", table_name="installer_access_membership_history")
    op.drop_table("installer_access_membership_history")
    op.drop_index("ix_installer_access_memberships_installer_active", table_name="installer_access_memberships")
    op.drop_index("ix_installer_access_memberships_person_active", table_name="installer_access_memberships")
    op.drop_table("installer_access_memberships")
