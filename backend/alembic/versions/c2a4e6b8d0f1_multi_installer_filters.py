"""Lista de instaladores nos filtros do Calendário de obras.

Revision ID: c2a4e6b8d0f1
Revises: d1f3b5c7e9a2
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2a4e6b8d0f1"
down_revision: str | Sequence[str] | None = "d1f3b5c7e9a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL marks rows created before this revision; application reads retain
    # their legacy installer_id as a singleton selection without rewriting it.
    op.add_column(
        "works_calendar_preferences",
        sa.Column("installer_ids", sa.JSON(), nullable=True),
    )
    op.add_column(
        "works_calendar_saved_views",
        sa.Column("installer_ids", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Retain the first selected installer in the legacy column.

    Downgrading to the single-installer schema necessarily discards any
    additional IDs in a multi-selection, but preserves its first ID when the
    legacy installer_id is NULL.
    """
    for table_name in ("works_calendar_saved_views", "works_calendar_preferences"):
        table = sa.table(
            table_name,
            sa.column("installer_id", sa.String()),
            sa.column("installer_ids", sa.JSON()),
        )
        op.execute(
            table.update()
            .where(table.c.installer_id.is_(None))
            .where(table.c.installer_ids.is_not(None))
            .values(installer_id=table.c.installer_ids[0].as_string())
        )

    with op.batch_alter_table("works_calendar_saved_views", schema=None) as batch_op:
        batch_op.drop_column("installer_ids")
    with op.batch_alter_table("works_calendar_preferences", schema=None) as batch_op:
        batch_op.drop_column("installer_ids")
