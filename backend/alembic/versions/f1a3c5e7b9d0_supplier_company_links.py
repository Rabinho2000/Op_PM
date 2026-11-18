"""Associa fornecedores a uma ou ambas as empresas.

Revision ID: f1a3c5e7b9d0
Revises: c2a4e6b8d0f1
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db import GUID

revision: str = "f1a3c5e7b9d0"
down_revision: str | Sequence[str] | None = "c2a4e6b8d0f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "supplier_company_links",
        sa.Column("supplier_id", GUID(), nullable=False),
        sa.Column("company_code", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "company_code IN ('solcor', 'verde_milenar')",
            name="ck_supplier_company_links_company_code",
        ),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("supplier_id", "company_code"),
    )


def downgrade() -> None:
    op.drop_table("supplier_company_links")
