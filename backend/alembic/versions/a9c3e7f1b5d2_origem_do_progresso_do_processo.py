"""origem do progresso do processo (ui | legacy)

Revision ID: a9c3e7f1b5d2
Revises: e5b1c9d3a7f2
Create Date: 2026-09-25 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9c3e7f1b5d2'
down_revision: Union[str, Sequence[str], None] = 'e5b1c9d3a7f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ('project_subtask_progress', 'project_stage_progress')


def upgrade() -> None:
    """Upgrade schema.

    `source` distingue o progresso marcado na aplicação (`ui`) do importado do
    legado (`legacy`, sem data nem autor). Tudo o que já existe é `ui`. O default
    do servidor só serve as linhas existentes; o valor em runtime vem do ORM.
    """
    for table in TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('source', sa.String(length=16), nullable=False, server_default='ui'))
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.alter_column('source', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    for table in TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column('source')
