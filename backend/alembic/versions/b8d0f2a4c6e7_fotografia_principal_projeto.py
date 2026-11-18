"""Fotografia principal da instalação por projeto.

Revision ID: b8d0f2a4c6e7
Revises: a7c9e1f3b5d6
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d0f2a4c6e7"
down_revision: str | Sequence[str] | None = "a7c9e1f3b5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("primary_photo_storage_name", sa.String(length=128), nullable=True))
    op.add_column("projects", sa.Column("primary_photo_content_type", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "primary_photo_content_type")
    op.drop_column("projects", "primary_photo_storage_name")
