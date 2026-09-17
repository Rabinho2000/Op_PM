"""Entidades do mapa operacional que não são projeto nem fornecedor:
pontos de recolha de material e pendências de obra. Ver
docs/MAP_AND_PLANNING.md e docs/PLAN_OPERATIONS_MVP.md secção 5.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk

ISSUE_CATEGORIES: frozenset[str] = frozenset({"obra", "material", "documentacao", "visita", "outro"})
ISSUE_STATUSES: frozenset[str] = frozenset({"aberta", "em_curso", "resolvida", "cancelada"})
ISSUE_PRIORITIES: frozenset[str] = frozenset({"low", "medium", "high", "urgent"})


class PickupPoint(UUIDPk, TimestampMixin, Base):
    __tablename__ = "pickup_points"

    name: Mapped[str] = mapped_column(String(256), nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("suppliers.id"), nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    schedule: Mapped[str | None] = mapped_column(String(256), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(256), nullable=True)
    materials: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ProjectIssue(UUIDPk, TimestampMixin, Base):
    """Pendência de obra visível no mapa — pode ser convertida numa `Task`
    (ver app/services/map.py:convert_issue_to_task), que nunca duplica a
    entidade: `related_task_id` liga-se à tarefa criada, a pendência
    continua a existir para controlo do próprio mapa."""

    __tablename__ = "project_issues"

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="outro", nullable=False)
    priority: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="aberta", nullable=False)
    assigned_to_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    due_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    related_task_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("tasks.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    visible_on_map: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
