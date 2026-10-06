"""Definição do processo operacional (fases → etapas → subtarefas) como
 dados normalizados em base de dados.
"""
from __future__ import annotations

import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk


class Phase(UUIDPk, TimestampMixin, Base):
    __tablename__ = "phases"
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    color_hex: Mapped[str] = mapped_column(String(16), default="#888888")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    stages: Mapped[list["WorkflowStage"]] = relationship(back_populates="phase")


class WorkflowStage(UUIDPk, TimestampMixin, Base):
    __tablename__ = "workflow_stages"
    phase_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("phases.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    responsible_role_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    depends_on_stage_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("workflow_stages.id"), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_start_offset_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    planned_end_offset_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_contact_checkpoint: Mapped[bool] = mapped_column(default=False, nullable=False)
    contact_note: Mapped[str] = mapped_column(Text, default="")
    contact_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contact_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    responsible_rule: Mapped[str | None] = mapped_column(String(32), nullable=True)
    responsible_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phase: Mapped["Phase"] = relationship(back_populates="stages")
    subtasks: Mapped[list["WorkflowSubtask"]] = relationship(back_populates="stage")


class WorkflowSubtask(UUIDPk, TimestampMixin, Base):
    __tablename__ = "workflow_subtasks"
    stage_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("workflow_stages.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped["WorkflowStage"] = relationship(back_populates="subtasks")


class SupportDelegation(UUIDPk, TimestampMixin, Base):
    __tablename__ = "support_delegations"
    pm_person_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("people.id"), unique=True, nullable=False)
    support_person_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("people.id"), nullable=False)


class SupportDelegationHistory(UUIDPk, Base):
    __tablename__ = "support_delegation_history"
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    pm_person_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("people.id"), nullable=False)
    old_support_person_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("people.id"), nullable=True)
    new_support_person_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("people.id"), nullable=True)
    changed_by_person_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("people.id"), nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
