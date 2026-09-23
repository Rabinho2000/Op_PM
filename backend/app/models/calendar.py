"""Visitas e eventos de calendário.

Fonte de verdade: o calendário real vive no Microsoft 365/Exchange Online
(via Graph). `CalendarEvent.graph_event_id` só é preenchido depois de o
evento ser efetivamente criado lá — antes disso, é um rascunho local sem
qualquer efeito fora da plataforma (ver `app/adapters/graph`).
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk


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

    events: Mapped[list["CalendarEvent"]] = relationship(back_populates="visit")


class CalendarEvent(UUIDPk, TimestampMixin, Base):
    __tablename__ = "calendar_events"

    visit_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("visits.id"), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=True)
    # Quando presente, a camada de serviço valida sempre task.project_id ==
    # project_id antes de gravar — nunca liga um evento a uma tarefa de
    # outro projeto (ver app/services/planning.py, docs/MAP_AND_PLANNING.md).
    task_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("tasks.id"), nullable=True)
    assigned_to_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
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

    visit: Mapped["Visit | None"] = relationship(back_populates="events")
    project: Mapped["Project | None"] = relationship()
    task: Mapped["Task | None"] = relationship()
