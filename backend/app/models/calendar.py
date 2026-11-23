"""Visitas e eventos de calendário.

Fonte de verdade: o calendário real vive no Microsoft 365/Exchange Online
(via Graph). `CalendarEvent.graph_event_id` só é preenchido depois de o
evento ser efetivamente criado lá — antes disso, é um rascunho local sem
qualquer efeito fora da plataforma (ver `app/adapters/graph_mail.py`).
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, JSON, String, Table, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk
from app.models.constraints import vocabulary_check

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.people import Person
    from app.models.task import Task
    from app.models.workflow import WorkflowStage, WorkflowSubtask


class Visit(UUIDPk, TimestampMixin, Base):
    __tablename__ = "visits"

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # visita_tecnica | comissionamento
    status: Mapped[str] = mapped_column(
        String(32), default="proposta", nullable=False
    )  # proposta | confirmada | concluida | cancelada
    proposed_at_options: Mapped[str] = mapped_column(Text, default="[]")  # JSON de datas propostas
    confirmed_datetime: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    approved_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )

    events: Mapped[list[CalendarEvent]] = relationship(back_populates="visit")


# Vocabulários fechados; o CHECK na BD é gerado a partir destas constantes.
CALENDAR_SERIES_RULES = frozenset({"weekly"})
CALENDAR_AUDIT_ACTIONS = frozenset({"create", "update", "cancel"})


class CalendarEventSeries(UUIDPk, TimestampMixin, Base):
    """Metadados de uma série semanal de eventos do calendário local.

    As ocorrências continuam a ser ``CalendarEvent`` normais, preservando a
    API e os filtros existentes. A série guarda apenas a regra necessária
    para tornar as ocorrências idempotentes e permitir alterações em âmbito
    explícito.
    """

    __tablename__ = "calendar_event_series"
    __table_args__ = (
        UniqueConstraint(
            "created_by_user_id", "idempotency_key", name="uq_calendar_event_series_idempotency"
        ),
        vocabulary_check("recurrence_rule", CALENDAR_SERIES_RULES, name="ck_calendar_event_series_recurrence_rule"),
    )

    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    recurrence_rule: Mapped[str] = mapped_column(String(16), nullable=False, default="weekly")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Lisbon")
    starts_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    starts_at_local: Mapped[str] = mapped_column(String(5), nullable=False)
    ends_day_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    ends_at_local: Mapped[str] = mapped_column(String(5), nullable=False)
    starts_fold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ends_fold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    until_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)

    events: Mapped[list[CalendarEvent]] = relationship(back_populates="series")


calendar_event_assignees = Table(
    "calendar_event_assignees",
    Base.metadata,
    Column("event_id", GUID(), ForeignKey("calendar_events.id", ondelete="CASCADE"), primary_key=True),
    Column("person_id", GUID(), ForeignKey("people.id"), primary_key=True, index=True),
)


class CalendarEvent(UUIDPk, TimestampMixin, Base):
    __tablename__ = "calendar_events"
    __table_args__ = (
        UniqueConstraint(
            "series_id", "series_occurrence_index", name="uq_calendar_event_series_occurrence"
        ),
    )

    visit_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("visits.id"), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=True)
    # Quando presente, a camada de serviço valida sempre task.project_id ==
    # project_id antes de gravar — nunca liga um evento a uma tarefa de
    # outro projeto (ver app/services/planning.py, docs/MAP_AND_PLANNING.md).
    task_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("tasks.id"), nullable=True)
    assigned_to_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    # Categoria é um código estável do catálogo da API; não depende de
    # títulos livres do Processo nem de integração externa.
    category: Mapped[str] = mapped_column(String(32), default="other", nullable=False)
    # Índices criados pela migração f5a7c9d1e3b2; declarados aqui para o
    # modelo e o Alembic não divergirem (tests/test_alembic_schema.py).
    process_stage_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("workflow_stages.id"), nullable=True, index=True
    )
    process_subtask_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("workflow_subtasks.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="rascunho", nullable=False
    )  # rascunho | aprovado | publicado | cancelado
    graph_event_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # caminho local do fallback .ics enquanto o Graph não está configurado
    ics_fallback_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Nulos para todos os eventos legados e para eventos únicos. Ocorrências
    # semanais referenciam a série e têm índice estável começado em zero.
    series_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("calendar_event_series.id"), nullable=True, index=True
    )
    series_occurrence_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    visit: Mapped[Visit | None] = relationship(back_populates="events")
    project: Mapped[Project | None] = relationship()
    task: Mapped[Task | None] = relationship()
    assigned_to: Mapped[Person | None] = relationship(foreign_keys=[assigned_to_person_id])
    assignees: Mapped[list[Person]] = relationship(
        secondary=calendar_event_assignees,
        lazy="selectin",
        order_by="Person.display_name",
    )
    process_stage: Mapped[WorkflowStage | None] = relationship(foreign_keys=[process_stage_id])
    process_subtask: Mapped[WorkflowSubtask | None] = relationship(foreign_keys=[process_subtask_id])
    series: Mapped[CalendarEventSeries | None] = relationship(back_populates="events")


class CalendarEventAudit(UUIDPk, Base):
    """Registo append-only das alterações a eventos do calendário."""

    __tablename__ = "calendar_event_audit"
    __table_args__ = (
        vocabulary_check("action", CALENDAR_AUDIT_ACTIONS, name="ck_calendar_event_audit_action"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    series_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    actor_person_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)  # create | update | cancel
    field_changes: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
