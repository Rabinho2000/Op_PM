"""Endpoints de calendário de planeamento e read model do Processo.

Eventos ``source=process`` são projeções read-only. Eventos manuais continuam
locais; nenhuma rota chama Microsoft Graph.
"""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.calendar import CalendarEvent
from app.models.people import Person
from app.models.project import Project
from app.models.task import Task
from app.schemas.planning import (
    CalendarEventCategoryRead,
    CalendarEventCreate,
    CalendarEventRead,
    CalendarEventUpdate,
    PlanningPreferencePatch,
    PlanningPreferenceRead,
    PlanningProcessOptionRead,
)
from app.security.current_user import get_auth_context
from app.security.permissions import (
    AuthContext,
    can_manage_calendar_event,
    is_installer_readonly_scope,
)
from app.services.planning import (
    CALENDAR_EVENT_CATEGORIES,
    CalendarEventValidationError,
    PlanningPreferenceValidationError,
    cancel_calendar_event,
    create_calendar_event,
    event_assignee_ids,
    get_event_for_mutation,
    get_planning_preferences,
    get_visible_event,
    list_calendar_events,
    list_process_calendar_events,
    list_process_options,
    update_calendar_event,
    update_planning_preferences,
)

router = APIRouter(prefix="/api/planning", tags=["planning"])
preferences_router = APIRouter(prefix="/api/me", tags=["planning"])


def _require_calendar_view(ctx: AuthContext) -> None:
    if not (ctx.has_permission("calendar.view") or ctx.has_permission("works_calendar.view_assigned_installer")):
        raise HTTPException(status_code=403, detail="Sem permissão para ver o planeamento.")


def _deny_installer_generic_planning(ctx: AuthContext) -> None:
    """O canal externo usa exclusivamente o Calendário de obras dedicado."""
    if is_installer_readonly_scope(ctx):
        raise HTTPException(status_code=403, detail="Sem permissão para ver o planeamento.")


def _require_calendar_write(ctx: AuthContext) -> None:
    if is_installer_readonly_scope(ctx) or not ctx.has_permission("calendar.manage"):
        raise HTTPException(status_code=403, detail="O papel externo tem acesso somente de leitura.")


