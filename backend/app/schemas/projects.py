"""Schemas Pydantic para os endpoints de projeto. Campos editáveis via API
(`ProjectUpdate`) excluem de propósito `clickup_status_mirror` — fonte de
verdade ClickUp, nunca editado pela UI (ver ARCHITECTURE_PROPOSAL.md
secção 5) — e qualquer coisa que só a migração em staging deva escrever.
"""
from __future__ import annotations

import datetime as dt
import math
import uuid
from typing import Annotated

from fastapi import HTTPException
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from app.services.project_lifecycle import LIFECYCLE_STATUS_CODES, ON_HOLD


class ProjectEligibleManagerRead(BaseModel):
    id: uuid.UUID
    display_name: str


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    client_name: str | None
    client_contact: str | None
    client_email: str | None
    address: str | None
    lat: float | None
    lon: float | None
    power_kwp: float | None
    power_raw: str | None
    pm_person_id: uuid.UUID | None
    start_date: dt.date | None
    lifecycle_status: str | None
    # Obra (D-071)
    installer_id: uuid.UUID | None
    installer_team_id: uuid.UUID | None
    work_start_date: dt.date | None
    work_end_date: dt.date | None
    work_dates_estimated: bool
    clickup_status_mirror: str | None
    role: str | None
    equipment_notes: str | None
    injection_notes: str | None
    om_notes: str | None
    commercial_assumptions: str | None
    upac_registration: str | None
    m2m_card: str | None
    upac_connection_date_raw: str | None
    award_year_raw: str | None
    is_active: bool
    deleted_at: dt.datetime | None = None
    deleted_by_person_id: uuid.UUID | None = None
    entered_at: dt.datetime | None = None
    notes: str
    created_at: dt.datetime
    updated_at: dt.datetime

    # Derivados — úteis para a lista/filtros no frontend sem um pedido extra.
    pm_display_name: str | None = None
    has_pm: bool = False
    has_email: bool = False
    has_coordinates: bool = False
    has_contact: bool = False

    # Derivados das tarefas e do estado do ciclo de vida final (ver
    # app/services/projects.py:compute_project_task_summary).
    # — nao_iniciado | em_curso | concluido; o estado final do ciclo de vida
    # pode classificar o projeto como concluído sem alterar os restantes campos.
    status: str = "nao_iniciado"
    next_task_title: str | None = None
    next_task_due_date: dt.date | None = None
    overdue_tasks_count: int = 0
    workflow_progress_percent: int = 0
    photos_pending_warning: bool = False
    can_delete: bool = False
    can_restore: bool = False

    # Permissões efetivas do utilizador atual sobre ESTE projeto (D-051) —
    # só para a UI decidir o que mostrar; o servidor continua a validar
    # cada escrita (app/services/projects.py, app/services/tasks.py).
    editable_fields: list[str] = []
    can_manage_tasks: bool = False
    can_change_status: bool = False
    can_plan_work: bool = False
    has_project_photo: bool = False
    can_edit_project_photo: bool = False
    # Licenciamento (D-105): permissões efetivas — permissão + âmbito do projeto, calculadas
    # no servidor. O frontend não deduz estas flags de /api/me nem de editable_fields.
    can_edit_credentials: bool = False
    can_reveal_credentials: bool = False
    can_edit_sim_cards: bool = False
    can_reveal_sim_secrets: bool = False
    can_edit_surplus_contracts: bool = False
    payments: dict[str, bool] | None = None
    can_edit_payments: bool = False
    installer_name: str | None = None
    installer_team_name: str | None = None
    installer_team_leader_name: str | None = None


def _reject_non_finite_json_numbers(value: object) -> object:
    # FastAPI serializes Pydantic's ``input`` in normal validation errors.
    # For raw JSON Infinity/NaN (including 1e999), that both leaks the
    # value and makes JSONResponse fail. Return a fixed, sanitized 422.
    if isinstance(value, float) and not math.isfinite(value):
        raise HTTPException(status_code=422, detail="Valor numérico inválido.")
    return value


# Limites partilhados por `ProjectCreate` e `ProjectUpdate` (espelham o
# tamanho das colunas de `Project`): uma só definição, para a edição nunca
# aceitar o que a criação rejeita (M5).
ProjectName = Annotated[str, Field(min_length=1, max_length=512)]
Latitude = Annotated[float, BeforeValidator(_reject_non_finite_json_numbers), Field(ge=-90, le=90, allow_inf_nan=False)]
Longitude = Annotated[float, BeforeValidator(_reject_non_finite_json_numbers), Field(ge=-180, le=180, allow_inf_nan=False)]
PowerKwp = Annotated[float, BeforeValidator(_reject_non_finite_json_numbers), Field(ge=0, allow_inf_nan=False)]
ClientName = Annotated[str, Field(max_length=256)]
ClientContact = Annotated[str, Field(max_length=256)]
ClientEmail = Annotated[str, Field(max_length=320)]
Address = Annotated[str, Field(max_length=512)]
PowerRaw = Annotated[str, Field(max_length=64)]
ProjectRole = Annotated[str, Field(max_length=128)]
LongNote = Annotated[str, Field(max_length=20_000)]
AwardYearRaw = Annotated[str, Field(max_length=16)]
UpacRegistration = Annotated[str, Field(max_length=128)]
M2mCard = Annotated[str, Field(max_length=128)]
UpacConnectionDateRaw = Annotated[str, Field(max_length=64)]


