"""Grant read-only cross-PM access to Planning calendars.

Revision ID: f9c2a4e6b8d0
Revises: f2a4b6c8d0e1

Only ``project_manager`` receives the calendar-specific permission. It does
not grant project or Process visibility, or any calendar mutation right.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "f9c2a4e6b8d0"
down_revision: str | Sequence[str] | None = "f2a4b6c8d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVISIONING_TABLE = "calendar_pm_read_permission_provisioning"
_PERMISSION = "calendar.view_all_pm"
_DESCRIPTION = "Ver todos os eventos de planeamento, sem acesso aos restantes dados dos projetos"
_GRANTED_ROLE = "project_manager"


def _tables():
    permissions = sa.table(
        "permissions",
        sa.column("id", app.db.GUID()),
        sa.column("code", sa.String(length=128)),
        sa.column("description", sa.String(length=512)),
    )
    roles = sa.table(
        "roles",
        sa.column("id", app.db.GUID()),
        sa.column("code", sa.String(length=64)),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("id", app.db.GUID()),
        sa.column("role_id", app.db.GUID()),
        sa.column("permission_id", app.db.GUID()),
    )
    provisioning = sa.table(
        _PROVISIONING_TABLE,
        sa.column("id", app.db.GUID()),
        sa.column("kind", sa.String(length=32)),
        sa.column("owned_row_id", app.db.GUID()),
        sa.column("permission_id", app.db.GUID()),
        sa.column("role_id", app.db.GUID()),
    )
    return permissions, roles, role_permissions, provisioning


def upgrade() -> None:
    bind = op.get_bind()
    permissions, roles, role_permissions, provisioning = _tables()
    existing_permission_ids = bind.execute(
        sa.select(permissions.c.id).where(permissions.c.code == _PERMISSION)
    ).scalars().all()
    if len(existing_permission_ids) > 1:
        raise RuntimeError(f"Multiple permission rows exist for {_PERMISSION!r}; refusing migration.")

    permission_id = existing_permission_ids[0] if existing_permission_ids else None
    if permission_id is not None:
        assigned_roles = bind.execute(
            sa.select(roles.c.code)
            .select_from(role_permissions.outerjoin(roles, role_permissions.c.role_id == roles.c.id))
            .where(role_permissions.c.permission_id == permission_id)
        ).scalars().all()
        conflicting_roles = sorted({code or "<unknown role>" for code in assigned_roles if code != _GRANTED_ROLE})
        if conflicting_roles:
            raise RuntimeError(
                f"Unexpected role grants for {_PERMISSION!r}: {', '.join(conflicting_roles)}; "
                "refusing migration before any writes."
            )

    if not sa.inspect(bind).has_table(_PROVISIONING_TABLE):
        op.create_table(
            _PROVISIONING_TABLE,
            sa.Column("id", app.db.GUID(), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("owned_row_id", app.db.GUID(), nullable=False),
            sa.Column("permission_id", app.db.GUID(), nullable=False),
            sa.Column("role_id", app.db.GUID(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    if permission_id is None:
        permission_id = uuid.uuid4()
        bind.execute(
            permissions.insert().values(id=permission_id, code=_PERMISSION, description=_DESCRIPTION)
        )
        bind.execute(
            provisioning.insert().values(
                id=uuid.uuid4(),
                kind="permission",
                owned_row_id=permission_id,
                permission_id=permission_id,
                role_id=None,
            )
        )
    role_id = bind.execute(sa.select(roles.c.id).where(roles.c.code == _GRANTED_ROLE)).scalar_one_or_none()
    if role_id is None:
        return
    existing = bind.execute(
        sa.select(role_permissions.c.id).where(
            role_permissions.c.role_id == role_id,
            role_permissions.c.permission_id == permission_id,
        )
    ).first()
    if existing is None:
        assignment_id = uuid.uuid4()
        bind.execute(
            role_permissions.insert().values(
                id=assignment_id,
                role_id=role_id,
                permission_id=permission_id,
            )
        )
        bind.execute(
            provisioning.insert().values(
                id=uuid.uuid4(),
                kind="role_permission",
                owned_row_id=assignment_id,
                permission_id=permission_id,
                role_id=role_id,
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_PROVISIONING_TABLE):
        return

    permissions, _roles, role_permissions, provisioning = _tables()
    owned = bind.execute(
        sa.select(
            provisioning.c.kind,
            provisioning.c.owned_row_id,
            provisioning.c.permission_id,
        )
    ).all()
    created_permission_ids = set()
    for kind, owned_row_id, permission_id in owned:
        if kind == "role_permission":
            bind.execute(role_permissions.delete().where(role_permissions.c.id == owned_row_id))
        elif kind == "permission":
            created_permission_ids.add(permission_id)

    for permission_id in created_permission_ids:
        still_used = bind.execute(
            sa.select(role_permissions.c.id)
            .where(role_permissions.c.permission_id == permission_id)
            .limit(1)
        ).first()
        if still_used is None:
            bind.execute(permissions.delete().where(permissions.c.id == permission_id))

    op.drop_table(_PROVISIONING_TABLE)
