"""Payment receipt markers attached to a project."""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, GUID
from app.models.base import UUIDPk
from app.models.constraints import vocabulary_check
from app.models.people import Person

PAYMENT_MILESTONES: tuple[str, ...] = (
    "adjudicacao",
    "entrada_obra",
    "fim_obra",
    "certificado_final",
)

PAYMENT_MILESTONE_LABELS: dict[str, str] = {
    "adjudicacao": "Adjudicação",
    "entrada_obra": "Entrada de Obra",
    "fim_obra": "Fim de Obra",
    "certificado_final": "Certificado final",
}


class ProjectPaymentMilestone(UUIDPk, Base):
    __tablename__ = "project_payment_milestones"
    __table_args__ = (
        vocabulary_check("milestone", PAYMENT_MILESTONES, name="ck_project_payment_milestone_code"),
        UniqueConstraint("project_id", "milestone", name="uq_project_payment_milestone"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("projects.id", ondelete="CASCADE", name="fk_project_payment_project"), nullable=False, index=True
    )
    milestone: Mapped[str] = mapped_column(String(32), nullable=False)
    received: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    marked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    marked_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id", ondelete="SET NULL", name="fk_project_payment_marked_by"), nullable=True
    )

    marked_by_person: Mapped[Person | None] = relationship(lazy="joined")
