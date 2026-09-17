"""percurso de obra: responsável, nota e ponto de contacto por etapa (D-052)

Revision ID: 5c2d1e7a9b40
Revises: 207faad55b86
Create Date: 2026-09-16 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c2d1e7a9b40'
down_revision: Union[str, Sequence[str], None] = '207faad55b86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('workflow_stages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('responsible_label', sa.String(length=128), server_default='', nullable=False))
        batch_op.add_column(sa.Column('contact_type', sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column('contact_day', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('note', sa.Text(), server_default='', nullable=False))

    with op.batch_alter_table('workflow_subtasks', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('is_client_contact', sa.Boolean(), server_default=sa.false(), nullable=False)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('workflow_subtasks', schema=None) as batch_op:
        batch_op.drop_column('is_client_contact')

    with op.batch_alter_table('workflow_stages', schema=None) as batch_op:
        batch_op.drop_column('note')
        batch_op.drop_column('contact_day')
        batch_op.drop_column('contact_type')
        batch_op.drop_column('responsible_label')
