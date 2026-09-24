"""Schemas do processo de um projeto (D-073)."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict


class ProcessSubtaskRead(BaseModel):
    id: uuid.UUID
    code: str
    title: str
    done: bool
    done_at: dt.datetime | None = None
    done_by_display_name: str | None = None


class ProcessResponsibleRead(BaseModel):
    """Quem faz a etapa **neste projeto** (regra resolvida)."""

    rule: str | None
    # Texto genérico da regra ("PM do projeto", "Subempreiteiro", …).
    label: str
    names: list[str]
    # A regra precisa de um dado que este projeto ainda não tem (PM, instalador, chefe de equipa).
    unresolved: bool
    # Só em `support_delegate`: true se há uma pessoa de suporte delegada para o PM.
    delegated: bool = False


class ProcessContactRead(BaseModel):
    day: int
    kind: str
    note: str
    planned_date: dt.date | None
    done: bool
    done_at: dt.datetime | None = None
    overdue: bool


class ProcessStageRead(BaseModel):
    id: uuid.UUID
    code: str
    title: str
    note: str
    responsible: ProcessResponsibleRead
    depends_on_code: str | None
    start_day: int | None
    end_day: int | None
    planned_start: dt.date | None
    planned_end: dt.date | None
    # done | overdue | active | upcoming | no_date
    status: str
    done_count: int
    total_count: int
    contact: ProcessContactRead | None
    subtasks: list[ProcessSubtaskRead]


class ProcessPhaseRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    color: str
    done_count: int
    total_count: int
    stages: list[ProcessStageRead]


class ProcessSummary(BaseModel):
    done: int
    total: int
    percent: int
    stages_done: int
    stages_total: int
    overdue_stages: int
    overdue_contacts: int


class ProcessRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: uuid.UUID
    start_date: dt.date | None
    # Falso se o catálogo do processo ainda não foi carregado.
    has_catalog: bool
    # Pode o utilizador atual marcar o progresso deste projeto?
    can_update: bool
    phases: list[ProcessPhaseRead]
    summary: ProcessSummary


class SubtaskProgressUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    done: bool


class ContactProgressUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    done: bool
