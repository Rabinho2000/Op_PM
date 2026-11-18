from __future__ import annotations

import datetime as dt
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

HolidayScope = Literal["nacional", "municipal", "empresa"]


class HolidayRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    date: dt.date
    name: str
    scope: HolidayScope
    is_active: bool
    created_at: dt.datetime
    updated_at: dt.datetime


class HolidayCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: dt.date
    name: str = Field(min_length=1, max_length=160)
    scope: HolidayScope

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("O nome do feriado não pode estar vazio.")
        return clean


class HolidayUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: dt.date | None = None
    name: str | None = Field(default=None, min_length=1, max_length=160)
    scope: HolidayScope | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        clean = value.strip()
        if not clean:
            raise ValueError("O nome do feriado não pode estar vazio.")
        return clean
