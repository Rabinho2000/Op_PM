"""Personal Task-list preferences and saved views.

Revision ID: f3b5d7e9a1c2
Revises: e2f4a6c8b0d1
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

import app.db
from alembic import op

revision: str = "f3b5d7e9a1c2"
down_revision: str | Sequence[str] | None = "e2f4a6c8b0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_task_list_views_active_user_name"


def upgrade() -> None:
    op.create_table(
        "task_list_preferences",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("user_id", app.db.GUID(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_task_list_preferences_user"),
    )
    op.create_table(
        "task_list_views",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("user_id", app.db.GUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        _INDEX,
        "task_list_views",
        ["user_id", "name"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
        postgresql_where=sa.text("is_active IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="task_list_views")
    op.drop_table("task_list_views")
    op.drop_table("task_list_preferences")
