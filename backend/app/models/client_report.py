"""Persistência dos relatórios semanais ao cliente."""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, Time, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk


class ClientReportConfig(UUIDPk, TimestampMixin, Base):
    __tablename__ = "client_report_configs"
    __table_args__ = (UniqueConstraint("project_id", name="uq_client_report_config_project"),)

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=False)
    enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    review_before_send: Mapped[bool] = mapped_column(default=False, nullable=False)
    weekday: Mapped[int] = mapped_column(default=0, nullable=False)
    send_time: Mapped[dt.time] = mapped_column(Time(), default=dt.time(9, 0), nullable=False)
    to_emails: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    cc_emails: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    weekly_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )


class ClientReportSend(UUIDPk, Base):
    __tablename__ = "client_report_sends"
    __table_args__ = (
        Index("ix_client_report_sends_project_week", "project_id", "iso_week"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=False)
    iso_week: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    from_email: Mapped[str] = mapped_column(String(320), nullable=False)
    to_emails: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    cc_emails: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    approved_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    graph_message_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
