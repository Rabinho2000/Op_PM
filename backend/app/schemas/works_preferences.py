"""Schemas da preferência pessoal do Calendário de obras."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr

WorksPreferenceZoom = Literal["weeks", "months", "quarters", "month_days"]


class WorksPreferenceRead(BaseModel):
    zoom: WorksPreferenceZoom
    lifecycle_status: list[str]
    pm_person_id: uuid.UUID | None
    installer_id: uuid.UUID | None
    team_id: uuid.UUID | None
    show_idle: bool


class WorksPreferencePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # `None` is accepted at schema level so the service can reject it together
    # with all other fields before changing the stored row. Nullable IDs use it
    # deliberately as the clear operation.
    zoom: WorksPreferenceZoom | None = None
    lifecycle_status: list[StrictStr] | None = None
    pm_person_id: uuid.UUID | None = None
    installer_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    show_idle: StrictBool | None = None
