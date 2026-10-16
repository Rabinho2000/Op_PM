"""Provision private material-price capabilities with migration ownership tracking.

Revision ID: b2d4f6a8c0e1
Revises: a1c3e5f7b9d0
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "b2d4f6a8c0e1"
down_revision: str | Sequence[str] | None = "a1c3e5f7b9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVISIONING_TABLE = "material_prices_permission_provisioning"


def _provision_permission(bind, *, permissions, provisioning, code: str, description: str):
    row = bind.execute(sa.select(permissions.c.id).where(permissions.c.code == code)).first()
    if row is not None:
        return row[0]
    permission_id = uuid.uuid4()
    bind.execute(permissions.insert().values(id=permission_id, code=code, description=description))
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


def _provision_role_permission(
    bind, *, role_id, permission_id, role_permissions, provisioning
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
    # Only rows created by this migration are tracked, so downgrade never
    # removes a permission or assignment that existed before this revision.
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
    if not inspector.has_table("permissions") or not inspector.has_table("roles"):
        return

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

    view_permission_id = _provision_permission(
        bind,
        permissions=permissions,
        provisioning=provisioning,
        code="price.view",
        description="Ver preços de materiais",
    )
    manage_permission_id = _provision_permission(
        bind,
        permissions=permissions,
        provisioning=provisioning,
        code="price.manage",
        description="Carregar e importar preços de materiais",
    )

    role_grants = {
        "administrador": (view_permission_id, manage_permission_id),
        "chefe_operacoes": (view_permission_id,),
    }
    for role_code, permission_ids in role_grants.items():
        role_row = bind.execute(sa.select(roles.c.id).where(roles.c.code == role_code)).first()
        if role_row is None:
            continue
        for permission_id in permission_ids:
            _provision_role_permission(
                bind,
                role_id=role_row[0],
                permission_id=permission_id,
                role_permissions=role_permissions,
                provisioning=provisioning,
            )


def downgrade() -> None:
    bind = op.get_bind()
    provisioning = sa.table(
        _PROVISIONING_TABLE,
        sa.column("kind", sa.String(length=32)),
        sa.column("owned_row_id", app.db.GUID()),
        sa.column("permission_id", app.db.GUID()),
    )
    role_permissions = sa.table("role_permissions", sa.column("id", app.db.GUID()))
    permissions = sa.table("permissions", sa.column("id", app.db.GUID()))

    owned = bind.execute(
        sa.select(provisioning.c.kind, provisioning.c.owned_row_id, provisioning.c.permission_id)
    ).all()
    permission_ids: set[uuid.UUID] = set()
    for kind, owned_row_id, permission_id in owned:
        if kind == "role_permission":
            bind.execute(role_permissions.delete().where(role_permissions.c.id == owned_row_id))
        elif kind == "permission":
            permission_ids.add(permission_id)

    role_permission_usage = sa.table(
        "role_permissions",
        sa.column("permission_id", app.db.GUID()),
    )
    for permission_id in permission_ids:
        still_used = bind.execute(
            sa.select(role_permission_usage.c.permission_id)
            .where(role_permission_usage.c.permission_id == permission_id)
            .limit(1)
        ).first()
        if still_used is None:
            bind.execute(permissions.delete().where(permissions.c.id == permission_id))

    op.drop_table(_PROVISIONING_TABLE)
