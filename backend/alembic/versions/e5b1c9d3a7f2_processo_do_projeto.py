"""processo do projeto: etapas com responsável por regra e delegações de suporte

Revision ID: e5b1c9d3a7f2
Revises: c8d2e4f6a1b7
Create Date: 2026-09-25 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.db  # necessário para o tipo de coluna portável app.db.GUID()


# revision identifiers, used by Alembic.
revision: str = 'e5b1c9d3a7f2'
down_revision: Union[str, Sequence[str], None] = 'c8d2e4f6a1b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    `workflow_stages` ganha o dia útil e o tipo do ponto de contacto, a nota da
    etapa e a regra de responsável (`responsible_rule`/`responsible_label`), e
    cria-se `support_delegations` (PM -> pessoa de suporte). Só colunas
    opcionais / uma tabela nova: o catálogo genérico existente continua válido.
    """
    with op.batch_alter_table('workflow_stages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('contact_day', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('contact_kind', sa.String(length=16), nullable=True))
        # server_default só para as linhas existentes; o valor em runtime vem do ORM.
        batch_op.add_column(sa.Column('note', sa.Text(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('responsible_rule', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('responsible_label', sa.String(length=128), nullable=True))
    with op.batch_alter_table('workflow_stages', schema=None) as batch_op:
        batch_op.alter_column('note', server_default=None)

    op.create_table(
        'support_delegations',
        sa.Column('pm_person_id', app.db.GUID(), nullable=False),
        sa.Column('support_person_id', app.db.GUID(), nullable=False),
        sa.Column('id', app.db.GUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['pm_person_id'], ['people.id']),
        sa.ForeignKeyConstraint(['support_person_id'], ['people.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pm_person_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('support_delegations')
    with op.batch_alter_table('workflow_stages', schema=None) as batch_op:
        batch_op.drop_column('responsible_label')
        batch_op.drop_column('responsible_rule')
        batch_op.drop_column('note')
        batch_op.drop_column('contact_kind')
        batch_op.drop_column('contact_day')
