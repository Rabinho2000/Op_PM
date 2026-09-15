"""Férias e outras ausências — modelo mínimo pedido para o MVP: pessoa,
intervalo de datas, tipo, nota, estado. Sem fluxo de aprovação nesta fase
(uma ausência criada fica logo `aprovada`) — ver docs/OPEN_QUESTIONS.md
sobre se um fluxo de pedido/aprovação é necessário no futuro.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk

TYPE_FERIAS = "ferias"
TYPE_BAIXA_MEDICA = "baixa_medica"
TYPE_OUTRO = "outro"
ABSENCE_TYPES: frozenset[str] = frozenset({TYPE_FERIAS, TYPE_BAIXA_MEDICA, TYPE_OUTRO})

STATUS_APROVADA = "aprovada"
STATUS_CANCELADA = "cancelada"
ABSENCE_STATUSES: frozenset[str] = frozenset({STATUS_APROVADA, STATUS_CANCELADA})


class Absence(UUIDPk, TimestampMixin, Base):
    __tablename__ = "absences"

    person_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("people.id"), nullable=False)
    start_date: Mapped[dt.date] = mapped_column(nullable=False)
    end_date: Mapped[dt.date] = mapped_column(nullable=False)
    type: Mapped[str] = mapped_column(String(32), default=TYPE_FERIAS, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default=STATUS_APROVADA, nullable=False)
    created_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )

    person: Mapped["Person"] = relationship(foreign_keys=[person_id])
