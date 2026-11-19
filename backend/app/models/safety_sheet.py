"""Ficha de segurança e versões históricas por projeto."""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk


class ProjectSafetySheet(UUIDPk, TimestampMixin, Base):
    __tablename__ = "project_safety_sheets"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("projects.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    roof_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    roof_other: Mapped[str | None] = mapped_column(Text, nullable=True)
    approximate_height_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    access_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    access_other: Mapped[str | None] = mapped_column(Text, nullable=True)
    risks_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    risk_other: Mapped[str | None] = mapped_column(Text, nullable=True)
    safety_measures_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default="[]"
    )
    measure_other: Mapped[str | None] = mapped_column(Text, nullable=True)
    safety_responsible: Mapped[str | None] = mapped_column(Text, nullable=True)
    emergency_contacts: Mapped[str | None] = mapped_column(Text, nullable=True)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    work_start_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    work_end_date: Mapped[dt.date | None] = mapped_column(nullable=True)

    workers: Mapped[list[ProjectSafetySheetWorker]] = relationship(
        back_populates="sheet",
        cascade="all, delete-orphan",
        order_by="ProjectSafetySheetWorker.position",
        lazy="selectin",
    )


class ProjectSafetySheetWorker(UUIDPk, Base):
    __tablename__ = "project_safety_sheet_workers"
    __table_args__ = (UniqueConstraint("safety_sheet_id", "position", name="uq_safety_sheet_worker_position"),)

    safety_sheet_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("project_safety_sheets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    name_snapshot: Mapped[str] = mapped_column(String(256), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    installer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("installers.id"), nullable=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("installer_teams.id"), nullable=True
    )

    sheet: Mapped[ProjectSafetySheet] = relationship(back_populates="workers")


class ProjectSafetySheetHistory(UUIDPk, Base):
    """Snapshot append-only de cada versão da ficha."""

    __tablename__ = "project_safety_sheet_history"
    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_safety_sheet_history_version"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    changed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
