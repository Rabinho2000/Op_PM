"""Provision the cable-tool cost/catalog capability.

Revision ID: d7a9c1e3f5b6
Revises: c6f8b0d2e4a5
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "d7a9c1e3f5b6"
down_revision: str | Sequence[str] | None = "c6f8b0d2e4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVISIONING_TABLE = "cable_tool_costs_provisioning"
_PERMISSION_CODE = "cable_design.view_costs"
_PERMISSION_DESCRIPTION = "Abrir a ferramenta de dimensionamento (inclui preços e catálogos comerciais)"
_NAMED_ROLE_CODES = {"administrador", "chefe_operacoes", "project_manager"}


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


def _ensure_permission(bind, permissions, provisioning):
    row = bind.execute(
        sa.select(permissions.c.id).where(permissions.c.code == _PERMISSION_CODE)
    ).first()
    if row is not None:
        return row[0]

    permission_id = uuid.uuid4()
    bind.execute(
        permissions.insert().values(
            id=permission_id,
            code=_PERMISSION_CODE,
            description=_PERMISSION_DESCRIPTION,
        )
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
    return permission_id


def _ensure_role_permission(
    bind,
    role_permissions,
    provisioning,
    *,
    role_id,
    permission_id,
) -> None:
    existing = bind.execute(
        sa.select(role_permissions.c.id).where(
            role_permissions.c.role_id == role_id,
            role_permissions.c.permission_id == permission_id,
        )
    ).first()
    if existing is not None:
        return

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


def upgrade() -> None:
    op.create_table(
        _PROVISIONING_TABLE,
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("owned_row_id", app.db.GUID(), nullable=False),
        sa.Column("permission_id", app.db.GUID(), nullable=False),
        sa.Column("role_id", app.db.GUID(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not all(
        inspector.has_table(table_name)
        for table_name in ("permissions", "roles", "role_permissions")
    ):
        return

    permissions, roles, role_permissions, provisioning = _tables()
    permission_id = _ensure_permission(bind, permissions, provisioning)

    role_rows = bind.execute(sa.select(roles.c.id, roles.c.code)).all()
    role_ids = {
        role_id for role_id, role_code in role_rows if role_code in _NAMED_ROLE_CODES
    }
    edit_permission = bind.execute(
        sa.select(permissions.c.id).where(permissions.c.code == "cable_design.edit")
    ).first()
    if edit_permission is not None:
        role_ids.update(
            role_id
            for (role_id,) in bind.execute(
                sa.select(role_permissions.c.role_id).where(
                    role_permissions.c.permission_id == edit_permission[0]
                )
            ).all()
        )

    for role_id in role_ids:
        _ensure_role_permission(
            bind,
            role_permissions,
            provisioning,
            role_id=role_id,
            permission_id=permission_id,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_PROVISIONING_TABLE):
        return

    _permissions_table, _roles_table, role_permissions, provisioning = _tables()
    owned = bind.execute(
        sa.select(
            provisioning.c.kind,
            provisioning.c.owned_row_id,
            provisioning.c.permission_id,
        )
    ).all()
    created_permission_ids: set[object] = set()
    for kind, owned_row_id, permission_id in owned:
        if kind == "role_permission":
            bind.execute(
                role_permissions.delete().where(role_permissions.c.id == owned_row_id)
            )
        elif kind == "permission":
            created_permission_ids.add(permission_id)

    permissions = sa.table("permissions", sa.column("id", app.db.GUID()))
    role_permission_usage = sa.table(
        "role_permissions",
        sa.column("id", app.db.GUID()),
        sa.column("permission_id", app.db.GUID()),
    )
    for permission_id in created_permission_ids:
        still_used = bind.execute(
            sa.select(role_permission_usage.c.id)
            .where(role_permission_usage.c.permission_id == permission_id)
            .limit(1)
        ).first()
        if still_used is None:
            bind.execute(permissions.delete().where(permissions.c.id == permission_id))

    op.drop_table(_PROVISIONING_TABLE)
