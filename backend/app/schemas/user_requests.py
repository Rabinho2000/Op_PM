from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator


RequestStatus = Literal["open", "resolved"]
RequestStatusFilter = Literal["open", "resolved", "all"]
RequestScope = Literal["mine", "all"]


class _RequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: StrictStr = Field(min_length=1, max_length=2000)

    @field_validator("body", mode="before")
    @classmethod
    def strip_body(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("O corpo tem de ser texto.")
        return value.strip()


class RequestCreate(_RequestBody):
    page_path: str | None = None

    @field_validator("page_path", mode="before")
    @classmethod
    def keep_valid_page_path(cls, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        if (
            value.startswith("/")
            and "?" not in value
            and "#" not in value
            and len(value) <= 256
        ):
            return value
        return None


class RequestMessageCreate(_RequestBody):
    pass


class RequestStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: RequestStatus


class RequestMessageRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    author_name: str
    is_staff_reply: bool
    is_mine: bool
    body: str
    created_at: dt.datetime


class RequestListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    status: RequestStatus
    page_path: str | None
    created_at: dt.datetime
    updated_at: dt.datetime
    author_name: str
    message_count: int
    last_message_preview: str | None
    last_message_is_staff: bool | None


class RequestListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RequestListItem]
    total: int


class RequestSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open: int


class RequestDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    status: RequestStatus
    page_path: str | None
    created_at: dt.datetime
    updated_at: dt.datetime
    author_name: str
    messages: list[RequestMessageRead]


# Descriptive aliases keep the public schema names easy to discover for callers
# that use the domain's full "user request" terminology.
UserRequestCreate = RequestCreate
UserRequestMessageCreate = RequestMessageCreate
UserRequestStatusUpdate = RequestStatusUpdate
UserRequestMessageRead = RequestMessageRead
UserRequestListItem = RequestListItem
UserRequestListResponse = RequestListResponse
UserRequestSummary = RequestSummary
UserRequestRead = RequestDetail
