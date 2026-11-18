"""Um só envio ativo do relatório semanal por projeto e semana ISO.

Índice único parcial em client_report_sends(project_id, iso_week) para os
estados pending/pending_review/sent: impede que o scheduler, o "Enviar agora"
e a aprovação de um rascunho entreguem o mesmo relatório duas vezes.

Revision ID: b9e1d3f5a7c2
Revises: a6c8e0f2d4b1
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9e1d3f5a7c2"
down_revision: str | Sequence[str] | None = "a6c8e0f2d4b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_client_report_sends_active_week"
_PREDICATE = "status IN ('pending', 'pending_review', 'sent')"


def upgrade() -> None:
    bind = op.get_bind()
    duplicates = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM (SELECT project_id, iso_week FROM client_report_sends "
            f"WHERE {_PREDICATE} GROUP BY project_id, iso_week HAVING COUNT(*) > 1) d"
        )
    ).scalar_one()
    if duplicates:
        raise RuntimeError(
            f"Há {duplicates} par(es) projeto/semana com mais de um envio ativo em "
            "client_report_sends. Rever manualmente antes de aplicar esta migração."
        )
    op.create_index(
        _INDEX,
        "client_report_sends",
        ["project_id", "iso_week"],
        unique=True,
        sqlite_where=sa.text(_PREDICATE),
        postgresql_where=sa.text(_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="client_report_sends")
