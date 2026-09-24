"""fornecedores: telefone, site, notas e tipos de material

Revision ID: a3f5d81c9e42
Revises: 7c1e4a9d2b30
Create Date: 2026-09-24 18:00:00.000000

"""
import unicodedata
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.db  # necessário para o tipo de coluna portável app.db.GUID()


# revision identifiers, used by Alembic.
revision: str = 'a3f5d81c9e42'
down_revision: Union[str, Sequence[str], None] = '7c1e4a9d2b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _key(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", " ".join(text.split()).lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def upgrade() -> None:
    """Upgrade schema.

    Acrescenta `phone`, `website` e `notes` a `suppliers`, e cria os tipos de
    material (D-070): `supplier_material_types` + a associação
    `supplier_material_type_links`. O `category` antigo (um só tipo, em texto)
    passa a tipo de material de cada fornecedor que o tinha — nada se perde; o
    campo antigo mantém-se.
    """
    op.create_table(
        'supplier_material_types',
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('name_key', sa.String(length=128), nullable=False),
        sa.Column('id', app.db.GUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name_key'),
    )
    op.create_table(
        'supplier_material_type_links',
        sa.Column('supplier_id', app.db.GUID(), nullable=False),
        sa.Column('material_type_id', app.db.GUID(), nullable=False),
        sa.ForeignKeyConstraint(['material_type_id'], ['supplier_material_types.id']),
        sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id']),
        sa.PrimaryKeyConstraint('supplier_id', 'material_type_id'),
    )
    with op.batch_alter_table('suppliers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('phone', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('website', sa.String(length=512), nullable=True))
        # server_default só para as linhas existentes; o valor em runtime vem do ORM.
        batch_op.add_column(sa.Column('notes', sa.Text(), nullable=False, server_default=''))
    with op.batch_alter_table('suppliers', schema=None) as batch_op:
        batch_op.alter_column('notes', server_default=None)

    bind = op.get_bind()
    # Tabelas leves tipadas com GUID: o mesmo código serve SQLite (texto) e PostgreSQL (uuid).
    types_tbl = sa.table(
        'supplier_material_types',
        sa.column('id', app.db.GUID()),
        sa.column('name', sa.String()),
        sa.column('name_key', sa.String()),
    )
    links_tbl = sa.table(
        'supplier_material_type_links',
        sa.column('supplier_id', app.db.GUID()),
        sa.column('material_type_id', app.db.GUID()),
    )
    types_by_key: dict = {}
    for supplier_id, category in bind.execute(sa.text("SELECT id, category FROM suppliers")).fetchall():
        if not category or not category.strip():
            continue
        display = " ".join(category.replace("_", " ").split()).capitalize()
        key = _key(display)
        if key not in types_by_key:
            type_id = uuid.uuid4()
            bind.execute(sa.insert(types_tbl).values(id=type_id, name=display, name_key=key))
            types_by_key[key] = type_id
        bind.execute(sa.insert(links_tbl).values(supplier_id=supplier_id, material_type_id=types_by_key[key]))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('suppliers', schema=None) as batch_op:
        batch_op.drop_column('notes')
        batch_op.drop_column('website')
        batch_op.drop_column('phone')
    op.drop_table('supplier_material_type_links')
    op.drop_table('supplier_material_types')
