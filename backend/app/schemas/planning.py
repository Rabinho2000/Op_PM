from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


PlanningView = Literal["month", "week", "list"]
CalendarEventCategory = Literal[
    "meeting",
    "technical_visit",
    "commissioning",
    "final_inspection",
    "pending",
    "work",
    "other",
]
UTC = dt.timezone.utc


def ensure_calendar_instant(value: dt.datetime) -> dt.datetime:
    """Return an instant with an explicit offset without changing aware values.

    SQLite drops the offset from ``DateTime(timezone=True)`` columns. Existing
    rows are stored as UTC wall-clock values, so a naive value loaded from the
    calendar is interpreted as UTC at the API boundary. This policy is scoped
    to calendar instants; Process date-only projections keep their Lisbon
    ``ZoneInfo`` values.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value


def normalize_calendar_instant(value: dt.datetime) -> dt.datetime:
    """Normalize a calendar instant to UTC before persistence/comparison.

    Naive API datetimes remain accepted for backwards compatibility and mean
    UTC explicitly. Browser wall-clock inputs must send an offset (the
    frontend sends UTC after resolving Europe/Lisbon).
    """
    return ensure_calendar_instant(value).astimezone(UTC)


class CalendarEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    visit_id: uuid.UUID | None
    project_id: uuid.UUID | None
    task_id: uuid.UUID | None
    assigned_to_person_id: uuid.UUID | None
    assigned_to_person_ids: list[uuid.UUID] = Field(default_factory=list)
    title: str
    category: str = "other"
    starts_at: dt.datetime
    ends_at: dt.datetime
    status: str
    graph_event_id: str | None
    created_at: dt.datetime

    project_name: str | None = None
    project_url: str | None = None
    task_title: str | None = None
    assigned_to_display_name: str | None = None
    assigned_to_display_names: list[str] = Field(default_factory=list)
    process_stage_id: uuid.UUID | None = None
    process_stage_code: str | None = None
    process_stage_title: str | None = None
    process_subtask_id: uuid.UUID | None = None
    process_subtask_code: str | None = None
    process_subtask_title: str | None = None
    responsible_person_ids: list[uuid.UUID] = Field(default_factory=list)
    responsible_display_names: list[str] = Field(default_factory=list)
    source: Literal["manual", "process"] = "manual"
    source_id: uuid.UUID | None = None
    category_label: str | None = None
    category_color: str | None = None
    can_manage: bool = False

    @field_validator("starts_at", "ends_at")
    @classmethod
    def datetimes_are_explicitly_aware(cls, value: dt.datetime) -> dt.datetime:
        return ensure_calendar_instant(value)


class CalendarEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    starts_at: dt.datetime
    ends_at: dt.datetime
    project_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    assigned_to_person_id: uuid.UUID | None = None
    assigned_to_person_ids: list[uuid.UUID] | None = None
    category: CalendarEventCategory = "other"
    process_stage_id: uuid.UUID | None = None
    process_subtask_id: uuid.UUID | None = None

    @field_validator("assigned_to_person_ids")
    @classmethod
    def assigned_ids_must_not_be_null(cls, value: list[uuid.UUID] | None) -> list[uuid.UUID]:
        if value is None:
            raise ValueError("assigned_to_person_ids omitido preserva; use [] para limpar.")
        return value

    @field_validator("starts_at", "ends_at")
    @classmethod
    def normalize_input_instants(cls, value: dt.datetime) -> dt.datetime:
        return normalize_calendar_instant(value)


class CalendarEventUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    starts_at: dt.datetime | None = None
    ends_at: dt.datetime | None = None
    project_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    assigned_to_person_id: uuid.UUID | None = None
    assigned_to_person_ids: list[uuid.UUID] | None = None
    category: CalendarEventCategory | None = None
    process_stage_id: uuid.UUID | None = None
    process_subtask_id: uuid.UUID | None = None
    status: str | None = None

    @field_validator("assigned_to_person_ids")
    @classmethod
    def assigned_ids_must_not_be_null(cls, value: list[uuid.UUID] | None) -> list[uuid.UUID]:
        if value is None:
            raise ValueError("assigned_to_person_ids omitido preserva; use [] para limpar.")
        return value

    @field_validator("starts_at", "ends_at")
    @classmethod
    def normalize_input_instants(cls, value: dt.datetime | None) -> dt.datetime | None:
        return normalize_calendar_instant(value) if value is not None else None


class CalendarEventCategoryRead(BaseModel):
    code: str
    label: str
    color: str


class PlanningPreferenceRead(BaseModel):
    view: PlanningView
    hide_weekends: bool


class PlanningPreferencePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    view: PlanningView | None = None
    hide_weekends: bool | None = None


class PlanningProcessOptionRead(BaseModel):
    project_id: uuid.UUID
    stage_id: uuid.UUID
    stage_code: str
    stage_title: str
    planned_start: dt.date | None
    planned_end: dt.date | None
    responsible_person_ids: list[uuid.UUID] = Field(default_factory=list)
    responsible_display_names: list[str] = Field(default_factory=list)
    subtasks: list["PlanningProcessSubtaskOptionRead"] = Field(default_factory=list)


class PlanningProcessSubtaskOptionRead(BaseModel):
    id: uuid.UUID
    code: str
    title: str
    # Processo não atribui datas às subtarefas nesta projeção.
    planned_start: None = None
    planned_end: None = None
