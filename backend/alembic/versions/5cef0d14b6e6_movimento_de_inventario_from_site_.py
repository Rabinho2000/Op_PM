"""movimento de inventario: from_site_quantity

Revision ID: 5cef0d14b6e6
Revises: 25103ca9bfeb
Create Date: 2026-09-23 22:35:31.537938

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5cef0d14b6e6'
down_revision: Union[str, Sequence[str], None] = '25103ca9bfeb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Coluna nova, nullable e sem default: os movimentos existentes ficam com
    NULL (tratado como 0 — "nada abatido ao material no local"), por isso não
    há backfill nem risco para dados existentes (D-064).
    """
    with op.batch_alter_table('inventory_movements', schema=None) as batch_op:
        batch_op.add_column(sa.Column('from_site_quantity', sa.Numeric(precision=14, scale=3), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('inventory_movements', schema=None) as batch_op:
        batch_op.drop_column('from_site_quantity')
