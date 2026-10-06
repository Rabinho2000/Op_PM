"""Férias e outras ausências, incluindo o fluxo de aprovação de férias.

Só as férias (`ferias`) ficam pendentes para quem não tem
`absence.approve`. Baixas médicas e outros registos são aprovados no momento
em que são criados; os campos de decisão preservam sempre a auditoria da
última transição ou aprovação automática.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk

if TYPE_CHECKING:
    from app.models.people import Person

TYPE_FERIAS = "ferias"
TYPE_BAIXA_MEDICA = "baixa_medica"
TYPE_OUTRO = "outro"
ABSENCE_TYPES: frozenset[str] = frozenset({TYPE_FERIAS, TYPE_BAIXA_MEDICA, TYPE_OUTRO})

STATUS_PENDENTE = "pendente"
STATUS_APROVADA = "aprovada"
STATUS_REJEITADA = "rejeitada"
STATUS_CANCELADA = "cancelada"
ABSENCE_STATUSES: frozenset[str] = frozenset(
    {STATUS_PENDENTE, STATUS_APROVADA, STATUS_REJEITADA, STATUS_CANCELADA}
)


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
    decided_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cancelled_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    person: Mapped["Person"] = relationship(foreign_keys=[person_id])
    decided_by_person: Mapped["Person | None"] = relationship(foreign_keys=[decided_by_person_id])
    cancelled_by_person: Mapped["Person | None"] = relationship(foreign_keys=[cancelled_by_person_id])
