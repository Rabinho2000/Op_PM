"""guarda documento original da importacao de notas iniciais

Revision ID: f1134f80f657
Revises: 9d75fdc41128
Create Date: 2026-09-17 16:25:57.533262

Nota: `op.add_column` direto (autogenerate) funciona para SQLite numa
coluna nova, mas uma coluna `NOT NULL` sem valor por omissão falha se a
tabela já tiver linhas — por isso `server_default=""` na adição, seguido
de `batch_alter_table` para o remover (mesmo padrão de
65bf12876b1e_mvp_operacoes_inventario_com_.py para `suppliers.materials`),
para o valor por omissão em runtime ficar só no lado do ORM (`default=""`
em app/models/imports.py), nunca no esquema da base de dados.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1134f80f657'
down_revision: Union[str, Sequence[str], None] = '9d75fdc41128'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('field_import_batches', schema=None) as batch_op:
        batch_op.add_column(sa.Column('raw_document_text', sa.Text(), nullable=False, server_default=""))
    with op.batch_alter_table('field_import_batches', schema=None) as batch_op:
        batch_op.alter_column('raw_document_text', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('field_import_batches', schema=None) as batch_op:
        batch_op.drop_column('raw_document_text')
