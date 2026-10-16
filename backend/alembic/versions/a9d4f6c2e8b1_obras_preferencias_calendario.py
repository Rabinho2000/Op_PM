"""preferências pessoais do Calendário de obras

Revision ID: a9d4f6c2e8b1
Revises: f5a7c9d1e3b2

A preferência é uma linha própria por utilizador. A janela temporal do
calendário não é migrada nem congelada: continua a ser calculada pelo cliente.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

import app.db

revision: str = "a9d4f6c2e8b1"
down_revision: str | Sequence[str] | None = "f5a7c9d1e3b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "works_calendar_preferences",
        sa.Column("user_id", app.db.GUID(), nullable=False),
        sa.Column("zoom", sa.String(length=16), nullable=False),
        sa.Column("lifecycle_status", sa.JSON(), nullable=False),
        sa.Column("pm_person_id", app.db.GUID(), nullable=True),
        sa.Column("installer_id", app.db.GUID(), nullable=True),
        sa.Column("team_id", app.db.GUID(), nullable=True),
        sa.Column("show_idle", sa.Boolean(), nullable=False),
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pm_person_id"], ["people.id"]),
        sa.ForeignKeyConstraint(["installer_id"], ["installers.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["installer_teams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_works_calendar_preferences_user"),
    )


def downgrade() -> None:
    op.drop_table("works_calendar_preferences")
