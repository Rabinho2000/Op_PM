from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class GoalPeriodRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    period_type: str
    year: int
    quarter: int | None
    semester: int | None
    month: int | None
    metric: str
    target_value: Decimal
    scope: str
    pm_person_id: uuid.UUID | None
    created_by_person_id: uuid.UUID | None
    notes: str
    created_at: dt.datetime

    pm_display_name: str | None = None
    # Progresso — sempre calculado no backend, nunca no frontend (D-041).
    realized: Decimal = Decimal("0")
    percent: float = 0.0
    missing: Decimal = Decimal("0")
    expected_pace: Decimal = Decimal("0")
    projection: Decimal = Decimal("0")
    pace_status: str = "no_target"


class GoalPeriodCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_type: str
    year: int
    quarter: int | None = None
    semester: int | None = None
    month: int | None = None
    metric: str
    target_value: Decimal
    scope: str = "company"
    pm_person_id: uuid.UUID | None = None
    notes: str = ""


class GoalPeriodUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_value: Decimal | None = None
    notes: str | None = None


class YearlyIndicator(BaseModel):
    year: int
    installations: Decimal
    kwp: Decimal


class PortfolioBreakdownRead(BaseModel):
    not_started: int
    in_progress: int
    completed: int
    kwp_not_started: Decimal
    kwp_in_progress: Decimal
    kwp_completed: Decimal
    certified_count: int
    pending_certification_count: int


class PerformanceSummary(BaseModel):
    goals: list[GoalPeriodRead]
    portfolio: PortfolioBreakdownRead
    yearly: list[YearlyIndicator]
