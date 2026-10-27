from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RoofType = Literal[
    "telha_ceramica",
    "chapa_sandwich",
    "chapa_simples_fibrocimento",
    "laje_terraco",
    "solo",
    "outro",
]
AccessMethod = Literal["escada", "andaime", "plataforma_elevatoria", "outro"]
Risk = Literal[
    "queda_altura",
    "eletrico_dc_ac",
    "fragil_claraboias",
    "condicoes_meteorologicas",
    "outro",
]
SafetyMeasure = Literal[
    "linha_vida",
    "arnes",
    "capacete",
    "luvas_dieleticas",
    "calcado",
    "guarda_corpos",
    "outro",
]


class SafetySheetWorkerInput(BaseModel):
    person_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=256)
    installer_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("O nome do trabalhador é obrigatório.")
        return value


class SafetySheetUpdate(BaseModel):
    expected_version: int = Field(ge=0)
    roof_type: RoofType | None = None
    roof_other: str | None = Field(default=None, max_length=2000)
    approximate_height_m: float | None = Field(default=None, ge=0, le=1000)
    access_method: AccessMethod | None = None
    access_other: str | None = Field(default=None, max_length=2000)
    risks: list[Risk] = Field(default_factory=list, max_length=5)
    risk_other: str | None = Field(default=None, max_length=2000)
    safety_measures: list[SafetyMeasure] = Field(default_factory=list, max_length=7)
    measure_other: str | None = Field(default=None, max_length=2000)
    workers: list[SafetySheetWorkerInput] = Field(default_factory=list, max_length=100)
    safety_responsible: str | None = Field(default=None, max_length=256)
    emergency_contacts: str | None = Field(default=None, max_length=4000)
    observations: str | None = Field(default=None, max_length=10000)
    work_start_date: dt.date | None = None
    work_end_date: dt.date | None = None

    @field_validator("risks", "safety_measures")
    @classmethod
    def checklist_values_must_be_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("A checklist não pode conter opções repetidas.")
        return values

    @model_validator(mode="after")
    def dates_must_be_ordered(self):
        if (
            self.work_start_date is not None
            and self.work_end_date is not None
            and self.work_end_date < self.work_start_date
        ):
            raise ValueError("A data de fim não pode ser anterior à data de início.")
        return self


class SafetySheetWorkerRead(BaseModel):
    person_id: uuid.UUID | None = None
    name: str
    installer_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None


class SafetySheetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: uuid.UUID
    version: int = 0
    roof_type: RoofType | None = None
    roof_other: str | None = None
    approximate_height_m: float | None = None
    access_method: AccessMethod | None = None
    access_other: str | None = None
    risks: list[Risk] = Field(default_factory=list)
    risk_other: str | None = None
    safety_measures: list[SafetyMeasure] = Field(default_factory=list)
    measure_other: str | None = None
    workers: list[SafetySheetWorkerRead] = Field(default_factory=list)
    safety_responsible: str | None = None
    emergency_contacts: str | None = None
    observations: str | None = None
    work_start_date: dt.date | None = None
    work_end_date: dt.date | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class SafetySheetPrefillRead(BaseModel):
    project_id: uuid.UUID
    workers: list[SafetySheetWorkerRead]


class SafetySheetHistoryRead(BaseModel):
    version: int
    snapshot: SafetySheetRead
    changed_by_person_id: uuid.UUID | None = None
    changed_at: dt.datetime
