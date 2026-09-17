"""Schemas do percurso de obra (D-052) — espelham
`app/services/workflow.py`."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict


class WorkflowSubtaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    title: str
    is_client_contact: bool
    done: bool
    done_at: dt.datetime | None


class WorkflowStageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    number: int
    title: str
    phase_code: str
    responsible_label: str
    responsible_role_code: str | None
    note: str
    depends_on_number: int | None
    start_day: int | None
    end_day: int | None
    planned_start: dt.date | None
    planned_end: dt.date | None
    status: str  # concluida | em_curso | atrasada | a_aguardar | por_iniciar
    done_count: int
    total_count: int
    subtasks: list[WorkflowSubtaskRead]
    contact_type: str | None  # contacto | update | None
    contact_note: str
    contact_date: dt.date | None
    contact_done: bool
    contact_overdue: bool


class WorkflowPhaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    color: str
    done_count: int
    total_count: int


class ProjectWorkflowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: uuid.UUID
    start_date: dt.date | None
    planned_end: dt.date | None
    total_days: int
    progress_percent: int
    done_count: int
    total_count: int
    current_stage_number: int | None
    current_phase_code: str | None
    overdue_stages_count: int
    pending_contacts_count: int
    can_edit: bool
    phases: list[WorkflowPhaseRead]
    stages: list[WorkflowStageRead]


class WorkflowDoneUpdate(BaseModel):
    done: bool
