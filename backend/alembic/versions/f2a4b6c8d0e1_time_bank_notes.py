"""Independent append-only notes for each time-bank person.

Revision ID: f2a4b6c8d0e1
Revises: f1a3c5e7b9d0
"""
from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "f2a4b6c8d0e1"
down_revision: str | Sequence[str] | None = "f1a3c5e7b9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "time_bank_notes",
        sa.Column("person_id", app.db.GUID(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", app.db.GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_time_bank_notes_person_created", "time_bank_notes", ["person_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_time_bank_notes_person_created", table_name="time_bank_notes")
    op.drop_table("time_bank_notes")
