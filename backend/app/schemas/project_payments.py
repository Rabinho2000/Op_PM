"""HTTP schemas for project payment milestones."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, StrictBool


class ProjectPaymentMilestoneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    milestone: str
    label: str
    received: bool
    marked_at: dt.datetime | None
    marked_by: str | None


class ProjectPaymentMilestoneUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    received: StrictBool
