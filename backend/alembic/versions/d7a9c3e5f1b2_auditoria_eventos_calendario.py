"""Auditoria append-only de alterações a eventos do calendário.

Regista criação, alteração e cancelamento de cada evento (incluindo cada
ocorrência de uma série semanal), com o autor e as diferenças campo a campo.
Uma operação sobre uma série altera dezenas de linhas de uma só vez, por isso
o histórico é a única forma de reconstituir o que mudou. A tabela não tem
chaves estrangeiras para sobreviver à eventual remoção de eventos/utilizadores.

Revision ID: d7a9c3e5f1b2
Revises: c4e6a8b0d2f1
"""
from __future__ import annotations

from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "d7a9c3e5f1b2"
down_revision: str | Sequence[str] | None = "c4e6a8b0d2f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calendar_event_audit",
        sa.Column("event_id", app.db.GUID(), nullable=False),
        sa.Column("series_id", app.db.GUID(), nullable=True),
        sa.Column("actor_user_id", app.db.GUID(), nullable=False),
        sa.Column("actor_person_id", app.db.GUID(), nullable=True),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("field_changes", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # Vocabulário congelado em literal (ver app/models/constraints.py).
        sa.CheckConstraint(
            "action IN ('create', 'update', 'cancel')", name="ck_calendar_event_audit_action"
        ),
    )
    op.create_index("ix_calendar_event_audit_event_id", "calendar_event_audit", ["event_id"])
    op.create_index("ix_calendar_event_audit_series_id", "calendar_event_audit", ["series_id"])


def downgrade() -> None:
    op.drop_index("ix_calendar_event_audit_series_id", table_name="calendar_event_audit")
    op.drop_index("ix_calendar_event_audit_event_id", table_name="calendar_event_audit")
    op.drop_table("calendar_event_audit")
