"""afectações de equipas por obra

Revision ID: e8b2c4d6f0a1
Revises: d7a2c5e9b3f1
"""
import datetime as dt
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa

import app.db  # necessário para o tipo GUID portável


revision: str = "e8b2c4d6f0a1"
down_revision: Union[str, Sequence[str], None] = "d7a2c5e9b3f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Cria afectações e migra a equipa/janela legadas para a primeira afectação."""
    op.create_table(
        "project_team_assignments",
        sa.Column("project_id", app.db.GUID(), nullable=False),
        sa.Column("installer_id", app.db.GUID(), nullable=False),
        sa.Column("team_id", app.db.GUID(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.Column("created_by_person_id", app.db.GUID(), nullable=True),
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["installer_id", "team_id"],
            ["installer_teams.installer_id", "installer_teams.id"],
            name="fk_assignment_team_belongs_to_installer",
        ),
        sa.ForeignKeyConstraint(["created_by_person_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("end_date >= start_date", name="ck_assignment_dates_order"),
    )
    with op.batch_alter_table("project_team_assignments", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_project_team_assignments_project_id"), ["project_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_project_team_assignments_installer_id"), ["installer_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_project_team_assignments_team_id"), ["team_id"], unique=False)

    bind = op.get_bind()
    # A migração é deliberadamente determinística: a equipa legada passa a ser
    # a equipa principal e a sua janela é copiada sem alterar a janela da obra.
    rows = bind.execute(
        sa.text(
            "SELECT id, installer_id, installer_team_id, work_start_date, work_end_date "
            "FROM projects WHERE installer_team_id IS NOT NULL "
            "AND installer_id IS NOT NULL AND work_start_date IS NOT NULL AND work_end_date IS NOT NULL"
        )
    ).fetchall()
    assignments = sa.table(
        "project_team_assignments",
        sa.column("project_id", app.db.GUID()),
        sa.column("installer_id", app.db.GUID()),
        sa.column("team_id", app.db.GUID()),
        sa.column("start_date", sa.Date()),
        sa.column("end_date", sa.Date()),
        sa.column("note", sa.Text()),
        sa.column("id", app.db.GUID()),
    )
    def as_date(value: object) -> dt.date:
        # `sa.text()` não conhece os tipos das colunas no SQLite e devolve as
        # datas como texto; no PostgreSQL já são `date`. A conversão explícita
        # mantém a migração portável entre os dois motores.
        if isinstance(value, dt.datetime):
            return value.date()
        if isinstance(value, dt.date):
            return value
        return dt.date.fromisoformat(str(value))

    for project_id, installer_id, team_id, start_date, end_date in rows:
        bind.execute(
            sa.insert(assignments).values(
                id=uuid.uuid4(),
                project_id=project_id,
                installer_id=installer_id,
                team_id=team_id,
                start_date=as_date(start_date),
                end_date=as_date(end_date),
                note="",
            )
        )


def downgrade() -> None:
    """Remove as afectações; os campos legados permanecem intactos."""
    with op.batch_alter_table("project_team_assignments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_project_team_assignments_team_id"))
        batch_op.drop_index(batch_op.f("ix_project_team_assignments_installer_id"))
        batch_op.drop_index(batch_op.f("ix_project_team_assignments_project_id"))
    op.drop_table("project_team_assignments")
