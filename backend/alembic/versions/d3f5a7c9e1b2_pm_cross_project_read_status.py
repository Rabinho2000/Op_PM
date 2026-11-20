"""Grant PMs cross-project operational reading and lifecycle status changes.

Revision ID: d3f5a7c9e1b2
Revises: d2f4a6c8e0b1
"""
from __future__ import annotations

import uuid

import app.db
import sqlalchemy as sa
from alembic import op

revision = "d3f5a7c9e1b2"
down_revision = "d2f4a6c8e0b1"
branch_labels = None
depends_on = None

_PERMISSION = "project.view_all_pm_status"
_DESCRIPTION = "Consultar todos os projetos e alterar o respetivo estado (Project Manager)"
_ROLE = "project_manager"
_TRACKING = "pm_cross_project_status_provisioning"


def _tables():
    permissions = sa.table("permissions", sa.column("id", app.db.GUID()), sa.column("code", sa.String(128)), sa.column("description", sa.String(512)))
    roles = sa.table("roles", sa.column("id", app.db.GUID()), sa.column("code", sa.String(64)))
    role_permissions = sa.table("role_permissions", sa.column("id", app.db.GUID()), sa.column("role_id", app.db.GUID()), sa.column("permission_id", app.db.GUID()))
    tracking = sa.table(_TRACKING, sa.column("id", app.db.GUID()), sa.column("kind", sa.String(32)), sa.column("owned_row_id", app.db.GUID()), sa.column("permission_id", app.db.GUID()))
    return permissions, roles, role_permissions, tracking


def upgrade() -> None:
    bind = op.get_bind()
    permissions, roles, role_permissions, tracking = _tables()
    existing = bind.execute(sa.select(permissions.c.id).where(permissions.c.code == _PERMISSION)).scalars().all()
    if len(existing) > 1:
        raise RuntimeError(f"Multiple permission rows exist for {_PERMISSION!r}; refusing migration.")
    permission_id = existing[0] if existing else None
    if permission_id is not None:
        assigned_roles = bind.execute(
            sa.select(roles.c.code)
            .select_from(role_permissions.outerjoin(roles, role_permissions.c.role_id == roles.c.id))
            .where(role_permissions.c.permission_id == permission_id)
        ).scalars().all()
        unexpected = sorted({code or "<unknown role>" for code in assigned_roles if code != _ROLE})
        if unexpected:
            raise RuntimeError(
                f"Unexpected role grants for {_PERMISSION!r}: {', '.join(unexpected)}; refusing migration."
            )
    permission_id = existing[0] if existing else uuid.uuid4()
    op.create_table(
        _TRACKING,
        sa.Column("id", app.db.GUID(), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("owned_row_id", app.db.GUID(), nullable=False),
        sa.Column("permission_id", app.db.GUID(), nullable=False),
    )
    if not existing:
        bind.execute(permissions.insert().values(id=permission_id, code=_PERMISSION, description=_DESCRIPTION))
        bind.execute(tracking.insert().values(id=uuid.uuid4(), kind="permission", owned_row_id=permission_id, permission_id=permission_id))
    role_id = bind.execute(sa.select(roles.c.id).where(roles.c.code == _ROLE)).scalar_one_or_none()
    if role_id is None:
        return
    assignments = bind.execute(sa.select(role_permissions.c.id).where(role_permissions.c.role_id == role_id, role_permissions.c.permission_id == permission_id)).scalars().all()
    if len(assignments) > 1:
        raise RuntimeError(f"Duplicate grant for {_PERMISSION!r} and {_ROLE!r}; refusing migration.")
    if not assignments:
        assignment_id = uuid.uuid4()
        bind.execute(role_permissions.insert().values(id=assignment_id, role_id=role_id, permission_id=permission_id))
        bind.execute(tracking.insert().values(id=uuid.uuid4(), kind="role_permission", owned_row_id=assignment_id, permission_id=permission_id))


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TRACKING):
        return
    permissions, _roles, role_permissions, tracking = _tables()
    owned = bind.execute(sa.select(tracking.c.kind, tracking.c.owned_row_id, tracking.c.permission_id)).all()
    created_permissions = set()
    for kind, row_id, permission_id in owned:
        if kind == "role_permission":
            bind.execute(role_permissions.delete().where(role_permissions.c.id == row_id))
        elif kind == "permission":
            created_permissions.add(permission_id)
    for permission_id in created_permissions:
        used = bind.execute(sa.select(role_permissions.c.id).where(role_permissions.c.permission_id == permission_id).limit(1)).first()
        if used is None:
            bind.execute(permissions.delete().where(permissions.c.id == permission_id))
    op.drop_table(_TRACKING)
