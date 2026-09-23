"""task category

Revision ID: 25103ca9bfeb
Revises: f1134f80f657
Create Date: 2026-09-23 13:35:35.192728

Adiciona `Task.category` (workflow|field|material|documentation|
commercial|other — ver app/models/task.py) para separar workflow/
documentação de dívida operacional real (field/material), usada pelo mapa
operacional (`attention`). Mesmo padrão de migração segura já usado neste
repositório para uma coluna `NOT NULL` nova sobre uma tabela com linhas
existentes (ver f1134f80f657): `server_default` só para a adição, removido
a seguir — o valor por omissão em runtime fica sempre do lado do ORM.

Backfill: as 5 tarefas padrão (`Task.task_type` em
DEFAULT_TASK_TYPE_CATEGORIES) recebem a categoria correta; qualquer outra
tarefa existente (incluindo `custom`) fica em 'other' — nunca inventada.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '25103ca9bfeb'
down_revision: Union[str, Sequence[str], None] = 'f1134f80f657'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mesma correspondência de app/models/task.py:DEFAULT_TASK_TYPE_CATEGORIES —
# duplicada aqui, literal, para a migração nunca depender do código
# aplicacional em runtime (uma migração antiga tem de continuar a
# funcionar mesmo que o módulo mude no futuro).
_TASK_TYPE_CATEGORIES = {
    "visita_tecnica": "workflow",
    "preparacao_instalacao": "workflow",
    "instalacao": "workflow",
    "comissionamento": "workflow",
    "fotos_drive": "documentation",
}


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category', sa.String(length=32), nullable=False, server_default='other'))
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.alter_column('category', server_default=None)

    tasks = sa.table('tasks', sa.column('task_type', sa.String), sa.column('category', sa.String))
    for task_type, category in _TASK_TYPE_CATEGORIES.items():
        op.execute(tasks.update().where(tasks.c.task_type == task_type).values(category=category))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_column('category')
