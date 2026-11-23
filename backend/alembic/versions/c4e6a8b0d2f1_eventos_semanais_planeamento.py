"""Séries semanais idempotentes e ligações de ocorrência no planeamento.

Acrescenta ``calendar_event_series`` (regra semanal, chave de idempotência por
utilizador) e liga cada ocorrência (``calendar_events.series_id`` +
``series_occurrence_index``). Eventos existentes ficam com ambas as colunas a
NULL, ou seja, continuam a ser eventos únicos. O downgrade remove as colunas e
a tabela; as ocorrências já criadas mantêm-se como eventos únicos.

Revision ID: c4e6a8b0d2f1
Revises: d3f5a7c9e1b2
"""
from __future__ import annotations

from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "c4e6a8b0d2f1"
down_revision: str | Sequence[str] | None = "d3f5a7c9e1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calendar_event_series",
        sa.Column("created_by_user_id", app.db.GUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("recurrence_rule", sa.String(length=16), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("starts_at_local", sa.String(length=5), nullable=False),
        sa.Column("ends_day_offset", sa.Integer(), nullable=False),
        sa.Column("ends_at_local", sa.String(length=5), nullable=False),
        sa.Column("starts_fold", sa.Integer(), nullable=False),
        sa.Column("ends_fold", sa.Integer(), nullable=False),
        sa.Column("until_date", sa.Date(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "created_by_user_id", "idempotency_key", name="uq_calendar_event_series_idempotency"
        ),
        # Vocabulário congelado em literal (ver app/models/constraints.py).
        sa.CheckConstraint(
            "recurrence_rule IN ('weekly')", name="ck_calendar_event_series_recurrence_rule"
        ),
    )
    with op.batch_alter_table("calendar_events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("series_id", app.db.GUID(), nullable=True))
        batch_op.add_column(sa.Column("series_occurrence_index", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_calendar_events_series", "calendar_event_series", ["series_id"], ["id"]
        )
        batch_op.create_index("ix_calendar_events_series_id", ["series_id"], unique=False)
        batch_op.create_unique_constraint(
            "uq_calendar_event_series_occurrence", ["series_id", "series_occurrence_index"]
        )


def downgrade() -> None:
    with op.batch_alter_table("calendar_events", schema=None) as batch_op:
        batch_op.drop_constraint("uq_calendar_event_series_occurrence", type_="unique")
        batch_op.drop_index("ix_calendar_events_series_id")
        batch_op.drop_constraint("fk_calendar_events_series", type_="foreignkey")
        batch_op.drop_column("series_occurrence_index")
        batch_op.drop_column("series_id")
    op.drop_table("calendar_event_series")
