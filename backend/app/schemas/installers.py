"""Schemas de instaladores, equipas e do plano de obra (D-071)."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from app.schemas.suppliers import _validate_phone


def _blank_to_none(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


OptionalText = Annotated[str | None, BeforeValidator(_blank_to_none)]


class InstallerTeamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    leader_name: str | None
    leader_phone: str | None
    is_active: bool
    # Obras ativas atribuídas a esta equipa.
    project_count: int = 0


class InstallerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    is_active: bool
    teams: list[InstallerTeamRead] = []
    # Obras ativas atribuídas a este instalador (com ou sem equipa).
    project_count: int = 0


class InstallerAccessTeamRead(BaseModel):
    """Minimal team catalog for the scoped external channel."""

    id: uuid.UUID
    installer_id: uuid.UUID
    name: str
    is_active: bool


class InstallerAccessInstallerRead(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
    teams: list[InstallerAccessTeamRead] = []


class InstallerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=256)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("O nome é obrigatório.")
        return value


class InstallerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=256)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("O nome não pode ficar vazio.")
        return value


class TeamBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leader_name: OptionalText = Field(default=None, max_length=256)
    leader_phone: OptionalText = None

    @field_validator("leader_phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        return _validate_phone(value)


class TeamCreate(TeamBase):
    name: str = Field(min_length=1, max_length=128)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("O nome é obrigatório.")
        return value


class TeamUpdate(TeamBase):
    name: str | None = Field(default=None, max_length=128)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("O nome não pode ficar vazio.")
        return value




class TeamAssignmentCreate(BaseModel):
    """Cria uma afectação de uma equipa à janela indicada."""

    model_config = ConfigDict(extra="forbid")

    team_id: uuid.UUID
    start_date: dt.date
    end_date: dt.date
    note: str = Field(default="", max_length=4000)

class TeamAssignmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: uuid.UUID | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    note: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="before")
    @classmethod
    def _required_fields_not_null(cls, value: object) -> object:
        if isinstance(value, dict):
            invalid = sorted(
                field for field in ("team_id", "start_date", "end_date") if field in value and value[field] is None
            )
            if invalid:
                raise ValueError(f"Os campos {', '.join(invalid)} não podem ser nulos.")
        return value

    @model_validator(mode="after")
    def _at_least_one(self) -> "TeamAssignmentUpdate":
        if not self.model_fields_set:
            raise ValueError("Indique pelo menos um campo a alterar.")
        return self

class TeamAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    installer_id: uuid.UUID
    team_id: uuid.UUID
    start_date: dt.date
    end_date: dt.date
    note: str
    created_by_person_id: uuid.UUID | None
    team_name: str | None = None
    installer_name: str | None = None
    team_leader_name: str | None = None
    team_leader_phone: str | None = None
    warning: str | None = None


class TeamLocationAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    address: str | None
    lat: float | None
    lon: float | None
    pm_person_id: uuid.UUID | None
    pm_display_name: str | None
    lifecycle_status: str | None
    start_date: dt.date
    end_date: dt.date
    note: str
    conflict: bool = False


class TeamLocationTeamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    installer_id: uuid.UUID
    name: str
    assignments: list[TeamLocationAssignmentRead] = []
    # livre | ocupada | ocupada_noutra_obra. `free` mantém a forma anterior.
    status: str = "livre"
    free: bool = True


class TeamLocationInstallerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    teams: list[TeamLocationTeamRead] = []


class TeamsViewRead(BaseModel):
    date: dt.date
    days: int
    installers: list[TeamLocationInstallerRead] = []


class WorkPlanUpdate(BaseModel):
    """Só os campos presentes são alterados; `null` limpa. Ver
    `app/services/installers.py:update_work_plan` para as regras."""

    model_config = ConfigDict(extra="forbid")

    installer_id: uuid.UUID | None = None
    installer_team_id: uuid.UUID | None = None
    work_start_date: dt.date | None = None
    work_end_date: dt.date | None = None
    # Só se pode enviar `false`: confirma as datas atuais (estimadas) sem as alterar.
    work_dates_estimated: Literal[False] = False

    @model_validator(mode="after")
    def _at_least_one(self) -> "WorkPlanUpdate":
        if not self.model_fields_set:
            raise ValueError("Indique pelo menos um campo a alterar.")
        return self