class ProjectUpdate(BaseModel):
    """Todos os campos opcionais — só os presentes no pedido são
    alterados. `None` explícito limpa o campo (distinto de omitido); ver
    `app/services/projects.py:update_project`, que usa
    `model_dump(exclude_unset=True)` para essa distinção.

    Excepção: `name`, `notes` e `is_active` são NOT NULL na BD, por isso um
    `null` explícito é rejeitado com 422 (antes dava 500 por violação de
    NOT NULL). Os limites são os de `ProjectCreate`."""

    model_config = ConfigDict(extra="forbid")

    name: ProjectName | None = None
    client_name: ClientName | None = None
    client_contact: ClientContact | None = None
    client_email: ClientEmail | None = None
    address: Address | None = None
    lat: Latitude | None = None
    lon: Longitude | None = None
    power_kwp: PowerKwp | None = None
    power_raw: PowerRaw | None = None
    pm_person_id: uuid.UUID | None = None
    start_date: dt.date | None = None
    role: ProjectRole | None = None
    equipment_notes: LongNote | None = None
    injection_notes: LongNote | None = None
    om_notes: LongNote | None = None
    commercial_assumptions: LongNote | None = None
    upac_registration: UpacRegistration | None = None
    m2m_card: M2mCard | None = None
    upac_connection_date_raw: UpacConnectionDateRaw | None = None
    award_year_raw: AwardYearRaw | None = None
    notes: LongNote | None = None
    is_active: bool | None = None

    @field_validator("name", "notes", "is_active", mode="before")
    @classmethod
    def reject_null_for_required_fields(cls, value: object) -> object:
        # Só corre para campos presentes no pedido (os omitidos ficam como
        # estão): `null` explícito num campo NOT NULL é um 422, não um 500.
        if value is None:
            raise ValueError("Este campo é obrigatório e não pode ser nulo.")
        return value

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ProjectCreate(BaseModel):
    """Campos permitidos na criação pela UI. Campos de estado interno e
    controlo de remoção são definidos exclusivamente pelo serviço."""

    model_config = ConfigDict(extra="forbid")

    name: ProjectName
    client_name: ClientName | None = None
    client_contact: ClientContact | None = None
    client_email: ClientEmail | None = None
    address: Address | None = None
    lat: Latitude | None = None
    lon: Longitude | None = None
    power_kwp: PowerKwp | None = None
    power_raw: PowerRaw | None = None
    pm_person_id: uuid.UUID | None = None
    start_date: dt.date | None = None
    role: ProjectRole | None = None
    equipment_notes: LongNote | None = None
    injection_notes: LongNote | None = None
    om_notes: LongNote | None = None
    commercial_assumptions: LongNote | None = None
    award_year_raw: AwardYearRaw | None = None
    notes: LongNote | None = None
    lifecycle_status: str | None = Field(default=ON_HOLD, max_length=32)

    @field_validator("name", mode="before")
    @classmethod
    def strip_and_require_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("lifecycle_status")
    @classmethod
    def validate_lifecycle_status(cls, value: str | None) -> str | None:
        if value is not None and value not in LIFECYCLE_STATUS_CODES:
            raise ValueError(f"Estado de projeto inválido: {value!r}")
        return value


class ProjectNameCandidate(BaseModel):
    id: uuid.UUID
    name: str


class ProjectHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    field_name: str
    old_value: str | None
    new_value: str | None
    changed_by_person_id: uuid.UUID | None
    changed_by_person_name: str | None = None
    source: str
    note: str
    related_staging_record_id: uuid.UUID | None
    changed_at: dt.datetime


class ProjectDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Indique o motivo da remoção.")
        return normalized


class LifecycleStatusRead(BaseModel):
    code: str
    label: str
    # Sequência normal (1..5); `null` para "On hold pelo cliente", que não faz
    # parte dela.
    flow_position: int | None = None


class ProjectStatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lifecycle_status: str
    note: str = ""


class ProjectStatusChangeResult(BaseModel):
    project: ProjectRead
    # Aviso (nunca bloqueio) quando a mudança salta estados da sequência normal.
    warning: str | None = None
