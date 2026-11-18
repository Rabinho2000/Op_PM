"""Inventário separado por proprietário da localização.

Revision ID: d4f6b8c0e2a3
Revises: c3e5a7b9d1f2
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4f6b8c0e2a3"
down_revision: str | Sequence[str] | None = "c3e5a7b9d1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_CENTRAL_INDEX = "uq_inventory_locations_one_active_central"
OWNER_CENTRAL_INDEX = "uq_inventory_locations_one_active_central_per_owner"


def upgrade() -> None:
    op.add_column(
        "inventory_locations",
        sa.Column("owner", sa.String(length=32), nullable=False, server_default="solcor"),
    )
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE inventory_locations SET owner = 'solcor' WHERE owner IS NULL"))
    op.drop_index(OLD_CENTRAL_INDEX, table_name="inventory_locations")
    op.create_index(
        OWNER_CENTRAL_INDEX,
        "inventory_locations",
        ["owner"],
        unique=True,
        sqlite_where=sa.text("location_type = 'central' AND is_active = 1"),
        postgresql_where=sa.text("location_type = 'central' AND is_active"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    active_central_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM inventory_locations "
            "WHERE location_type = 'central' AND is_active IS TRUE"
        )
    ).scalar_one()
    if active_central_count > 1:
        raise RuntimeError(
            "Cannot downgrade inventory ownership while multiple active central locations exist."
        )

    op.drop_index(OWNER_CENTRAL_INDEX, table_name="inventory_locations")
    with op.batch_alter_table("inventory_locations") as batch:
        batch.drop_column("owner")
    op.create_index(
        OLD_CENTRAL_INDEX,
        "inventory_locations",
        ["location_type"],
        unique=True,
        sqlite_where=sa.text("location_type = 'central' AND is_active = 1"),
        postgresql_where=sa.text("location_type = 'central' AND is_active"),
    )
