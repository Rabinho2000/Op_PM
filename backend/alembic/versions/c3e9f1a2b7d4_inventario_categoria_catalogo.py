"""inventario: categoria livre do catálogo (F1)

Revision ID: c3e9f1a2b7d4
Revises: 8a1d3f4c6b90
Create Date: 2026-10-02

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3e9f1a2b7d4"
down_revision: str | Sequence[str] | None = "8a1d3f4c6b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("inventory_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("category", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("inventory_items", schema=None) as batch_op:
        batch_op.drop_column("category")
