"""Schemas dos alarmes de etapas do processo."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field


class AlertStageRead(BaseModel):
    id: uuid.UUID
    code: str
    title: str
    subscribed: bool


class AlertPhaseRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    stages: list[AlertStageRead]


class AlertSubscriptionsRead(BaseModel):
    phases: list[AlertPhaseRead]


class AlertSubscriptionsUpdate(BaseModel):
    stage_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


class NotificationRead(BaseModel):
    id: uuid.UUID
    kind: str
    message: str
    project_id: uuid.UUID | None = None
    project_name: str | None = None
    stage_id: uuid.UUID | None = None
    stage_title: str | None = None
    is_read: bool
    created_at: dt.datetime
    read_at: dt.datetime | None = None


class NotificationListRead(BaseModel):
    items: list[NotificationRead]
    total: int
    limit: int
    offset: int


class UnreadCountRead(BaseModel):
    unread: int


class MarkAllReadRead(BaseModel):
    marked: int
