"""Categorias de inventário geridas pelos utilizadores.

Cria `inventory_categories` e semeia-a com as categorias da lista fechada
anterior, para que o vocabulário em uso continue idêntico após a migração.
`inventory_items.category` não tem CHECK de vocabulário e não é alterado.

Revision ID: e4c7a9b1d3f5
Revises: d3f5a7c9e1b2
"""
from __future__ import annotations

import unicodedata
from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "e4c7a9b1d3f5"
down_revision: str | Sequence[str] | None = "d3f5a7c9e1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Cópia congelada da lista fechada que existia em `app.models.inventory`;
# uma migração não deve depender do código aplicacional que evolui depois.
_SEED_CATEGORIES: tuple[str, ...] = (
    "Painéis",
    "Inversores",
    "Baterias",
    "Estruturas",
    "Cabos DC",
    "Cabos AC",
    "Proteções/Quadros",
    "Conectores",
    "Monitorização/Comunicação",
    "Consumíveis",
    "Outros",
)


def _key(value: str) -> str:
    """Mesma chave que `app.utils.text.alnum_casefold_key` (NFKD, casefold, alfanumérico)."""
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    return "".join(char for char in decomposed if char.isalnum())


def upgrade() -> None:
    table = op.create_table(
        "inventory_categories",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("normalized_key", sa.String(length=256), nullable=False),
        sa.Column("created_by_person_id", app.db.GUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_inventory_categories_name_nonempty"),
        sa.CheckConstraint("length(normalized_key) > 0", name="ck_inventory_categories_key_nonempty"),
        sa.ForeignKeyConstraint(["created_by_person_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("name"),
        sa.UniqueConstraint("normalized_key", name="uq_inventory_categories_normalized_key"),
    )
    op.bulk_insert(table, [{"name": name, "normalized_key": _key(name)} for name in _SEED_CATEGORIES])


def downgrade() -> None:
    op.drop_table("inventory_categories")
