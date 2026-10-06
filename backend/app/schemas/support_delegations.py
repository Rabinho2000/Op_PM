from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class SupportDelegationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pm_person_id: uuid.UUID
    pm_display_name: str
    support_person_id: uuid.UUID
    support_display_name: str


class SupportDelegationUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pm_person_id: uuid.UUID
    support_person_id: uuid.UUID
