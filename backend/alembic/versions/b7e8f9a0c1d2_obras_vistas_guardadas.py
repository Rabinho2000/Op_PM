"""vistas pessoais guardadas do Calendário de obras

Revision ID: b7e8f9a0c1d2
Revises: a9d4f6c2e8b1

Cada vista é uma combinação nomeada de filtros persistentes, propriedade de
uma conta autenticada. Não guarda a janela temporal do calendário.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

import app.db

revision: str = "b7e8f9a0c1d2"
down_revision: str | Sequence[str] | None = "a9d4f6c2e8b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "works_calendar_saved_views",
        sa.Column("user_id", app.db.GUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("zoom", sa.String(length=16), nullable=False),
        sa.Column("lifecycle_status", sa.JSON(), nullable=False),
        sa.Column("pm_person_id", app.db.GUID(), nullable=True),
        sa.Column("installer_id", app.db.GUID(), nullable=True),
        sa.Column("team_id", app.db.GUID(), nullable=True),
        sa.Column("show_idle", sa.Boolean(), nullable=False),
        sa.Column("id", app.db.GUID(), nullable=False),
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
        sa.ForeignKeyConstraint(["pm_person_id"], ["people.id"]),
        sa.ForeignKeyConstraint(["installer_id"], ["installers.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["installer_teams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "name",
            name="uq_works_calendar_saved_views_user_name",
        ),
    )


def downgrade() -> None:
    op.drop_table("works_calendar_saved_views")