def _manual_process_responsible(db: Session, event: CalendarEvent) -> tuple[list[uuid.UUID], list[str]]:
    stage = event.process_stage
    project = event.project
    if stage is None or project is None:
        return [], []
    if stage.responsible_rule == "pm" and project.pm is not None:
        return [project.pm.id], [project.pm.display_name]
    if stage.responsible_rule == "support_delegate" and project.pm_person_id is not None:
        from app.models.workflow import SupportDelegation

        delegation = (
            db.query(SupportDelegation)
            .filter(SupportDelegation.pm_person_id == project.pm_person_id)
            .one_or_none()
        )
        if delegation is not None:
            person = db.get(Person, delegation.support_person_id)
            if person is not None and person.is_active:
                return [person.id], [person.display_name]
        if project.pm is not None:
            return [project.pm.id], [project.pm.display_name]
    if stage.responsible_rule == "role" and stage.responsible_role_code:
        from app.models.identity import Role, User, UserRole

        rows = (
            db.query(Person.id, Person.display_name)
            .join(User, User.person_id == Person.id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .filter(
                Role.code == stage.responsible_role_code,
                User.is_active.is_(True),
                Person.is_active.is_(True),
            )
            .order_by(Person.display_name, Person.id)
            .all()
        )
        return [person_id for person_id, _ in rows], [name for _, name in rows]
    return [], []


def _to_read(db: Session, event: CalendarEvent, ctx: AuthContext) -> CalendarEventRead:
    data = CalendarEventRead.model_validate(event)
    participant_ids = event_assignee_ids(event)
    people_by_id = {person.id: person for person in (event.assignees or [])}
    if event.assigned_to is not None:
        people_by_id.setdefault(event.assigned_to.id, event.assigned_to)
    if participant_ids:
        missing = [person_id for person_id in participant_ids if person_id not in people_by_id]
        if missing:
            people_by_id.update(
                {
                    person.id: person
                    for person in db.query(Person).filter(Person.id.in_(missing)).all()
                }
            )
    data.assigned_to_person_ids = participant_ids
    data.assigned_to_display_names = [
        people_by_id[person_id].display_name
        for person_id in participant_ids
        if person_id in people_by_id
    ]
    data.assigned_to_display_name = (
        data.assigned_to_display_names[0] if data.assigned_to_display_names else None
    )
    data.source = "manual"
    data.source_id = event.id
    if event.project_id:
        project = event.project or db.get(Project, event.project_id)
        data.project_name = project.name if project else None
        data.project_url = f"/projects/{event.project_id}?tab=processo" if event.process_stage_id else f"/projects/{event.project_id}"
    if event.task_id:
        task = event.task or db.get(Task, event.task_id)
        data.task_title = task.title if task else None
    if event.process_stage_id:
        stage = event.process_stage or db.get(type(event.process_stage), event.process_stage_id)
        if stage is not None:
            data.process_stage_code = stage.code
            data.process_stage_title = stage.title
            data.responsible_person_ids, data.responsible_display_names = _manual_process_responsible(db, event)
    if event.process_subtask_id:
        subtask = event.process_subtask or db.get(type(event.process_subtask), event.process_subtask_id)
        if subtask is not None:
            data.process_subtask_code = subtask.code
            data.process_subtask_title = subtask.title
            if data.process_stage_id is None:
                data.process_stage_id = subtask.stage_id
    label, color = CALENDAR_EVENT_CATEGORIES.get(event.category, CALENDAR_EVENT_CATEGORIES["other"])
    data.category_label = label
    data.category_color = color
    data.can_manage = can_manage_calendar_event(ctx, event.project if event.project_id else None)
    if is_installer_readonly_scope(ctx):
        # Only the authenticated person's participation is meaningful in the
        # scoped channel; hide foreign people and process responsibility rows.
        if ctx.person_id in participant_ids:
            data.assigned_to_person_ids = [ctx.person_id]
            data.assigned_to_display_names = [
                people_by_id[ctx.person_id].display_name
            ] if ctx.person_id in people_by_id else []
            data.assigned_to_display_name = data.assigned_to_display_names[0] if data.assigned_to_display_names else None
        else:
            data.assigned_to_person_ids = []
            data.assigned_to_display_names = []
            data.assigned_to_display_name = None
        data.responsible_person_ids = []
        data.responsible_display_names = []
        data.can_manage = False
    return data


def _list_events(
    project_id: uuid.UUID | None,
    assigned_to_person_id: uuid.UUID | None,
    mine_only: bool,
    category: str | None,
    starts_from: dt.datetime | None,
    starts_to: dt.datetime | None,
    db: Session,
    ctx: AuthContext,
) -> list[CalendarEventRead]:
    try:
        events = list_calendar_events(
            db,
            ctx,
            project_id=project_id,
            assigned_to_person_id=assigned_to_person_id,
            mine_only=mine_only,
            category=category,
            starts_from=starts_from,
            starts_to=starts_to,
        )
    except CalendarEventValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return [_to_read(db, event, ctx) for event in events]


@preferences_router.get("/planning-preferences", response_model=PlanningPreferenceRead)
def get_preferences_endpoint(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> dict[str, object]:
    _deny_installer_generic_planning(ctx)
    _require_calendar_view(ctx)
    try:
        return get_planning_preferences(db, ctx)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Não foi possível carregar as preferências de planeamento.",
        ) from exc


@preferences_router.patch("/planning-preferences", response_model=PlanningPreferenceRead)
def patch_preferences_endpoint(
    body: PlanningPreferencePatch,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, object]:
    _deny_installer_generic_planning(ctx)
    _require_calendar_view(ctx)
    _require_calendar_write(ctx)
    try:
        return update_planning_preferences(db, ctx, body.model_dump(exclude_unset=True))
    except PlanningPreferenceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/event-categories", response_model=list[CalendarEventCategoryRead])
def list_event_categories_endpoint(
    ctx: AuthContext = Depends(get_auth_context),
) -> list[CalendarEventCategoryRead]:
    _deny_installer_generic_planning(ctx)
    _require_calendar_view(ctx)
    return [
        CalendarEventCategoryRead(code=code, label=label, color=color)
        for code, (label, color) in CALENDAR_EVENT_CATEGORIES.items()
    ]


@router.get("/events", response_model=list[CalendarEventRead])
def list_events_endpoint(
    project_id: uuid.UUID | None = None,
    assigned_to_person_id: uuid.UUID | None = None,
    mine_only: bool = False,
    category: str | None = None,
    starts_from: dt.datetime | None = Query(default=None),
    starts_to: dt.datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[CalendarEventRead]:
    _deny_installer_generic_planning(ctx)
    return _list_events(
        project_id, assigned_to_person_id, mine_only, category, starts_from, starts_to, db, ctx
    )


@router.get("/calendar", response_model=list[CalendarEventRead])
def calendar_view_endpoint(
    project_id: uuid.UUID | None = None,
    assigned_to_person_id: uuid.UUID | None = None,
    mine_only: bool = False,
    category: str | None = None,
    starts_from: dt.datetime | None = Query(default=None),
    starts_to: dt.datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[CalendarEventRead]:
    _deny_installer_generic_planning(ctx)
    return _list_events(
        project_id, assigned_to_person_id, mine_only, category, starts_from, starts_to, db, ctx
    )


@router.get("/process-events", response_model=list[CalendarEventRead])
def process_events_endpoint(
    project_id: uuid.UUID | None = None,
    assigned_to_person_id: uuid.UUID | None = None,
    mine_only: bool = False,
    category: str | None = None,
    starts_from: dt.datetime | None = Query(default=None),
    starts_to: dt.datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[CalendarEventRead]:
    _deny_installer_generic_planning(ctx)
    try:
        rows = list_process_calendar_events(
            db,
            ctx,
            project_id=project_id,
            assigned_to_person_id=assigned_to_person_id,
            mine_only=mine_only,
            category=category,
            starts_from=starts_from,
            starts_to=starts_to,
        )
    except CalendarEventValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return [CalendarEventRead.model_validate(row) for row in rows]


@router.get("/process-options/{project_id}", response_model=list[PlanningProcessOptionRead])
def process_options_endpoint(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[PlanningProcessOptionRead]:
    _deny_installer_generic_planning(ctx)
    options = list_process_options(db, ctx, project_id)
    if options is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")
    return [PlanningProcessOptionRead.model_validate(option) for option in options]


@router.get("/events/{event_id}", response_model=CalendarEventRead)
def get_event_endpoint(
    event_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> CalendarEventRead:
    _deny_installer_generic_planning(ctx)
    event = get_visible_event(db, ctx, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Evento não encontrado ou sem permissão para o ver.")
    return _to_read(db, event, ctx)


@router.post("/events", response_model=CalendarEventRead, status_code=201)
def create_event_endpoint(
    body: CalendarEventCreate, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> CalendarEventRead:
    _deny_installer_generic_planning(ctx)
    try:
        supplied = body.model_dump(exclude_unset=True)
        event = create_calendar_event(
            db,
            ctx=ctx,
            title=body.title,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            project_id=body.project_id,
            task_id=body.task_id,
            assigned_to_person_id=body.assigned_to_person_id,
            assigned_to_person_ids=(body.assigned_to_person_ids if "assigned_to_person_ids" in supplied else None),
            category=body.category,
            process_stage_id=body.process_stage_id,
            process_subtask_id=body.process_subtask_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except CalendarEventValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return _to_read(db, event, ctx)


@router.patch("/events/{event_id}", response_model=CalendarEventRead)
def update_event_endpoint(
    event_id: uuid.UUID,
    body: CalendarEventUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> CalendarEventRead:
    _deny_installer_generic_planning(ctx)
    event = get_event_for_mutation(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Evento não encontrado.")
    try:
        updated = update_calendar_event(db, event=event, changes=body.model_dump(exclude_unset=True), ctx=ctx)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except CalendarEventValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return _to_read(db, updated, ctx)


@router.post("/events/{event_id}/cancel", response_model=CalendarEventRead)
def cancel_event_endpoint(
    event_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> CalendarEventRead:
    _deny_installer_generic_planning(ctx)
    event = get_event_for_mutation(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Evento não encontrado.")
    try:
        updated = cancel_calendar_event(db, event=event, ctx=ctx)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return _to_read(db, updated, ctx)
