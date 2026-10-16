"""inventário: anulação auditável de movimentos de projetos

Revision ID: d4e6f8a1b2c3
Revises: e8b2c4d6f0a1
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "d4e6f8a1b2c3"
down_revision: str | Sequence[str] | None = "e8b2c4d6f0a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVISIONING_TABLE = "inventory_reverse_movement_provisioning"
_PERMISSION = "inventory.reverse_project"
_DESCRIPTION = "Anular movimentos de inventário de um projeto (mantendo o histórico)"


def upgrade() -> None:
    with op.batch_alter_table("inventory_movements", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reversal_of_movement_id", app.db.GUID(), nullable=True))
        batch_op.create_foreign_key(
            "fk_inventory_movement_reversal_of",
            "inventory_movements",
            ["reversal_of_movement_id"],
            ["id"],
        )
        batch_op.create_unique_constraint("uq_inventory_movement_one_reversal", ["reversal_of_movement_id"])

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
    permissions = sa.table(
        "permissions",
        sa.column("id", app.db.GUID()),
        sa.column("code", sa.String(length=128)),
        sa.column("description", sa.String(length=512)),
    )
    roles = sa.table("roles", sa.column("id", app.db.GUID()), sa.column("code", sa.String(length=64)))
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

    permission_row = bind.execute(sa.select(permissions.c.id).where(permissions.c.code == _PERMISSION)).first()
    if permission_row is None:
        permission_id = uuid.uuid4()
        bind.execute(permissions.insert().values(id=permission_id, code=_PERMISSION, description=_DESCRIPTION))
        bind.execute(
            provisioning.insert().values(
                id=uuid.uuid4(), kind="permission", owned_row_id=permission_id, permission_id=permission_id, role_id=None
            )
        )
    else:
        permission_id = permission_row[0]

    for role_code in ("administrador", "admin", "chefe_operacoes", "project_manager"):
        role_row = bind.execute(sa.select(roles.c.id).where(roles.c.code == role_code)).first()
        if role_row is None:
            continue
        role_id = role_row[0]
        assignment = bind.execute(
            sa.select(role_permissions.c.id).where(
                role_permissions.c.role_id == role_id,
                role_permissions.c.permission_id == permission_id,
            )
        ).first()
        if assignment is not None:
            continue
        assignment_id = uuid.uuid4()
        bind.execute(role_permissions.insert().values(id=assignment_id, role_id=role_id, permission_id=permission_id))
        bind.execute(
            provisioning.insert().values(
                id=uuid.uuid4(), kind="role_permission", owned_row_id=assignment_id, permission_id=permission_id, role_id=role_id
            )
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
    owned = bind.execute(sa.select(provisioning.c.kind, provisioning.c.owned_row_id, provisioning.c.permission_id)).all()
    permission_ids: set[uuid.UUID] = set()
    for kind, owned_row_id, permission_id in owned:
        if kind == "role_permission":
            bind.execute(role_permissions.delete().where(role_permissions.c.id == owned_row_id))
        elif kind == "permission":
            permission_ids.add(permission_id)
    for permission_id in permission_ids:
        still_used = bind.execute(
            sa.text("SELECT 1 FROM role_permissions WHERE permission_id = :permission_id LIMIT 1"),
            {"permission_id": str(permission_id)},
        ).first()
        if still_used is None:
            bind.execute(permissions.delete().where(permissions.c.id == permission_id))
    op.drop_table(_PROVISIONING_TABLE)
    with op.batch_alter_table("inventory_movements", schema=None) as batch_op:
        batch_op.drop_constraint("uq_inventory_movement_one_reversal", type_="unique")
        batch_op.drop_constraint("fk_inventory_movement_reversal_of", type_="foreignkey")
        batch_op.drop_column("reversal_of_movement_id")
