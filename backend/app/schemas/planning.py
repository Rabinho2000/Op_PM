from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict


class CalendarEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    visit_id: uuid.UUID | None
    project_id: uuid.UUID | None
    task_id: uuid.UUID | None
    assigned_to_person_id: uuid.UUID | None
    title: str
    starts_at: dt.datetime
    ends_at: dt.datetime
    status: str
    graph_event_id: str | None
    created_at: dt.datetime

    project_name: str | None = None
    task_title: str | None = None
    assigned_to_display_name: str | None = None
    can_manage: bool = False


class CalendarEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    starts_at: dt.datetime
    ends_at: dt.datetime
    project_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    assigned_to_person_id: uuid.UUID | None = None


class CalendarEventUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    starts_at: dt.datetime | None = None
    ends_at: dt.datetime | None = None
    project_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    assigned_to_person_id: uuid.UUID | None = None
    status: str | None = None
