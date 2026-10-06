"""Schemas públicos da API de relatório semanal ao cliente."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class ClientReportConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    review_before_send: bool = False
    weekday: int = Field(default=0, ge=0, le=6)
    send_time: str = "09:00"
    to_emails: list[str] = Field(default_factory=list)
    cc_emails: list[str] = Field(default_factory=list)
    weekly_note: str | None = None


class ClientReportSendRead(BaseModel):
    id: uuid.UUID
    iso_week: str
    status: str
    trigger: str
    subject: str
    to_emails: list[str]
    cc_emails: list[str]
    sent_at: str | None = None
    created_at: str | None = None
    error: str | None = None


class ClientReportPreviewRead(BaseModel):
    subject: str
    body_html: str
    from_email: str | None = None
    to: list[str]
    cc: list[str]
