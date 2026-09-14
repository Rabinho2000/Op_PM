"""Auditoria de cada ação de IA. Toda a chamada a uma ferramenta do Claude —
mesmo em modo mock — grava aqui: quem pediu, que ferramenta, resumo do
input/output, e o estado de aprovação. Nenhuma ferramenta de IA pode marcar
`status='executed'` sozinha para uma ação irreversível (email, evento,
adjudicação, alteração de custo/stock) — isso exige `approved_by_person_id`
preenchido por uma ação humana explícita.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk


class AiAuditLog(UUIDPk, TimestampMixin, Base):
    __tablename__ = "ai_audit_log"

    requested_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    input_summary: Mapped[str] = mapped_column(Text, default="")
    output_summary: Mapped[str] = mapped_column(Text, default="")
    related_entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # proposed | approved | rejected | executed
    status: Mapped[str] = mapped_column(String(32), default="proposed", nullable=False)
    approved_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
