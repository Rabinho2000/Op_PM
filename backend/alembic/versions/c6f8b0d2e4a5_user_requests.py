"""User request threads and messages.

Revision ID: c6f8b0d2e4a5
Revises: b5e7a9c1d3f4
"""
from __future__ import annotations

from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "c6f8b0d2e4a5"
down_revision: str | Sequence[str] | None = "b5e7a9c1d3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_requests",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("created_by_user_id", app.db.GUID(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("page_path", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_user_id", app.db.GUID(), nullable=True),
        sa.CheckConstraint(
            "status IN ('open', 'resolved')",
            name="ck_user_requests_status",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_requests_status_updated_at",
        "user_requests",
        ["status", "updated_at"],
    )

    op.create_table(
        "user_request_messages",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("request_id", app.db.GUID(), nullable=False),
        sa.Column("author_user_id", app.db.GUID(), nullable=False),
        sa.Column("is_staff_reply", sa.Boolean(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["user_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_request_messages_request_id_created_at",
        "user_request_messages",
        ["request_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_request_messages_request_id_created_at",
        table_name="user_request_messages",
    )
    op.drop_table("user_request_messages")
    op.drop_index("ix_user_requests_status_updated_at", table_name="user_requests")
    op.drop_table("user_requests")
