"""DTO for the private embedded cable-dimensioning tool."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, StrictStr


class CableToolRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine_version: StrictStr
    sha256: StrictStr
    script: StrictStr
