"""relatório semanal ao cliente

Revision ID: a7c1e5d9f3b2
Revises: b4d8f2a6c1e3
Create Date: 2026-09-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.db


revision: str = "a7c1e5d9f3b2"
down_revision: Union[str, Sequence[str], None] = "c3e9f1a2b7d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "client_report_configs",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("project_id", app.db.GUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("review_before_send", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("weekday", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("send_time", sa.Time(), nullable=False, server_default="09:00:00"),
        sa.Column("to_emails", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("cc_emails", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("weekly_note", sa.Text(), nullable=True),
        sa.Column("updated_by_person_id", app.db.GUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["updated_by_person_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_client_report_config_project"),
    )
    op.create_table(
        "client_report_sends",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("project_id", app.db.GUID(), nullable=False),
        sa.Column("iso_week", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("from_email", sa.String(length=320), nullable=False),
        sa.Column("to_emails", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("cc_emails", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("approved_by_person_id", app.db.GUID(), nullable=True),
        sa.Column("graph_message_id", sa.String(length=512), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["approved_by_person_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_client_report_sends_project_week", "client_report_sends", ["project_id", "iso_week"]
    )


def downgrade() -> None:
    op.drop_index("ix_client_report_sends_project_week", table_name="client_report_sends")
    op.drop_table("client_report_sends")
    op.drop_table("client_report_configs")
