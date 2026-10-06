from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class AbsenceOverlapRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    start_date: dt.date
    end_date: dt.date
    type: str
    status: str


class WorkOverlapRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    lifecycle_status: str | None
    work_start_date: dt.date
    work_end_date: dt.date


class AbsenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    person_id: uuid.UUID
    start_date: dt.date
    end_date: dt.date
    type: str
    note: str
    status: str
    created_by_person_id: uuid.UUID | None
    decided_by_person_id: uuid.UUID | None
    decided_at: dt.datetime | None
    decision_note: str
    cancelled_by_person_id: uuid.UUID | None
    cancelled_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime

    person_display_name: str | None = None
    decided_by_display_name: str | None = None
    cancelled_by_display_name: str | None = None
    # Informação contextual para quem aprova. É calculada em bloco no serviço;
    # para os restantes perfis fica vazia, sem alargar a informação exposta.
    overlapping_absences: list[AbsenceOverlapRead] = Field(default_factory=list)
    overlapping_absences_count: int = 0
    overlapping_projects: list[WorkOverlapRead] = Field(default_factory=list)
    overlapping_projects_count: int = 0
    # Permissões efetivas do utilizador atual (D-051) — só para a UI.
    can_approve: bool = False
    can_reject: bool = False
    can_cancel: bool = False


class AbsenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: uuid.UUID
    start_date: dt.date
    end_date: dt.date
    type: str = "ferias"
    note: str = ""


class AbsenceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=1)


class AbsenceUpdate(BaseModel):
    """Só a nota é editável depois de criada.

    Alterar datas/pessoa/tipo exige cancelar e criar de novo; as transições de
    estado têm endpoints explícitos para não permitir auto-aprovação por PATCH.
    """

    model_config = ConfigDict(extra="forbid")

    note: str | None = None
