"""Calendário de planeamento ligado a tarefas — ver
docs/MAP_AND_PLANNING.md. `CalendarEvent.task_id`, quando presente, tem de
apontar sempre para uma tarefa do mesmo projeto do evento — validado aqui,
nunca confiado ao cliente. Continua sem qualquer chamada ao Microsoft
Graph nesta fase (`graph_event_id` fica sempre vazio — D-010).
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy.orm import Query, Session

from app.models.calendar import CalendarEvent
from app.models.project import Project
from app.models.task import Task
from app.security.permissions import AuthContext, can_manage_calendar_event, can_view_calendar_event


class CalendarEventValidationError(ValueError):
    pass


def _validate_task_matches_project(db: Session, *, task_id: uuid.UUID | None, project_id: uuid.UUID | None) -> None:
    if task_id is None:
        return
    task = db.get(Task, task_id)
    if task is None:
        raise CalendarEventValidationError("Tarefa não encontrada.")
    if project_id is None:
        raise CalendarEventValidationError("Um evento com tarefa associada tem de indicar o projeto dessa tarefa.")
    if task.project_id != project_id:
        raise CalendarEventValidationError(
            "A tarefa associada pertence a um projeto diferente do evento — não é permitido."
        )


def visible_events_query(db: Session, ctx: AuthContext) -> Query:
    if not ctx.has_permission("calendar.view"):
        return db.query(CalendarEvent).filter(False)
    return db.query(CalendarEvent)


def list_calendar_events(
    db: Session,
    ctx: AuthContext,
    *,
    project_id: uuid.UUID | None = None,
    assigned_to_person_id: uuid.UUID | None = None,
    mine_only: bool = False,
    starts_from: dt.datetime | None = None,
    starts_to: dt.datetime | None = None,
) -> list[CalendarEvent]:
    query = visible_events_query(db, ctx)
    if project_id is not None:
        query = query.filter(CalendarEvent.project_id == project_id)
    if assigned_to_person_id is not None:
        query = query.filter(CalendarEvent.assigned_to_person_id == assigned_to_person_id)
    if mine_only:
        query = query.filter(CalendarEvent.assigned_to_person_id == ctx.person_id)
    if starts_from is not None:
        query = query.filter(CalendarEvent.starts_at >= starts_from)
    if starts_to is not None:
        query = query.filter(CalendarEvent.starts_at <= starts_to)
    events = query.order_by(CalendarEvent.starts_at.asc()).all()
    # Filtra por visibilidade de projeto individualmente (eventos sem
    # projeto associado são visíveis a quem tem calendar.view, ver
    # can_view_calendar_event) — não dá para exprimir isto só em SQL sem
    # duplicar can_view_project.
    return [e for e in events if can_view_calendar_event(ctx, e.project if e.project_id else None)]


def get_visible_event(db: Session, ctx: AuthContext, event_id: uuid.UUID) -> CalendarEvent | None:
    event = db.get(CalendarEvent, event_id)
    if event is None:
        return None
    project = event.project if event.project_id else None
    if not can_view_calendar_event(ctx, project):
        return None
    return event


def create_calendar_event(
    db: Session,
    *,
    ctx: AuthContext,
    title: str,
    starts_at: dt.datetime,
    ends_at: dt.datetime,
    project_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
    assigned_to_person_id: uuid.UUID | None,
    visit_id: uuid.UUID | None = None,
) -> CalendarEvent:
    project = db.get(Project, project_id) if project_id is not None else None
    if not can_manage_calendar_event(ctx, project):
        raise PermissionError("Sem permissão para criar eventos de calendário.")
    if ends_at <= starts_at:
        raise CalendarEventValidationError("A hora de fim tem de ser depois da hora de início.")
    _validate_task_matches_project(db, task_id=task_id, project_id=project_id)

    event = CalendarEvent(
        title=title,
        starts_at=starts_at,
        ends_at=ends_at,
        project_id=project_id,
        task_id=task_id,
        assigned_to_person_id=assigned_to_person_id,
        visit_id=visit_id,
        status="rascunho",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def update_calendar_event(db: Session, *, event: CalendarEvent, changes: dict, ctx: AuthContext) -> CalendarEvent:
    project = event.project if event.project_id else None
    if not can_manage_calendar_event(ctx, project):
        raise PermissionError("Sem permissão para editar este evento de calendário.")

    new_project_id = changes.get("project_id", event.project_id)
    new_task_id = changes.get("task_id", event.task_id)
    _validate_task_matches_project(db, task_id=new_task_id, project_id=new_project_id)

    new_starts_at = changes.get("starts_at", event.starts_at)
    new_ends_at = changes.get("ends_at", event.ends_at)
    if new_ends_at <= new_starts_at:
        raise CalendarEventValidationError("A hora de fim tem de ser depois da hora de início.")

    for field_name, value in changes.items():
        setattr(event, field_name, value)
    db.commit()
    db.refresh(event)
    return event


def cancel_calendar_event(db: Session, *, event: CalendarEvent, ctx: AuthContext) -> CalendarEvent:
    project = event.project if event.project_id else None
    if not can_manage_calendar_event(ctx, project):
        raise PermissionError("Sem permissão para cancelar este evento de calendário.")
    event.status = "cancelado"
    db.commit()
    db.refresh(event)
    return event
