"""Metadados de documentos e fotografias. O ficheiro em si vive sempre no
SharePoint/OneDrive (`sharepoint_item_id`) — esta tabela nunca guarda bytes,
só a referência e os metadados usados para pesquisa/permissão/indexação.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk


class Document(UUIDPk, TimestampMixin, Base):
    __tablename__ = "documents"

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    tags: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=True)
    material_item_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("inventory_items.id"), nullable=True
    )
    sharepoint_item_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    sharepoint_drive_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    version: Mapped[str] = mapped_column(String(32), default="1")
    uploaded_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )


class Photo(UUIDPk, TimestampMixin, Base):
    __tablename__ = "photos"

    form_response_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("form_responses.id"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=True)
    sharepoint_item_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    uploaded_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
