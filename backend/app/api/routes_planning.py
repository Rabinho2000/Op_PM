"""Endpoints de calendário de planeamento — ver app/services/planning.py.
Continua local nesta versão: sem Microsoft Graph, sem envio de email,
`graph_event_id` nunca preenchido (D-010).
"""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.calendar import CalendarEvent
from app.models.people import Person
from app.models.project import Project
from app.models.task import Task
from app.schemas.planning import CalendarEventCreate, CalendarEventRead, CalendarEventUpdate
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, can_manage_calendar_event
from app.services.planning import (
    CalendarEventValidationError,
    cancel_calendar_event,
    create_calendar_event,
    get_visible_event,
    list_calendar_events,
    update_calendar_event,
)

router = APIRouter(prefix="/api/planning", tags=["planning"])


def _to_read(db: Session, event: CalendarEvent, ctx: AuthContext) -> CalendarEventRead:
    data = CalendarEventRead.model_validate(event)
    if event.project_id:
        project = event.project or db.get(Project, event.project_id)
        data.project_name = project.name if project else None
    if event.task_id:
        task = event.task or db.get(Task, event.task_id)
        data.task_title = task.title if task else None
    if event.assigned_to_person_id:
        person = db.get(Person, event.assigned_to_person_id)
        data.assigned_to_display_name = person.display_name if person else None
    data.can_manage = can_manage_calendar_event(ctx, event.project if event.project_id else None)
    return data


def _list_events(
    project_id: uuid.UUID | None,
    assigned_to_person_id: uuid.UUID | None,
    mine_only: bool,
    starts_from: dt.datetime | None,
    starts_to: dt.datetime | None,
    db: Session,
    ctx: AuthContext,
) -> list[CalendarEventRead]:
    events = list_calendar_events(
        db,
        ctx,
        project_id=project_id,
        assigned_to_person_id=assigned_to_person_id,
        mine_only=mine_only,
        starts_from=starts_from,
        starts_to=starts_to,
    )
    return [_to_read(db, e, ctx) for e in events]


@router.get("/events", response_model=list[CalendarEventRead])
def list_events_endpoint(
    project_id: uuid.UUID | None = None,
    assigned_to_person_id: uuid.UUID | None = None,
    mine_only: bool = False,
    starts_from: dt.datetime | None = Query(default=None),
    starts_to: dt.datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[CalendarEventRead]:
    return _list_events(project_id, assigned_to_person_id, mine_only, starts_from, starts_to, db, ctx)


@router.get("/calendar", response_model=list[CalendarEventRead])
def calendar_view_endpoint(
    project_id: uuid.UUID | None = None,
    assigned_to_person_id: uuid.UUID | None = None,
    mine_only: bool = False,
    starts_from: dt.datetime | None = Query(default=None),
    starts_to: dt.datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[CalendarEventRead]:
    """Mesmo resultado que `/events` — endpoint separado só para o
    frontend pedir explicitamente "vista de calendário" com um intervalo de
    datas, sem overloading semântico no mesmo path."""
    return _list_events(project_id, assigned_to_person_id, mine_only, starts_from, starts_to, db, ctx)


@router.get("/events/{event_id}", response_model=CalendarEventRead)
def get_event_endpoint(
    event_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> CalendarEventRead:
    event = get_visible_event(db, ctx, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Evento não encontrado ou sem permissão para o ver.")
    return _to_read(db, event, ctx)


@router.post("/events", response_model=CalendarEventRead, status_code=201)
def create_event_endpoint(
    body: CalendarEventCreate, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> CalendarEventRead:
    try:
        event = create_calendar_event(
            db,
            ctx=ctx,
            title=body.title,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            project_id=body.project_id,
            task_id=body.task_id,
            assigned_to_person_id=body.assigned_to_person_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except CalendarEventValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _to_read(db, event, ctx)


@router.patch("/events/{event_id}", response_model=CalendarEventRead)
def update_event_endpoint(
    event_id: uuid.UUID,
    body: CalendarEventUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> CalendarEventRead:
    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Evento não encontrado.")
    try:
        updated = update_calendar_event(db, event=event, changes=body.model_dump(exclude_unset=True), ctx=ctx)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except CalendarEventValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _to_read(db, updated, ctx)


@router.post("/events/{event_id}/cancel", response_model=CalendarEventRead)
def cancel_event_endpoint(
    event_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> CalendarEventRead:
    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Evento não encontrado.")
    try:
        updated = cancel_calendar_event(db, event=event, ctx=ctx)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return _to_read(db, updated, ctx)
