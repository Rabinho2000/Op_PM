from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel


class MyProcessStageRead(BaseModel):
    project_id: uuid.UUID
    project_name: str
    stage_id: uuid.UUID
    stage_code: str
    stage_title: str
    responsible_rule: str | None
    status: str
    planned_start: dt.date | None
    planned_end: dt.date | None
    done_count: int
    total_count: int
