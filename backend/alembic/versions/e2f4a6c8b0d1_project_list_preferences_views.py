"""Personal Projects-list preferences and saved views.

Revision ID: e2f4a6c8b0d1
Revises: d9e1f3a5b7c2
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

import app.db

revision: str = "e2f4a6c8b0d1"
down_revision: str | Sequence[str] | None = "d9e1f3a5b7c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_project_list_views_active_user_name"


def upgrade() -> None:
    op.create_table(
        "project_list_preferences",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("user_id", app.db.GUID(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_project_list_preferences_user"),
    )
    op.create_table(
        "project_list_views",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("user_id", app.db.GUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        _INDEX,
        "project_list_views",
        ["user_id", "name"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
        postgresql_where=sa.text("is_active IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="project_list_views")
    op.drop_table("project_list_views")
    op.drop_table("project_list_preferences")
