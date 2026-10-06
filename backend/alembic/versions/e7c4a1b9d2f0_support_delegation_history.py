"""auditoria append-only das delegações de suporte

Revision ID: e7c4a1b9d2f0
Revises: d1a7f3c9e2b4
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import app.db

revision: str = "e7c4a1b9d2f0"
down_revision: Union[str, Sequence[str], None] = "d1a7f3c9e2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "support_delegation_history",
        sa.Column("id", app.db.GUID(), primary_key=True, nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("pm_person_id", app.db.GUID(), sa.ForeignKey("people.id"), nullable=False),
        sa.Column("old_support_person_id", app.db.GUID(), sa.ForeignKey("people.id"), nullable=True),
        sa.Column("new_support_person_id", app.db.GUID(), sa.ForeignKey("people.id"), nullable=True),
        sa.Column("changed_by_person_id", app.db.GUID(), sa.ForeignKey("people.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("support_delegation_history")
