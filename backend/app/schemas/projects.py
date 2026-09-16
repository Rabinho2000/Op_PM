"""Schemas Pydantic para os endpoints de projeto. Campos editáveis via API
(`ProjectUpdate`) excluem de propósito `clickup_status_mirror` — fonte de
verdade ClickUp, nunca editado pela UI (ver ARCHITECTURE_PROPOSAL.md
secção 5) — e qualquer coisa que só a migração em staging deva escrever.
"""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict


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
    notes: str
    created_at: dt.datetime
    updated_at: dt.datetime

    # Derivados — úteis para a lista/filtros no frontend sem um pedido extra.
    pm_display_name: str | None = None
    has_pm: bool = False
    has_email: bool = False
    has_coordinates: bool = False
    has_contact: bool = False

    # Derivados de tarefas (ver app/services/projects.py:compute_project_task_summary)
    # — nao_iniciado | em_curso | concluido, calculado a partir das tarefas
    # reais, nunca hardcoded.
    status: str = "nao_iniciado"
    next_task_title: str | None = None
    next_task_due_date: dt.date | None = None
    overdue_tasks_count: int = 0
    workflow_progress_percent: int = 0
    photos_pending_warning: bool = False

    # Permissões efetivas do utilizador atual sobre ESTE projeto (D-051) —
    # só para a UI decidir o que mostrar; o servidor continua a validar
    # cada escrita (app/services/projects.py, app/services/tasks.py).
    editable_fields: list[str] = []
    can_manage_tasks: bool = False


class ProjectUpdate(BaseModel):
    """Todos os campos opcionais — só os presentes no pedido são
    alterados. `None` explícito limpa o campo (distinto de omitido); ver
    `app/services/projects.py:update_project`, que usa
    `model_dump(exclude_unset=True)` para essa distinção."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    client_name: str | None = None
    client_contact: str | None = None
    client_email: str | None = None
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    power_kwp: float | None = None
    power_raw: str | None = None
    pm_person_id: uuid.UUID | None = None
    start_date: dt.date | None = None
    role: str | None = None
    equipment_notes: str | None = None
    injection_notes: str | None = None
    om_notes: str | None = None
    commercial_assumptions: str | None = None
    upac_registration: str | None = None
    m2m_card: str | None = None
    upac_connection_date_raw: str | None = None
    award_year_raw: str | None = None
    notes: str | None = None
    is_active: bool | None = None


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
