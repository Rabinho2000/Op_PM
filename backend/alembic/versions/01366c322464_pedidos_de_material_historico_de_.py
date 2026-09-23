"""pedidos de material: historico de transicoes

Revision ID: 01366c322464
Revises: 5cef0d14b6e6
Create Date: 2026-09-23 23:30:10.768605

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.db  # necessário para o tipo de coluna portável app.db.GUID()


# revision identifiers, used by Alembic.
revision: str = '01366c322464'
down_revision: Union[str, Sequence[str], None] = '5cef0d14b6e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Cria uma tabela nova (auditoria append-only das transições de um pedido de
    material, D-067) e acrescenta `material_request_items.position` (ordem das
    linhas tal como introduzidas). A coluna nova entra com `server_default` só
    para as linhas existentes (se as houver) e o default é removido a seguir —
    mesmo padrão de f1134f80f657; o valor em runtime vem do ORM.
    """
    op.create_table(
        'material_request_history',
        sa.Column('request_id', app.db.GUID(), nullable=False),
        sa.Column('action', sa.String(length=32), nullable=False),
        sa.Column('from_status', sa.String(length=32), nullable=True),
        sa.Column('to_status', sa.String(length=32), nullable=False),
        sa.Column('changed_by_person_id', app.db.GUID(), nullable=True),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', app.db.GUID(), nullable=False),
        sa.ForeignKeyConstraint(['changed_by_person_id'], ['people.id']),
        sa.ForeignKeyConstraint(['request_id'], ['material_requests.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('material_request_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('position', sa.Integer(), nullable=False, server_default='0'))
    with op.batch_alter_table('material_request_items', schema=None) as batch_op:
        batch_op.alter_column('position', server_default=None)
        # Preço unitário com 4 casas (antes 2): material custa frações de cêntimo e
        # 2 casas arredondavam o preço em silêncio. A coluna ainda nunca teve dados.
        batch_op.alter_column(
            'unit_price',
            existing_type=sa.Numeric(precision=12, scale=2),
            type_=sa.Numeric(precision=14, scale=4),
            existing_nullable=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('material_request_items', schema=None) as batch_op:
        batch_op.alter_column(
            'unit_price',
            existing_type=sa.Numeric(precision=14, scale=4),
            type_=sa.Numeric(precision=12, scale=2),
            existing_nullable=True,
        )
        batch_op.drop_column('position')
    op.drop_table('material_request_history')
