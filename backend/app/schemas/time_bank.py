from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt


CalculationMode = Literal["standard", "saturday", "manual"]
AdjustmentKind = Literal["correction", "consumption"]


class TimeBankPersonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    is_active: bool


class EntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: uuid.UUID
    work_date: dt.date
    start_minute: StrictInt | None = Field(default=None, ge=0, le=1439)
    end_minute: StrictInt | None = Field(default=None, ge=0, le=1440)
    lunch_taken: StrictBool | None = None
    calculation_mode: CalculationMode
    manual_balance_seconds: StrictInt | None = None
    reason: str | None = Field(default=None, max_length=2000)


class EntryReverse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)


class EntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    person_id: uuid.UUID
    work_date: dt.date
    start_minute: int | None
    end_minute: int | None
    lunch_taken: bool | None
    balance_seconds: int
    calculated_seconds: int | None
    calculation_mode: str
    reason: str | None
    needs_review: bool
    review_flags: dict
    provenance: dict
    source_key: str | None
    created_by_user_id: uuid.UUID
    occurred_at: dt.datetime
    reversal_of_id: uuid.UUID | None


class EntryPage(BaseModel):
    items: list[EntryRead]
    total: int


class AdjustmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: uuid.UUID
    effective_date: dt.date
    delta_seconds: StrictInt
    kind: AdjustmentKind
    reason: str = Field(min_length=1, max_length=2000)


class AdjustmentReverse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)


class AdjustmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    person_id: uuid.UUID
    effective_date: dt.date
    delta_seconds: int
    kind: str
    reason: str
    provenance: dict
    source_key: str | None
    created_by_user_id: uuid.UUID
    occurred_at: dt.datetime
    reversal_of_id: uuid.UUID | None


class AdjustmentPage(BaseModel):
    items: list[AdjustmentRead]
    total: int


class SummaryWarning(BaseModel):
    code: str
    message: str


class TimeBankSummaryPerson(BaseModel):
    person_id: uuid.UUID
    display_name: str
    opening_seconds: int
    credited_seconds: int
    debited_seconds: int
    balance_seconds: int
    period_seconds: int
    needs_review_count: int
    warnings: list[SummaryWarning]


class TimeBankSummary(BaseModel):
    people: list[TimeBankSummaryPerson]


class ImportCandidate(BaseModel):
    id: uuid.UUID
    display_name: str


class ImportPersonRead(BaseModel):
    source_label: str
    person_id: uuid.UUID | None
    candidates: list[ImportCandidate]


class ImportIssue(BaseModel):
    code: str
    message: str
    blocking: bool
    sheet: str | None = None
    row: int | None = None


class ImportCounts(BaseModel):
    entries: int
    openings: int
    needs_review: int
    source_rows: int | None = None
    quarantined: int | None = None


class AppliedCounts(BaseModel):
    entries: int
    openings: int


class ImportRead(BaseModel):
    id: uuid.UUID
    status: Literal["pending", "applied"]
    sha256: str
    source_year: int | None
    counts: ImportCounts
    people: list[ImportPersonRead]
    issues: list[ImportIssue]
    applied_counts: AppliedCounts | None = None


class ImportResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_mapping: dict[str, uuid.UUID]
