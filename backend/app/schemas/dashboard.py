from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel


class ProjectMini(BaseModel):
    id: uuid.UUID
    name: str
    pm_display_name: str | None = None
    start_date: dt.date | None = None
    missing_fields: list[str] = []


class TaskMini(BaseModel):
    id: uuid.UUID
    title: str
    task_type: str
    priority: str
    project_id: uuid.UUID
    project_name: str
    assigned_to_display_name: str | None = None
    due_date: dt.date | None = None


class AbsenceMini(BaseModel):
    id: uuid.UUID
    person_id: uuid.UUID
    person_display_name: str
    start_date: dt.date
    end_date: dt.date
    type: str


class BirthdayMini(BaseModel):
    person_id: uuid.UUID
    person_display_name: str
    birth_date: dt.date
    days_until: int


class WeekDaySummary(BaseModel):
    """Um dia (Europe/Lisbon) da semana corrente — base do "resumo visual
    da semana" no dashboard (D-051). Contagens calculadas no servidor."""

    date: dt.date
    tasks_due_count: int
    tasks_completed_count: int
    people_absent_count: int


class DashboardSummary(BaseModel):
    generated_at: dt.datetime
    scope: str  # all | own | none
    week_start: dt.date
    week_end: dt.date

    active_projects_count: int
    projects_starting_next_30_days: list[ProjectMini]
    overdue_tasks: list[TaskMini]
    tasks_due_this_week: list[TaskMini]
    pending_technical_visits: list[TaskMini]
    pending_commissioning: list[TaskMini]
    projects_without_pm: list[ProjectMini]
    projects_missing_data: list[ProjectMini]
    current_absences: list[AbsenceMini]
    upcoming_absences: list[AbsenceMini]
    upcoming_birthdays: list[BirthdayMini]
    urgent_tasks: list[TaskMini]
    # D-051 — aditivos, com omissão vazia para não partir clientes antigos.
    projects_photos_pending: list[ProjectMini] = []
    week_overview: list[WeekDaySummary] = []
