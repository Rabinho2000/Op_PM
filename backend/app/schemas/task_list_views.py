"""Personal Task-list preferences and saved-view DTOs."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
)

from app.models.task import TASK_PRIORITIES, TASK_STATUSES

TASK_LIST_COLUMNS: tuple[str, ...] = (
    "task",
    "project",
    "assignee",
    "priority",
    "due_date",
    "status",
    "category",
    "created_at",
)
TASK_LIST_DEFAULT_COLUMNS: tuple[str, ...] = TASK_LIST_COLUMNS[:6]
TASK_LIST_SORT_FIELDS = frozenset(
    {"default", "title", "due_date", "priority", "created_at", "project_name"}
)
TASK_LIST_SORT_DIRECTIONS = frozenset({"asc", "desc"})
TASK_LIST_VIEWS = frozenset({"lista", "kanban"})
TASK_LIST_MAX_COLUMNS = len(TASK_LIST_COLUMNS)
TASK_LIST_EMPTY_OR_STATUSES = frozenset({"", *TASK_STATUSES})
TASK_LIST_EMPTY_OR_PRIORITIES = frozenset({"", *TASK_PRIORITIES})


class TaskListFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: StrictStr
    assigned_to_person_id: StrictStr
    priority: StrictStr
    status: StrictStr
    overdue_only: StrictBool

    @field_validator("project_id", "assigned_to_person_id")
    @classmethod
    def validate_uuid_shape(cls, value: str) -> str:
        if value:
            try:
                uuid.UUID(value)
            except (AttributeError, TypeError, ValueError) as exc:
                raise ValueError("O filtro de referência contém um UUID inválido.") from exc
        return value

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, value: str) -> str:
        if value not in TASK_LIST_EMPTY_OR_PRIORITIES:
            raise ValueError("Filtro de prioridade inválido.")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in TASK_LIST_EMPTY_OR_STATUSES:
            raise ValueError("Filtro de estado inválido.")
        return value


class TaskListConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[StrictStr] = Field(..., min_length=1, max_length=TASK_LIST_MAX_COLUMNS)
    sort_by: StrictStr
    sort_direction: StrictStr
    view: StrictStr
    filters: TaskListFilters

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("A lista de colunas não pode conter valores repetidos.")
        if any(value not in TASK_LIST_COLUMNS for value in values):
            raise ValueError("A lista de colunas contém um valor desconhecido.")
        if values[0] != "task":
            raise ValueError("A coluna task tem de ser a primeira.")
        return values

    @field_validator("sort_by")
    @classmethod
    def validate_sort_by(cls, value: str) -> str:
        if value not in TASK_LIST_SORT_FIELDS:
            raise ValueError("Campo de ordenação inválido.")
        return value

    @field_validator("sort_direction")
    @classmethod
    def validate_sort_direction(cls, value: str) -> str:
        if value not in TASK_LIST_SORT_DIRECTIONS:
            raise ValueError("Direção de ordenação inválida.")
        return value

    @field_validator("view")
    @classmethod
    def validate_view(cls, value: str) -> str:
        if value not in TASK_LIST_VIEWS:
            raise ValueError("Vista inválida.")
        return value


class TaskListPreferencePut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: TaskListConfig


class TaskListPreferenceRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: TaskListConfig


class TaskListViewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr
    config: TaskListConfig


class TaskListViewPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr | None = None
    config: TaskListConfig | None = None


class TaskListViewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    config: TaskListConfig
    created_at: dt.datetime
    updated_at: dt.datetime
