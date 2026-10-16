"""planeamento: preferências por utilizador, participantes e Processo no calendário

Revision ID: f5a7c9d1e3b2
Revises: d4e6f8a1b2c3

A migração preserva ``CalendarEvent.assigned_to_person_id`` como campo
compatível e faz backfill idempotente dos participantes primários para a nova
relação. Os marcos do Processo continuam read-only; só se adicionam as
referências opcionais dos eventos manuais.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.db


revision: str = "f5a7c9d1e3b2"
down_revision: Union[str, Sequence[str], None] = "d4e6f8a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FK_STAGE = "fk_calendar_events_process_stage"
_FK_SUBTASK = "fk_calendar_events_process_subtask"


def upgrade() -> None:
    op.create_table(
        "planning_preferences",
        sa.Column("user_id", app.db.GUID(), nullable=False),
        sa.Column("view", sa.String(length=16), nullable=False, server_default="month"),
        sa.Column("hide_weekends", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_planning_preferences_user"),
    )
    with op.batch_alter_table("planning_preferences", schema=None) as batch_op:
        batch_op.alter_column("view", server_default=None)
        batch_op.alter_column("hide_weekends", server_default=None)

    op.create_table(
        "calendar_event_assignees",
        sa.Column("event_id", app.db.GUID(), nullable=False),
        sa.Column("person_id", app.db.GUID(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["calendar_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("event_id", "person_id"),
    )
    op.create_index("ix_calendar_event_assignees_person_id", "calendar_event_assignees", ["person_id"])

    with op.batch_alter_table("calendar_events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("category", sa.String(length=32), nullable=False, server_default="other"))
    # O backfill por server_default tem de existir enquanto o batch SQLite copia
    # as linhas existentes; removê-lo na mesma operação faz o INSERT para a
    # tabela temporária falhar por NOT NULL.
    with op.batch_alter_table("calendar_events", schema=None) as batch_op:
        batch_op.alter_column("category", server_default=None)
        batch_op.add_column(sa.Column("process_stage_id", app.db.GUID(), nullable=True))
        batch_op.add_column(sa.Column("process_subtask_id", app.db.GUID(), nullable=True))
        batch_op.create_foreign_key(_FK_STAGE, "workflow_stages", ["process_stage_id"], ["id"])
        batch_op.create_foreign_key(_FK_SUBTASK, "workflow_subtasks", ["process_subtask_id"], ["id"])
        batch_op.create_index("ix_calendar_events_process_stage_id", ["process_stage_id"], unique=False)
        batch_op.create_index("ix_calendar_events_process_subtask_id", ["process_subtask_id"], unique=False)

    # Compatibilidade com eventos existentes: o primário antigo passa a ser
    # também participante. A coluna singular não é apagada nem alterada.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO calendar_event_assignees (event_id, person_id) "
            "SELECT id, assigned_to_person_id FROM calendar_events "
            "WHERE assigned_to_person_id IS NOT NULL"
        )
    )


def downgrade() -> None:
    # Só remove os objetos criados por esta revisão; o campo legado e os seus
    # dados permanecem no calendário.
    op.drop_index("ix_calendar_event_assignees_person_id", table_name="calendar_event_assignees")
    op.drop_table("calendar_event_assignees")
    with op.batch_alter_table("calendar_events", schema=None) as batch_op:
        batch_op.drop_index("ix_calendar_events_process_subtask_id")
        batch_op.drop_index("ix_calendar_events_process_stage_id")
        batch_op.drop_constraint(_FK_SUBTASK, type_="foreignkey")
        batch_op.drop_constraint(_FK_STAGE, type_="foreignkey")
        batch_op.drop_column("process_subtask_id")
        batch_op.drop_column("process_stage_id")
        batch_op.drop_column("category")
    op.drop_table("planning_preferences")
