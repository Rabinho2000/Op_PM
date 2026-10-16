"""Schemas das vistas pessoais guardadas do Calendário de obras."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

WorksSavedViewZoom = Literal["weeks", "months", "quarters", "month_days"]


class SavedViewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr
    zoom: WorksSavedViewZoom = "month_days"
    lifecycle_status: list[StrictStr] = Field(default_factory=list)
    pm_person_id: uuid.UUID | None = None
    installer_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    show_idle: StrictBool = False


class SavedViewPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr | None = None
    zoom: WorksSavedViewZoom | None = None
    lifecycle_status: list[StrictStr] | None = None
    pm_person_id: uuid.UUID | None = None
    installer_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    show_idle: StrictBool | None = None


class SavedViewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    zoom: WorksSavedViewZoom
    lifecycle_status: list[str]
    pm_person_id: uuid.UUID | None
    installer_id: uuid.UUID | None
    team_id: uuid.UUID | None
    show_idle: bool
    created_at: dt.datetime
    updated_at: dt.datetime
