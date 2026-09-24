"""data de entrada do projeto no programa (ordenação cronológica da lista)

Revision ID: b4d8f2a6c1e3
Revises: a9c3e7f1b5d2
Create Date: 2026-09-26 10:00:00.000000

"""
import datetime as dt
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.db  # tipo de coluna portável app.db.GUID()


# revision identifiers, used by Alembic.
revision: str = 'b4d8f2a6c1e3'
down_revision: Union[str, Sequence[str], None] = 'a9c3e7f1b5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Acrescenta `entered_at` e preenche os projetos existentes.

    Os projetos existentes vieram do legado: entram com a data de início (a do
    ClickUp) e, sem ela, com a data de criação do registo. Novos projetos usam o
    default do ORM (momento da criação).
    """
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('entered_at', sa.DateTime(timezone=True), nullable=True))

    projects = sa.table(
        'projects',
        sa.column('id', app.db.GUID()),
        sa.column('start_date', sa.Date()),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('entered_at', sa.DateTime(timezone=True)),
    )
    conn = op.get_bind()
    for row in conn.execute(sa.select(projects.c.id, projects.c.start_date, projects.c.created_at)).all():
        value = (
            dt.datetime.combine(row.start_date, dt.time.min, tzinfo=dt.timezone.utc)
            if row.start_date is not None
            else row.created_at
        )
        conn.execute(projects.update().where(projects.c.id == row.id).values(entered_at=value))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('entered_at')
