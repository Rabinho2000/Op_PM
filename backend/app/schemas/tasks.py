from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    task_type: str
    description: str
    status: str
    priority: str
    assigned_to_person_id: uuid.UUID | None
    due_date: dt.date | None
    completed_at: dt.datetime | None
    notes: str
    created_by_person_id: uuid.UUID | None
    created_at: dt.datetime
    updated_at: dt.datetime

    # Derivados — evitam um pedido extra no frontend para listagens/filtros.
    project_name: str | None = None
    assigned_to_display_name: str | None = None
    is_overdue: bool = False


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: uuid.UUID
    title: str
    task_type: str = "custom"
    description: str = ""
    priority: str = "medium"
    assigned_to_person_id: uuid.UUID | None = None
    due_date: dt.date | None = None
    notes: str = ""


class TaskUpdate(BaseModel):
    """Todos os campos opcionais — só os presentes no pedido são alterados
    (mesma convenção de `ProjectUpdate` — ver app/schemas/projects.py).
    `completed_at` nunca é editável diretamente: é derivado da transição
    de `status` para/de 'done' (ver app/services/tasks.py)."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    assigned_to_person_id: uuid.UUID | None = None
    due_date: dt.date | None = None
    notes: str | None = None


class TaskHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    field_name: str
    old_value: str | None
    new_value: str | None
    changed_by_person_id: uuid.UUID | None
    changed_by_person_name: str | None = None
    source: str
    note: str
    changed_at: dt.datetime
