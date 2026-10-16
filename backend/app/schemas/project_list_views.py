"""Strict HTTP schemas for personal Projects-list configuration."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator, model_validator

from app.services.project_lifecycle import LIFECYCLE_STATUS_CODES

PROJECT_LIST_COLUMNS: tuple[str, ...] = (
    "project",
    "pm",
    "lifecycle",
    "progress",
    "next_task",
    "overdue",
    "warnings",
    "installer",
    "start_date",
    "power_kwp",
)
PROJECT_LIST_DEFAULT_COLUMNS: tuple[str, ...] = PROJECT_LIST_COLUMNS[:7]
PROJECT_LIST_SORT_FIELDS = frozenset({"name", "start_date", "power_kwp", "created_at"})
PROJECT_LIST_SORT_DIRECTIONS = frozenset({"asc", "desc"})
PROJECT_LIST_STATUSES = frozenset({"", "nao_iniciado", "em_curso", "concluido"})
PROJECT_LIST_ACTIVE_FILTERS = frozenset({"active", "inactive", "all"})
PROJECT_LIST_MAX_SEARCH_LENGTH = 200
PROJECT_LIST_MAX_COLUMNS = len(PROJECT_LIST_COLUMNS)
PROJECT_LIST_MAX_LIFECYCLE = len(LIFECYCLE_STATUS_CODES)


class ProjectListFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search: StrictStr = Field(..., max_length=PROJECT_LIST_MAX_SEARCH_LENGTH)
    status: StrictStr
    lifecycle: list[StrictStr] = Field(..., max_length=PROJECT_LIST_MAX_LIFECYCLE)
    pm: StrictStr
    active: StrictStr
    startFrom: StrictStr
    startTo: StrictStr

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in PROJECT_LIST_STATUSES:
            raise ValueError("Filtro de status inválido.")
        return value

    @field_validator("lifecycle")
    @classmethod
    def validate_lifecycle(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("O filtro lifecycle não pode conter valores repetidos.")
        if any(value not in LIFECYCLE_STATUS_CODES for value in values):
            raise ValueError("Filtro de lifecycle inválido.")
        return values

    @field_validator("pm")
    @classmethod
    def validate_pm_shape(cls, value: str) -> str:
        if value:
            try:
                uuid.UUID(value)
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValueError("Filtro pm inválido.") from exc
        return value

    @field_validator("active")
    @classmethod
    def validate_active(cls, value: str) -> str:
        if value not in PROJECT_LIST_ACTIVE_FILTERS:
            raise ValueError("Filtro active inválido.")
        return value

    @field_validator("startFrom", "startTo")
    @classmethod
    def validate_date_shape(cls, value: str) -> str:
        if value:
            try:
                parsed = dt.date.fromisoformat(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("As datas dos filtros têm de usar YYYY-MM-DD.") from exc
            if parsed.isoformat() != value:
                raise ValueError("As datas dos filtros têm de usar YYYY-MM-DD.")
        return value

    @model_validator(mode="after")
    def validate_date_range(self) -> "ProjectListFilters":
        if self.startFrom and self.startTo and self.startFrom > self.startTo:
            raise ValueError("O intervalo de datas dos filtros é inválido.")
        return self


class ProjectListConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[StrictStr] = Field(..., min_length=1, max_length=PROJECT_LIST_MAX_COLUMNS)
    sort_by: StrictStr
    sort_direction: StrictStr
    filters: ProjectListFilters

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("A lista de colunas não pode conter valores repetidos.")
        if any(value not in PROJECT_LIST_COLUMNS for value in values):
            raise ValueError("A lista de colunas contém um valor desconhecido.")
        if values[0] != "project":
            raise ValueError("A coluna project tem de ser a primeira.")
        return values

    @field_validator("sort_by")
    @classmethod
    def validate_sort_by(cls, value: str) -> str:
        if value not in PROJECT_LIST_SORT_FIELDS:
            raise ValueError("Campo de ordenação inválido.")
        return value

    @field_validator("sort_direction")
    @classmethod
    def validate_sort_direction(cls, value: str) -> str:
        if value not in PROJECT_LIST_SORT_DIRECTIONS:
            raise ValueError("Direção de ordenação inválida.")
        return value


class ProjectListPreferencePut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: ProjectListConfig


class ProjectListPreferenceRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: ProjectListConfig


class ProjectListViewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr
    config: ProjectListConfig


class ProjectListViewPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr | None = None
    config: ProjectListConfig | None = None


class ProjectListViewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    config: ProjectListConfig
    created_at: dt.datetime
    updated_at: dt.datetime
