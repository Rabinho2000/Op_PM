"""Campos visuais e ficheiros do catálogo de inventário.

Revision ID: d1f3b5c7e9a2
Revises: b8d0f2a4c6e7
"""
from __future__ import annotations

from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "d1f3b5c7e9a2"
down_revision: str | Sequence[str] | None = "b8d0f2a4c6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("inventory_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("manufacturer", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("model", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("subcategory", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("power_w", sa.Numeric(precision=14, scale=3), nullable=True))
        batch_op.add_column(sa.Column("cross_section_mm2", sa.Numeric(precision=10, scale=3), nullable=True))
        batch_op.add_column(sa.Column("photo_storage_name", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("photo_content_type", sa.String(length=32), nullable=True))

    op.create_table(
        "inventory_item_documents",
        sa.Column("item_id", app.db.GUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("stored_name", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("created_by_person_id", app.db.GUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.CheckConstraint("kind IN ('datasheet', 'manual', 'guia', 'outro')", name="ck_inventory_item_document_kind"),
        sa.ForeignKeyConstraint(["created_by_person_id"], ["people.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["inventory_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stored_name", name="uq_inventory_item_documents_stored_name"),
    )
    op.create_index(
        "ix_inventory_item_documents_item_active",
        "inventory_item_documents",
        ["item_id", "deleted_at", "created_at"],
        unique=False,
    )
    op.create_table(
        "inventory_category_images",
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("stored_name", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("updated_by_person_id", app.db.GUID(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["updated_by_person_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("category"),
        sa.UniqueConstraint("stored_name", name="uq_inventory_category_images_stored_name"),
    )


def downgrade() -> None:
    op.drop_table("inventory_category_images")
    op.drop_index("ix_inventory_item_documents_item_active", table_name="inventory_item_documents")
    op.drop_table("inventory_item_documents")
    with op.batch_alter_table("inventory_items", schema=None) as batch_op:
        batch_op.drop_column("photo_content_type")
        batch_op.drop_column("photo_storage_name")
        batch_op.drop_column("cross_section_mm2")
        batch_op.drop_column("power_w")
        batch_op.drop_column("subcategory")
        batch_op.drop_column("model")
        batch_op.drop_column("manufacturer")
