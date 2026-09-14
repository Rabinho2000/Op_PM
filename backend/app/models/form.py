from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk


class FormTemplate(UUIDPk, TimestampMixin, Base):
    __tablename__ = "form_templates"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    # visita_tecnica | comissionamento | checklist_seguranca
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_json: Mapped[str] = mapped_column(Text, default="{}")
    requires_photos: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class FormResponse(UUIDPk, TimestampMixin, Base):
    __tablename__ = "form_responses"

    template_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("form_templates.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=False)
    answers_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), default="aberto")  # aberto | bloqueado_fotos | fechado
    submitted_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
