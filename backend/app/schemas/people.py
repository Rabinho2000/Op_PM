from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class PersonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    email: str | None
    is_active: bool
