"""Schemas do calendário de obras (D-072)."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel


class WorkItemRead(BaseModel):
    project_id: uuid.UUID
    name: str
    client_name: str | None
    pm_person_id: uuid.UUID | None
    pm_display_name: str | None
    lifecycle_status: str | None
    installer_id: uuid.UUID | None
    installer_name: str | None
    installer_team_id: uuid.UUID | None
    installer_team_name: str | None
    work_start_date: dt.date
    work_end_date: dt.date
    # Datas derivadas do modelo do processo e ainda não confirmadas.
    work_dates_estimated: bool
    # A mesma equipa tem outra obra sobreposta (só entre preparação e construção).
    conflict: bool


class UnscheduledProjectRead(BaseModel):
    """Projeto ativo a que faltam as datas da obra ("por planear")."""

    project_id: uuid.UUID
    name: str
    pm_display_name: str | None
    lifecycle_status: str | None
    installer_name: str | None
    installer_team_name: str | None
    work_start_date: dt.date | None
    work_end_date: dt.date | None


class WorksSummary(BaseModel):
    works: int
    conflicts: int
    estimated: int
    # Total de projetos por planear (a lista devolvida está limitada).
    unscheduled: int


class WorksCalendarRead(BaseModel):
    start: dt.date
    end: dt.date
    works: list[WorkItemRead]
    unscheduled: list[UnscheduledProjectRead]
    summary: WorksSummary
