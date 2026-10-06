"""contactos de fornecedores e ligação ao mapa

Revision ID: d7a2c5e9b3f1
Revises: a7c1e5d9f3b2
Create Date: 2026-09-28 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.db  # tipo de coluna portável app.db.GUID()


# revision identifiers, used by Alembic.
revision: str = 'd7a2c5e9b3f1'
down_revision: Union[str, Sequence[str], None] = 'a7c1e5d9f3b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'supplier_contacts',
        sa.Column('id', app.db.GUID(), nullable=False),
        sa.Column('supplier_id', app.db.GUID(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('department', sa.String(length=128), nullable=True),
        sa.Column('phone', sa.String(length=64), nullable=True),
        sa.Column('email', sa.String(length=320), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('supplier_contacts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_supplier_contacts_supplier_id'), ['supplier_id'], unique=False)
    with op.batch_alter_table('suppliers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('maps_url', sa.String(length=1024), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('suppliers', schema=None) as batch_op:
        batch_op.drop_column('maps_url')
    with op.batch_alter_table('supplier_contacts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_supplier_contacts_supplier_id'))
    op.drop_table('supplier_contacts')
