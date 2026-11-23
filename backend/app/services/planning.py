"""Calendário de planeamento local, com participantes e projeção do Processo.

Os eventos manuais continuam a ser dados persistidos em ``calendar_events``.
Os marcos do Processo são um read model determinístico: não criam tarefas nem
linhas em ``calendar_events`` e nunca são editáveis através das rotas de
escrita. Não há chamadas a Graph/Exchange nesta camada.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass
from collections.abc import Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Query, Session, joinedload, selectinload

from app.models.calendar import CalendarEvent, CalendarEventAudit, CalendarEventSeries
from app.models.identity import Role, User, UserRole
from app.models.people import Person
from app.models.planning import UserPlanningPreference
from app.models.project import Project, ProjectTeamAssignment
from app.models.task import Task
from app.models.workflow import Phase, SupportDelegation, WorkflowStage, WorkflowSubtask
from app.schemas.planning import normalize_calendar_instant
from app.security.permissions import (
    AuthContext,
    can_manage_calendar_event,
    can_view_calendar_event,
    has_only_delegated_project_scope,
    installer_project_scope_conditions,
    is_installer_readonly_scope,
)
from app.services.installers import business_day
from app.services.process import build_project_process
from app.services.projects import visible_projects_query
from app.security.perm import Perm


# Catálogo fechado: os códigos são estáveis e independentes dos títulos do
# Processo. Labels/cores são metadados de apresentação, não permissões.
CALENDAR_EVENT_CATEGORIES: dict[str, tuple[str, str]] = {
    "meeting": ("Reunião", "#2563eb"),
    "technical_visit": ("Visita técnica", "#0e7490"),
    "commissioning": ("Comissionamento", "#7c3aed"),
    "final_inspection": ("Inspeção final", "#15803d"),
    "pending": ("Pendência", "#b45309"),
    "work": ("Obra", "#475569"),
    "other": ("Outro", "#64748b"),
}
CALENDAR_EVENT_CATEGORY_CODES = frozenset(CALENDAR_EVENT_CATEGORIES)
PLANNING_VIEWS = frozenset({"month", "week", "list"})
LISBON = ZoneInfo("Europe/Lisbon")
_PROCESS_EVENT_NAMESPACE = uuid.UUID("4b3d6a5e-49a8-4e1b-bf55-7d5a8c64c7d9")
MAX_WEEKLY_OCCURRENCES = 52


class CalendarEventValidationError(ValueError):
    """Erro de input existente; a rota devolve 400 para compatibilidade."""

    status_code = 400


class CalendarEventReferenceError(CalendarEventValidationError):
    """Referência inexistente/fora do âmbito; a API devolve 422."""

    status_code = 422


class CalendarEventIdempotencyConflict(CalendarEventValidationError):
    """A chave de uma série já foi usada para outro pedido."""

    status_code = 409


class PlanningPreferenceValidationError(ValueError):
    pass


@dataclass(frozen=True)
class _ResponsiblePeople:
    ids: list[uuid.UUID]
    names: list[str]


def _dedupe_ids(values: Iterable[uuid.UUID | None]) -> list[uuid.UUID]:
    result: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for value in values:
        if value is None or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def event_assignee_ids(event: CalendarEvent) -> list[uuid.UUID]:
    """IDs compatíveis: o campo singular legado vem sempre primeiro."""
    association_ids = [person.id for person in (event.assignees or [])]
    return _dedupe_ids([event.assigned_to_person_id, *association_ids])


def _audit_value(value: object) -> object:
    if isinstance(value, dt.datetime):
        return normalize_calendar_instant(value).isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_audit_value(item) for item in value]
    return value


def _calendar_event_audit_values(event: CalendarEvent) -> dict[str, object]:
    return {
        "title": event.title,
        "starts_at": event.starts_at,
        "ends_at": event.ends_at,
        "project_id": event.project_id,
        "task_id": event.task_id,
        "assigned_to_person_id": event.assigned_to_person_id,
        "assigned_to_person_ids": event_assignee_ids(event),
        "category": event.category,
        "process_stage_id": event.process_stage_id,
        "process_subtask_id": event.process_subtask_id,
        "status": event.status,
    }


def _record_calendar_event_audit(
    db: Session,
    *,
    event: CalendarEvent,
    ctx: AuthContext,
    action: str,
    old_values: dict[str, object],
    new_values: dict[str, object],
) -> None:
    if action == "create":
        field_changes = {
            field_name: {"old": None, "new": _audit_value(new_value)}
            for field_name, new_value in new_values.items()
        }
    else:
        field_changes = {
            field_name: {
                "old": _audit_value(old_value),
                "new": _audit_value(new_values.get(field_name)),
            }
            for field_name, old_value in old_values.items()
            if _audit_value(old_value) != _audit_value(new_values.get(field_name))
        }
    if not field_changes:
        return
    db.add(
        CalendarEventAudit(
            event_id=event.id,
            series_id=event.series_id,
            actor_user_id=ctx.user.id,
            actor_person_id=ctx.person_id,
            action=action,
            field_changes=field_changes,
        )
    )


def _participant_condition(person_id: uuid.UUID):
    return or_(
        CalendarEvent.assigned_to_person_id == person_id,
        CalendarEvent.assignees.any(Person.id == person_id),
    )


def _project_scope_condition(ctx: AuthContext):
    conditions = []
    if ctx.has_permission(Perm.PROJECT_VIEW_OWN):
        conditions.append(Project.pm_person_id == ctx.person_id)
    if ctx.has_permission(Perm.PROJECT_VIEW_DELEGATED) and ctx.delegating_pm_ids:
        conditions.append(Project.pm_person_id.in_(ctx.delegating_pm_ids))
    conditions.extend(installer_project_scope_conditions(ctx))
    return conditions


def visible_events_query(db: Session, ctx: AuthContext) -> Query:
    """Apply the project scopes plus the Planning-only PM read capability.

    Um participante adicional nunca transforma um evento de projeto fora do
    âmbito num evento visível a Suporte. Só eventos sem projeto podem ser
    vistos por um perfil exclusivamente delegado quando esse perfil participa.
    ``calendar.view_all_pm`` expands only the calendar rows; the serializer
    removes linked project/task/Process detail outside the caller's project
    scope, and the event permission check excludes deleted projects.
    """
    if not (
        ctx.has_permission(Perm.CALENDAR_VIEW)
        or ctx.has_permission(Perm.CALENDAR_VIEW_ALL_PM)
        or ctx.has_permission(Perm.WORKS_CALENDAR_VIEW_ASSIGNED_INSTALLER)
    ):
        return db.query(CalendarEvent).filter(False)
    if ctx.has_permission(Perm.PROJECT_VIEW_ALL) or ctx.has_permission(Perm.CALENDAR_VIEW_ALL_PM):
        return db.query(CalendarEvent)

    project_conditions = _project_scope_condition(ctx)
    project_event = (
        CalendarEvent.project_id.in_(select(Project.id).where(or_(*project_conditions)))
        if project_conditions
        else None
    )
    if is_installer_readonly_scope(ctx):
        return db.query(CalendarEvent).filter(project_event) if project_event is not None else db.query(CalendarEvent).filter(False)
    if has_only_delegated_project_scope(ctx):
        unscoped_assigned = (CalendarEvent.project_id.is_(None), _participant_condition(ctx.person_id))
        conditions = [item for item in (project_event, *unscoped_assigned) if item is not None]
        return db.query(CalendarEvent).filter(or_(*conditions)) if conditions else db.query(CalendarEvent).filter(False)

    conditions = [CalendarEvent.project_id.is_(None)]
    if project_event is not None:
        conditions.append(project_event)
    return db.query(CalendarEvent).filter(or_(*conditions))


def _validate_task_matches_project(
    db: Session, *, task_id: uuid.UUID | None, project_id: uuid.UUID | None
) -> None:
    if task_id is None:
        return
    task = db.get(Task, task_id)
    if task is None:
        raise CalendarEventReferenceError("Tarefa não encontrada.")
    if project_id is None:
        raise CalendarEventValidationError(
            "Um evento com tarefa associada tem de indicar o projeto dessa tarefa."
        )
    if task.project_id != project_id:
        raise CalendarEventValidationError(
            "A tarefa associada pertence a um projeto diferente do evento — não é permitido."
        )


def _allowed_assignee_ids(db: Session, ctx: AuthContext, project: Project | None) -> set[uuid.UUID]:
    """IDs que podem ser escolhidos sem transformar o lookup em diretório global."""
    if ctx.has_permission(Perm.PROJECT_VIEW_ALL):
        return {
            person_id
            for (person_id,) in db.query(Person.id)
            .filter(Person.is_active.is_(True))
            .all()
        }

    allowed = {ctx.person_id}
    if project is None:
        return allowed
    if project.pm_person_id is not None:
        allowed.add(project.pm_person_id)
    task_ids = (
        db.query(Task.assigned_to_person_id)
        .filter(Task.project_id == project.id, Task.assigned_to_person_id.is_not(None))
        .all()
    )
    allowed.update(person_id for (person_id,) in task_ids if person_id is not None)
    return allowed


def _validate_assignees(
    db: Session, *, ctx: AuthContext, project: Project | None, person_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    ids = _dedupe_ids(person_ids)
    if not ids:
        return []
    allowed = _allowed_assignee_ids(db, ctx, project)
    active_ids = {
        person_id
        for (person_id,) in db.query(Person.id)
        .filter(Person.id.in_(ids), Person.is_active.is_(True))
        .all()
    }
    if set(ids) - active_ids or set(ids) - allowed:
        raise CalendarEventReferenceError("Uma ou mais pessoas não estão disponíveis para este evento.")
    return ids


def _resolve_assignees(
    db: Session,
    *,
    ctx: AuthContext,
    project: Project | None,
    changes: dict,
    existing_ids: list[uuid.UUID],
) -> tuple[bool, list[uuid.UUID]]:
    """Resolve omissão/lista/primário sem aplicar nada antes da validação."""
    list_present = "assigned_to_person_ids" in changes
    primary_present = "assigned_to_person_id" in changes
    if not list_present and not primary_present:
        return False, existing_ids

    if list_present:
        ids = _dedupe_ids(changes["assigned_to_person_ids"])
        primary = changes.get("assigned_to_person_id") if primary_present else None
        if primary is not None:
            if primary not in ids:
                raise CalendarEventReferenceError(
                    "assigned_to_person_id tem de estar incluído em assigned_to_person_ids."
                )
            ids = [primary, *[person_id for person_id in ids if person_id != primary]]
        elif primary_present and not ids:
            ids = []
        elif primary_present and changes["assigned_to_person_id"] is None and ids:
            raise CalendarEventReferenceError(
                "Não combine assigned_to_person_id=null com uma lista de participantes."
            )
    else:
        primary = changes["assigned_to_person_id"]
        ids = [] if primary is None else [primary]

    return True, _validate_assignees(db, ctx=ctx, project=project, person_ids=ids)


def _validate_process_refs(
    db: Session,
    *,
    project_id: uuid.UUID | None,
    process_stage_id: uuid.UUID | None,
    process_subtask_id: uuid.UUID | None,
) -> tuple[WorkflowStage | None, WorkflowSubtask | None]:
    if process_stage_id is None and process_subtask_id is None:
        return None, None
    if project_id is None:
        raise CalendarEventReferenceError("Uma ligação ao Processo tem de indicar o projeto.")

    stage = db.get(WorkflowStage, process_stage_id) if process_stage_id is not None else None
    subtask = db.get(WorkflowSubtask, process_subtask_id) if process_subtask_id is not None else None
    if process_stage_id is not None and stage is None:
        raise CalendarEventReferenceError("Etapa do Processo não encontrada.")
    if process_subtask_id is not None and subtask is None:
        raise CalendarEventReferenceError("Subtarefa do Processo não encontrada.")
    if subtask is not None:
        if stage is not None and subtask.stage_id != stage.id:
            raise CalendarEventReferenceError("A subtarefa não pertence à etapa indicada.")
        if stage is None:
            stage = db.get(WorkflowStage, subtask.stage_id)
    return stage, subtask


def _replace_event_assignees(db: Session, event: CalendarEvent, person_ids: list[uuid.UUID]) -> None:
    if not person_ids:
        event.assignees = []
        event.assigned_to_person_id = None
        return
    people = db.query(Person).filter(Person.id.in_(person_ids)).all()
    people_by_id = {person.id: person for person in people}
    event.assignees = [people_by_id[person_id] for person_id in person_ids]
    event.assigned_to_person_id = person_ids[0]


def _resolve_lisbon_wall_clock(value: dt.datetime, *, fold: int) -> dt.datetime:
    """Resolve a naive Lisbon wall clock without silently shifting DST gaps."""
    wall = value.replace(tzinfo=None)
    candidates = [wall.replace(tzinfo=LISBON, fold=fold), wall.replace(tzinfo=LISBON, fold=1 - fold)]
    valid = [
        candidate
        for candidate in candidates
        if candidate.astimezone(dt.timezone.utc).astimezone(LISBON).replace(tzinfo=None) == wall
    ]
    if not valid:
        raise CalendarEventValidationError(
            "A hora local escolhida não existe em Europe/Lisbon nessa data devido à mudança para o horário de verão."
        )
    # `fold` preserves the first occurrence's choice when a fall-back hour is
    # repeated. On dates without ambiguity both candidates have the same offset.
    selected = next((candidate for candidate in valid if candidate.fold == fold), valid[0])
    return selected.astimezone(dt.timezone.utc)


def _weekly_occurrence_instants(
    *,
    starts_at: dt.datetime,
    ends_at: dt.datetime,
    until_date: dt.date,
) -> tuple[dict[str, object], list[tuple[dt.datetime, dt.datetime]]]:
    first_start = normalize_calendar_instant(starts_at).astimezone(LISBON)
    first_end = normalize_calendar_instant(ends_at).astimezone(LISBON)
    starts_on = first_start.date()
    if until_date < starts_on:
        raise CalendarEventValidationError("A data final da série não pode ser anterior à primeira ocorrência.")
    occurrence_count = (until_date - starts_on).days // 7 + 1
    if occurrence_count > MAX_WEEKLY_OCCURRENCES:
        raise CalendarEventValidationError(
            f"Uma série semanal pode ter no máximo {MAX_WEEKLY_OCCURRENCES} ocorrências."
        )

    start_wall = first_start.replace(tzinfo=None)
    end_wall = first_end.replace(tzinfo=None)
    if end_wall <= start_wall:
        raise CalendarEventValidationError(
            "Para uma série semanal, a hora local de fim tem de ser posterior à hora local de início."
        )
    end_day_offset = (first_end.date() - starts_on).days
    schedule: dict[str, object] = {
        "starts_on": starts_on,
        "starts_at_local": start_wall.strftime("%H:%M"),
        "ends_day_offset": end_day_offset,
        "ends_at_local": end_wall.strftime("%H:%M"),
        "starts_fold": first_start.fold,
        "ends_fold": first_end.fold,
        "until_date": until_date,
        "occurrence_count": occurrence_count,
    }
    start_time = dt.time.fromisoformat(str(schedule["starts_at_local"]))
    end_time = dt.time.fromisoformat(str(schedule["ends_at_local"]))
    occurrences: list[tuple[dt.datetime, dt.datetime]] = []
    for index in range(occurrence_count):
        occurrence_date = starts_on + dt.timedelta(days=7 * index)
        local_start = dt.datetime.combine(occurrence_date, start_time)
        local_end = dt.datetime.combine(
            occurrence_date + dt.timedelta(days=end_day_offset), end_time
        )
        resolved_start = _resolve_lisbon_wall_clock(local_start, fold=first_start.fold)
        resolved_end = _resolve_lisbon_wall_clock(local_end, fold=first_end.fold)
        if resolved_end <= resolved_start:
            raise CalendarEventValidationError(
                "A hora de fim tem de ser posterior à hora de início em todas as ocorrências da série."
            )
        occurrences.append((resolved_start, resolved_end))
    return schedule, occurrences


def _series_request_fingerprint(values: dict[str, object]) -> str:
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def list_calendar_events(
    db: Session,
    ctx: AuthContext,
    *,
    project_id: uuid.UUID | None = None,
    assigned_to_person_id: uuid.UUID | None = None,
    mine_only: bool = False,
    category: str | None = None,
    starts_from: dt.datetime | None = None,
    starts_to: dt.datetime | None = None,
) -> list[CalendarEvent]:
    query = visible_events_query(db, ctx).options(
        joinedload(CalendarEvent.project),
        joinedload(CalendarEvent.task),
        joinedload(CalendarEvent.assigned_to),
        joinedload(CalendarEvent.process_stage),
        joinedload(CalendarEvent.process_subtask),
        joinedload(CalendarEvent.series),
        selectinload(CalendarEvent.assignees),
    )
    if project_id is not None:
        query = query.filter(CalendarEvent.project_id == project_id)
    if assigned_to_person_id is not None:
        query = query.filter(_participant_condition(assigned_to_person_id))
    if mine_only:
        query = query.filter(_participant_condition(ctx.person_id))
    if category is not None:
        if category not in CALENDAR_EVENT_CATEGORY_CODES:
            raise CalendarEventValidationError("Categoria de evento desconhecida.")
        query = query.filter(CalendarEvent.category == category)
    if starts_from is not None:
        query = query.filter(CalendarEvent.ends_at >= normalize_calendar_instant(starts_from))
    if starts_to is not None:
        query = query.filter(CalendarEvent.starts_at <= normalize_calendar_instant(starts_to))
    events = query.order_by(CalendarEvent.starts_at.asc(), CalendarEvent.id.asc()).all()
    return [
        event
        for event in events
        if can_view_calendar_event(
            ctx,
            event.project if event.project_id else None,
            assigned_to_person_id=event.assigned_to_person_id,
            assigned_to_person_ids=event_assignee_ids(event),
        )
    ]


def get_visible_event(db: Session, ctx: AuthContext, event_id: uuid.UUID) -> CalendarEvent | None:
    event = (
        db.query(CalendarEvent)
        .options(
            joinedload(CalendarEvent.project),
            joinedload(CalendarEvent.task),
            joinedload(CalendarEvent.assigned_to),
            joinedload(CalendarEvent.process_stage),
            joinedload(CalendarEvent.process_subtask),
            joinedload(CalendarEvent.series),
            selectinload(CalendarEvent.assignees),
        )
        .filter(CalendarEvent.id == event_id)
        .one_or_none()
    )
    if event is None:
        return None
    project = event.project if event.project_id else None
    if not can_view_calendar_event(
        ctx,
        project,
        assigned_to_person_id=event.assigned_to_person_id,
        assigned_to_person_ids=event_assignee_ids(event),
    ):
        return None
    return event


def get_event_for_mutation(db: Session, event_id: uuid.UUID) -> CalendarEvent | None:
    """Carrega um evento persistido para a rota de escrita.

    A leitura de detalhe mantém ocultos os eventos fora do âmbito (404), mas
    uma tentativa de mutação de uma linha existente tem de chegar ao serviço,
    onde ``can_manage_calendar_event`` devolve a recusa 403 estabelecida.
    IDs inexistentes — incluindo UUIDs de projeções do Processo — continuam a
    devolver ``None`` e, portanto, 404 na rota.
    """
    return (
        db.query(CalendarEvent)
        .options(
            joinedload(CalendarEvent.project),
            joinedload(CalendarEvent.task),
            joinedload(CalendarEvent.assigned_to),
            joinedload(CalendarEvent.process_stage),
            joinedload(CalendarEvent.process_subtask),
            joinedload(CalendarEvent.series),
            selectinload(CalendarEvent.assignees),
        )
        .filter(CalendarEvent.id == event_id)
        .one_or_none()
    )


def _lock_calendar_event(db: Session, event_id: uuid.UUID) -> CalendarEvent | None:
    """Recarrega a linha e os dados de autorização depois de obter o bloqueio.

    ``with_for_update`` é efetivo em PostgreSQL. O motor SQLite inicia as
    transações de escrita com ``BEGIN IMMEDIATE``, pelo que a consulta espera
    pelo escritor atual. ``populate_existing`` é necessário nos dois motores:
    o chamador já pode ter esta linha (e as relações) no identity map.
    """
    return (
        db.query(CalendarEvent)
        .options(
            joinedload(CalendarEvent.project),
            joinedload(CalendarEvent.task),
            joinedload(CalendarEvent.assigned_to),
            joinedload(CalendarEvent.process_stage),
            joinedload(CalendarEvent.process_subtask),
            joinedload(CalendarEvent.series),
            selectinload(CalendarEvent.assignees),
        )
        .filter(CalendarEvent.id == event_id)
        # The eager-loaded optional relations add LEFT JOINs. Lock only the
        # canonical row so PostgreSQL does not lock their nullable sides.
        .with_for_update(of=CalendarEvent)
        .populate_existing()
        .one_or_none()
    )


def _lock_calendar_series(db: Session, series_id: uuid.UUID) -> CalendarEventSeries | None:
    return (
        db.query(CalendarEventSeries)
        .filter(CalendarEventSeries.id == series_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )


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
    assigned_to_person_ids: list[uuid.UUID] | None = None,
    category: str = "other",
    process_stage_id: uuid.UUID | None = None,
    process_subtask_id: uuid.UUID | None = None,
    visit_id: uuid.UUID | None = None,
) -> CalendarEvent:
    project = (db.get(Project, project_id) if project_id is not None else None)
    if project_id is not None and project is None:
        raise CalendarEventReferenceError("Projeto não encontrado.")
    if not can_manage_calendar_event(ctx, project):
        raise PermissionError("Sem permissão para criar eventos de calendário.")
    starts_at = normalize_calendar_instant(starts_at)
    ends_at = normalize_calendar_instant(ends_at)
    if ends_at <= starts_at:
        raise CalendarEventValidationError("A hora de fim tem de ser depois da hora de início.")
    if category not in CALENDAR_EVENT_CATEGORY_CODES:
        raise CalendarEventReferenceError("Categoria de evento desconhecida.")
    _validate_task_matches_project(db, task_id=task_id, project_id=project_id)
    stage, subtask = _validate_process_refs(
        db,
        project_id=project_id,
        process_stage_id=process_stage_id,
        process_subtask_id=process_subtask_id,
    )
    if assigned_to_person_ids is not None:
        person_ids = _dedupe_ids(assigned_to_person_ids)
        if assigned_to_person_id is not None:
            if assigned_to_person_id not in person_ids:
                raise CalendarEventReferenceError(
                    "assigned_to_person_id tem de estar incluído em assigned_to_person_ids."
                )
            person_ids = [
                assigned_to_person_id,
                *[person_id for person_id in person_ids if person_id != assigned_to_person_id],
            ]
    else:
        person_ids = [] if assigned_to_person_id is None else [assigned_to_person_id]
    person_ids = _validate_assignees(db, ctx=ctx, project=project, person_ids=person_ids)

    event = CalendarEvent(
        title=title,
        starts_at=starts_at,
        ends_at=ends_at,
        project_id=project_id,
        task_id=task_id,
        category=category,
        process_stage_id=stage.id if stage is not None else None,
        process_subtask_id=subtask.id if subtask is not None else None,
        visit_id=visit_id,
        status="rascunho",
    )
    db.add(event)
    _replace_event_assignees(db, event, person_ids)
    db.flush()
    _record_calendar_event_audit(
        db,
        event=event,
        ctx=ctx,
        action="create",
        old_values={},
        new_values=_calendar_event_audit_values(event),
    )
    db.commit()
    db.refresh(event)
    return get_visible_event(db, ctx, event.id) or event


def create_weekly_calendar_event_series(
    db: Session,
    *,
    ctx: AuthContext,
    title: str,
    starts_at: dt.datetime,
    ends_at: dt.datetime,
    recurrence_until: dt.date,
    idempotency_key: str,
    project_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
    assigned_to_person_id: uuid.UUID | None,
    assigned_to_person_ids: list[uuid.UUID] | None = None,
    category: str = "other",
    process_stage_id: uuid.UUID | None = None,
    process_subtask_id: uuid.UUID | None = None,
) -> CalendarEvent:
    """Create a bounded weekly series atomically and idempotently."""
    project = (db.get(Project, project_id) if project_id is not None else None)
    if project_id is not None and project is None:
        raise CalendarEventReferenceError("Projeto não encontrado.")
    if not can_manage_calendar_event(ctx, project):
        raise PermissionError("Sem permissão para criar eventos de calendário.")

    starts_at = normalize_calendar_instant(starts_at)
    ends_at = normalize_calendar_instant(ends_at)
    if ends_at <= starts_at:
        raise CalendarEventValidationError("A hora de fim tem de ser depois da hora de início.")
    if category not in CALENDAR_EVENT_CATEGORY_CODES:
        raise CalendarEventReferenceError("Categoria de evento desconhecida.")
    _validate_task_matches_project(db, task_id=task_id, project_id=project_id)
    stage, subtask = _validate_process_refs(
        db,
        project_id=project_id,
        process_stage_id=process_stage_id,
        process_subtask_id=process_subtask_id,
    )
    if assigned_to_person_ids is not None:
        person_ids = _dedupe_ids(assigned_to_person_ids)
        if assigned_to_person_id is not None:
            if assigned_to_person_id not in person_ids:
                raise CalendarEventReferenceError(
                    "assigned_to_person_id tem de estar incluído em assigned_to_person_ids."
                )
            person_ids = [
                assigned_to_person_id,
                *[person_id for person_id in person_ids if person_id != assigned_to_person_id],
            ]
    else:
        person_ids = [] if assigned_to_person_id is None else [assigned_to_person_id]
    person_ids = _validate_assignees(db, ctx=ctx, project=project, person_ids=person_ids)
    schedule, occurrences = _weekly_occurrence_instants(
        starts_at=starts_at, ends_at=ends_at, until_date=recurrence_until
    )

    fingerprint = _series_request_fingerprint(
        {
            "title": title,
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
            "recurrence_until": recurrence_until.isoformat(),
            "project_id": str(project_id) if project_id else None,
            "task_id": str(task_id) if task_id else None,
            "assigned_to_person_ids": [str(person_id) for person_id in person_ids],
            "category": category,
            "process_stage_id": str(stage.id) if stage else None,
            "process_subtask_id": str(subtask.id) if subtask else None,
        }
    )
    creator_id = ctx.user.id
    existing = (
        db.query(CalendarEventSeries)
        .filter(
            CalendarEventSeries.created_by_user_id == creator_id,
            CalendarEventSeries.idempotency_key == idempotency_key,
        )
        .one_or_none()
    )
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise CalendarEventIdempotencyConflict(
                "Esta chave de idempotência já foi usada com outros dados. Reabra o formulário para iniciar uma série diferente."
            )
        first = (
            db.query(CalendarEvent)
            .filter(CalendarEvent.series_id == existing.id)
            .order_by(CalendarEvent.series_occurrence_index)
            .first()
        )
        if first is None:
            raise CalendarEventValidationError("A série existente não tem ocorrências disponíveis.")
        return first

    series = CalendarEventSeries(
        created_by_user_id=creator_id,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        recurrence_rule="weekly",
        timezone=LISBON.key,
        **schedule,
    )
    try:
        # Unique(idempotency owner, key) handles concurrent retries in the DB;
        # occurrence uniqueness is a second guard against duplicate rows.
        with db.begin_nested():
            db.add(series)
            db.flush()
            created_events: list[CalendarEvent] = []
            for index, (occurrence_start, occurrence_end) in enumerate(occurrences):
                event = CalendarEvent(
                    title=title,
                    starts_at=occurrence_start,
                    ends_at=occurrence_end,
                    project_id=project_id,
                    task_id=task_id,
                    category=category,
                    process_stage_id=stage.id if stage else None,
                    process_subtask_id=subtask.id if subtask else None,
                    status="rascunho",
                    series_id=series.id,
                    series_occurrence_index=index,
                )
                db.add(event)
                _replace_event_assignees(db, event, person_ids)
                created_events.append(event)
            db.flush()
            for event in created_events:
                _record_calendar_event_audit(
                    db,
                    event=event,
                    ctx=ctx,
                    action="create",
                    old_values={},
                    new_values=_calendar_event_audit_values(event),
                )
    except IntegrityError:
        existing = (
            db.query(CalendarEventSeries)
            .filter(
                CalendarEventSeries.created_by_user_id == creator_id,
                CalendarEventSeries.idempotency_key == idempotency_key,
            )
            .one_or_none()
        )
        if existing is None:
            raise
        if existing.request_fingerprint != fingerprint:
            raise CalendarEventIdempotencyConflict(
                "Esta chave de idempotência já foi usada com outros dados. Reabra o formulário para iniciar uma série diferente."
            )
        first = (
            db.query(CalendarEvent)
            .filter(CalendarEvent.series_id == existing.id)
            .order_by(CalendarEvent.series_occurrence_index)
            .first()
        )
        if first is None:
            raise CalendarEventValidationError("A série existente não tem ocorrências disponíveis.")
        return first

    db.commit()
    first = (
        db.query(CalendarEvent)
        .filter(CalendarEvent.series_id == series.id)
        .order_by(CalendarEvent.series_occurrence_index)
        .first()
    )
    assert first is not None
    return get_visible_event(db, ctx, first.id) or first


def _apply_calendar_event_changes(
    db: Session, *, event: CalendarEvent, changes: dict, ctx: AuthContext
) -> None:
    old_values = _calendar_event_audit_values(event)
    old_project = event.project if event.project_id else None
    if not can_manage_calendar_event(ctx, old_project):
        raise PermissionError("Sem permissão para editar este evento de calendário.")

    new_project_id = changes.get("project_id", event.project_id)
    new_project = (db.get(Project, new_project_id) if new_project_id is not None else None)
    if new_project_id is not None and new_project is None:
        raise CalendarEventReferenceError("Projeto não encontrado.")
    if not can_manage_calendar_event(ctx, new_project):
        raise PermissionError("Sem permissão para editar o novo projeto deste evento.")

    new_task_id = changes.get("task_id", event.task_id)
    _validate_task_matches_project(db, task_id=new_task_id, project_id=new_project_id)
    new_stage_id = changes.get("process_stage_id", event.process_stage_id)
    new_subtask_id = changes.get("process_subtask_id", event.process_subtask_id)
    stage, subtask = _validate_process_refs(
        db,
        project_id=new_project_id,
        process_stage_id=new_stage_id,
        process_subtask_id=new_subtask_id,
    )

    normalized_changes = dict(changes)
    for field_name in ("starts_at", "ends_at"):
        if field_name not in normalized_changes:
            continue
        if normalized_changes[field_name] is None:
            raise CalendarEventValidationError(f"{field_name} não pode ser null.")
        normalized_changes[field_name] = normalize_calendar_instant(normalized_changes[field_name])
    new_starts_at = normalize_calendar_instant(event.starts_at)
    new_ends_at = normalize_calendar_instant(event.ends_at)
    new_starts_at = normalized_changes.get("starts_at", new_starts_at)
    new_ends_at = normalized_changes.get("ends_at", new_ends_at)
    if new_ends_at <= new_starts_at:
        raise CalendarEventValidationError("A hora de fim tem de ser depois da hora de início.")
    new_category = changes.get("category", event.category)
    if new_category not in CALENDAR_EVENT_CATEGORY_CODES:
        raise CalendarEventReferenceError("Categoria de evento desconhecida.")

    participant_keys = {"assigned_to_person_id", "assigned_to_person_ids"}
    participant_changes = {key: value for key, value in changes.items() if key in participant_keys}
    if participant_changes:
        _, person_ids = _resolve_assignees(
            db,
            ctx=ctx,
            project=new_project,
            changes=participant_changes,
            existing_ids=event_assignee_ids(event),
        )
    else:
        person_ids = event_assignee_ids(event)

    for field_name, value in normalized_changes.items():
        if field_name in participant_keys or field_name in {"process_stage_id", "process_subtask_id"}:
            continue
        setattr(event, field_name, value)
    event.project_id = new_project_id
    event.task_id = new_task_id
    event.category = new_category
    event.process_stage_id = stage.id if stage is not None else None
    event.process_subtask_id = subtask.id if subtask is not None else None
    if participant_changes:
        _replace_event_assignees(db, event, person_ids)
    _record_calendar_event_audit(
        db,
        event=event,
        ctx=ctx,
        action="update",
        old_values=old_values,
        new_values=_calendar_event_audit_values(event),
    )

    return None


def _ensure_series_visible(ctx: AuthContext, events: Iterable[CalendarEvent]) -> None:
    """Uma operação sobre a série não pode revelar nem esconder ocorrências.

    A permissão de escrita não concede leitura: uma ocorrência pode ter sido
    movida individualmente para outro projeto/participantes e a resposta da
    operação devolve dados da série.
    """
    for occurrence in events:
        if not can_view_calendar_event(
            ctx,
            occurrence.project if occurrence.project_id else None,
            assigned_to_person_id=occurrence.assigned_to_person_id,
            assigned_to_person_ids=event_assignee_ids(occurrence),
        ):
            raise PermissionError("Sem permissão para ver todas as ocorrências desta série.")


def update_calendar_event(
    db: Session, *, event: CalendarEvent, changes: dict, ctx: AuthContext
) -> CalendarEvent:
    # Lock the series first when this is one of its occurrences. This gives
    # occurrence edits the same serialization point as whole-series edits and
    # avoids parent/child lock-order deadlocks on PostgreSQL.
    initial_series_id = event.series_id
    if initial_series_id is not None and _lock_calendar_series(db, initial_series_id) is None:
        raise CalendarEventValidationError("A série semanal já não está disponível.")
    locked_event = _lock_calendar_event(db, event.id)
    if locked_event is None or locked_event.series_id != initial_series_id:
        raise CalendarEventValidationError("O evento já não está disponível para edição.")
    _apply_calendar_event_changes(db, event=locked_event, changes=changes, ctx=ctx)
    db.commit()
    db.refresh(locked_event)
    return get_visible_event(db, ctx, locked_event.id) or locked_event


def update_calendar_event_series(
    db: Session, *, event: CalendarEvent, changes: dict, ctx: AuthContext
) -> CalendarEvent:
    initial_series_id = event.series_id
    if initial_series_id is None:
        raise CalendarEventValidationError("Este evento não pertence a uma série semanal.")
    series = _lock_calendar_series(db, initial_series_id)
    if series is None:
        raise CalendarEventValidationError("A série semanal já não está disponível.")
    locked_event = _lock_calendar_event(db, event.id)
    if locked_event is None or locked_event.series_id != series.id:
        raise CalendarEventValidationError("A ocorrência já não pertence à série semanal.")
    event = locked_event
    project = event.project if event.project_id else None
    if not can_manage_calendar_event(ctx, project):
        raise PermissionError("Sem permissão para editar esta série de calendário.")
    events = (
        db.query(CalendarEvent)
        .filter(CalendarEvent.series_id == series.id)
        .order_by(CalendarEvent.series_occurrence_index)
        .with_for_update(of=CalendarEvent)
        .populate_existing()
        .all()
    )
    if not events or event.id not in {item.id for item in events}:
        raise CalendarEventValidationError("A ocorrência não pertence à série indicada.")
    # Autoriza a série completa antes de alterar linhas ou registar auditoria:
    # uma ocorrência pode ter sido movida individualmente para outro projeto.
    _ensure_series_visible(ctx, events)
    if any(
        not can_manage_calendar_event(ctx, occurrence.project if occurrence.project_id else None)
        for occurrence in events
    ):
        raise PermissionError("Sem permissão para editar todas as ocorrências desta série.")

    old_start = normalize_calendar_instant(event.starts_at).astimezone(LISBON)
    old_end = normalize_calendar_instant(event.ends_at).astimezone(LISBON)
    if "starts_at" in changes and changes["starts_at"] is None:
        raise CalendarEventValidationError("starts_at não pode ser null.")
    starts_at_supplied = "starts_at" in changes
    ends_at_supplied = "ends_at" in changes
    candidate_start = normalize_calendar_instant(
        changes["starts_at"] if starts_at_supplied else event.starts_at
    ).astimezone(LISBON)
    if ends_at_supplied:
        if changes["ends_at"] is None:
            raise CalendarEventValidationError("ends_at não pode ser null.")
        candidate_end = normalize_calendar_instant(changes["ends_at"]).astimezone(LISBON)
    elif starts_at_supplied:
        candidate_end_wall = candidate_start.replace(tzinfo=None) + (
            old_end.replace(tzinfo=None) - old_start.replace(tzinfo=None)
        )
        candidate_end = _resolve_lisbon_wall_clock(candidate_end_wall, fold=old_end.fold)
    else:
        candidate_end = None

    occurrence_times: list[tuple[dt.datetime, dt.datetime]] | None = None
    new_start_date: dt.date | None = None
    new_until_date: dt.date | None = None
    schedule: dict[str, object] | None = None
    if starts_at_supplied:
        occurrence_index = event.series_occurrence_index
        if occurrence_index is None:
            raise CalendarEventValidationError("A série contém uma ocorrência inválida.")
        scheduled_selected_date = series.starts_on + dt.timedelta(days=7 * occurrence_index)
        # Só um starts_at explícito pode deslocar a série. Uma ocorrência
        # movida individualmente não altera o calendário-base ao editar o título.
        date_shift = (candidate_start.date() - scheduled_selected_date).days
        new_start_date = series.starts_on + dt.timedelta(days=date_shift)
        new_until_date = series.until_date + dt.timedelta(days=date_shift)
        assert candidate_end is not None
        candidate_end_local = candidate_end.astimezone(LISBON)
        first_start_wall = dt.datetime.combine(new_start_date, candidate_start.time().replace(tzinfo=None))
        first_end_offset = (candidate_end_local.date() - candidate_start.date()).days
        first_end_wall = dt.datetime.combine(
            new_start_date + dt.timedelta(days=first_end_offset),
            candidate_end_local.time().replace(tzinfo=None),
        )
        first_start = _resolve_lisbon_wall_clock(first_start_wall, fold=candidate_start.fold)
        first_end = _resolve_lisbon_wall_clock(first_end_wall, fold=candidate_end_local.fold)
        schedule, occurrence_times = _weekly_occurrence_instants(
            starts_at=first_start,
            ends_at=first_end,
            until_date=new_until_date,
        )
        if len(occurrence_times) != series.occurrence_count:
            raise CalendarEventValidationError("A edição alteraria o número de ocorrências da série.")
    elif ends_at_supplied:
        assert candidate_end is not None
        end_day_offset = (candidate_end.date() - candidate_start.date()).days
        end_time = candidate_end.time().replace(tzinfo=None)
        occurrence_times = []
        for occurrence in events:
            occurrence_start = normalize_calendar_instant(occurrence.starts_at)
            occurrence_start_local = occurrence_start.astimezone(LISBON)
            end_wall = dt.datetime.combine(
                occurrence_start_local.date() + dt.timedelta(days=end_day_offset), end_time
            )
            occurrence_end = _resolve_lisbon_wall_clock(end_wall, fold=candidate_end.fold)
            if occurrence_end <= occurrence_start:
                raise CalendarEventValidationError(
                    "A hora de fim tem de ser posterior à hora de início em todas as ocorrências da série."
                )
            occurrence_times.append((occurrence_start, occurrence_end))

    common_changes = {
        key: value for key, value in changes.items() if key not in {"starts_at", "ends_at"}
    }
    # All rows are updated in one transaction. The series is locked on engines
    # that support row locks; SQLite serializes this write at transaction start.
    for occurrence in events:
        occurrence_changes = dict(common_changes)
        if occurrence_times is not None:
            index = occurrence.series_occurrence_index
            if index is None or index >= len(occurrence_times):
                raise CalendarEventValidationError("A série contém uma ocorrência inválida.")
            new_start, new_end = occurrence_times[index]
            occurrence_changes.update({"starts_at": new_start, "ends_at": new_end})
        _apply_calendar_event_changes(
            db,
            event=occurrence,
            changes=occurrence_changes,
            ctx=ctx,
        )

    # O novo âmbito (projeto/participantes) também tem de continuar visível.
    _ensure_series_visible(ctx, events)

    if schedule is not None:
        assert new_start_date is not None and new_until_date is not None
        series.starts_on = new_start_date
        series.until_date = new_until_date
        series.starts_at_local = str(schedule["starts_at_local"])
        series.ends_day_offset = int(schedule["ends_day_offset"])
        series.ends_at_local = str(schedule["ends_at_local"])
        series.starts_fold = int(schedule["starts_fold"])
        series.ends_fold = int(schedule["ends_fold"])
    elif ends_at_supplied:
        assert candidate_end is not None
        series.ends_day_offset = (candidate_end.date() - candidate_start.date()).days
        series.ends_at_local = candidate_end.strftime("%H:%M")
        series.ends_fold = candidate_end.fold
    db.commit()
    db.refresh(event)
    visible_event = get_visible_event(db, ctx, event.id)
    if visible_event is None:
        raise PermissionError("Sem permissão para ver a ocorrência atualizada.")
    return visible_event


def cancel_calendar_event(
    db: Session, *, event: CalendarEvent, ctx: AuthContext, whole_series: bool = False
) -> CalendarEvent:
    if whole_series:
        if event.series_id is None:
            raise CalendarEventValidationError("Este evento não pertence a uma série semanal.")
        series = _lock_calendar_series(db, event.series_id)
        if series is None:
            raise CalendarEventValidationError("A série semanal já não está disponível.")
        locked_event = _lock_calendar_event(db, event.id)
        if locked_event is None or locked_event.series_id != series.id:
            raise CalendarEventValidationError("A ocorrência já não pertence à série semanal.")
        events = (
            db.query(CalendarEvent)
            .options(joinedload(CalendarEvent.project), selectinload(CalendarEvent.assignees))
            .filter(CalendarEvent.series_id == series.id)
            .order_by(CalendarEvent.series_occurrence_index)
            .with_for_update(of=CalendarEvent)
            .populate_existing()
            .all()
        )
        if not events or locked_event.id not in {row.id for row in events}:
            raise CalendarEventValidationError("A ocorrência já não pertence à série semanal.")
        # Authorize the complete operation before changing rows or appending
        # audit entries. The series then commits or rolls back as one unit.
        _ensure_series_visible(ctx, events)
        for occurrence in events:
            occurrence_project = occurrence.project if occurrence.project_id else None
            if not can_manage_calendar_event(ctx, occurrence_project):
                raise PermissionError("Sem permissão para cancelar todas as ocorrências desta série.")

        for occurrence in events:
            old_values = _calendar_event_audit_values(occurrence)
            occurrence.status = "cancelado"
            _record_calendar_event_audit(
                db,
                event=occurrence,
                ctx=ctx,
                action="cancel",
                old_values=old_values,
                new_values=_calendar_event_audit_values(occurrence),
            )
        event = locked_event
    else:
        initial_series_id = event.series_id
        if initial_series_id is not None and _lock_calendar_series(db, initial_series_id) is None:
            raise CalendarEventValidationError("A série semanal já não está disponível.")
        locked_event = _lock_calendar_event(db, event.id)
        if locked_event is None or locked_event.series_id != initial_series_id:
            raise CalendarEventValidationError("O evento já não está disponível para cancelamento.")
        project = locked_event.project if locked_event.project_id else None
        if not can_manage_calendar_event(ctx, project):
            raise PermissionError("Sem permissão para cancelar este evento de calendário.")
        event = locked_event
        old_values = _calendar_event_audit_values(event)
        event.status = "cancelado"
        _record_calendar_event_audit(
            db,
            event=event,
            ctx=ctx,
            action="cancel",
            old_values=old_values,
            new_values=_calendar_event_audit_values(event),
        )
    db.commit()
    db.refresh(event)
    return get_visible_event(db, ctx, event.id) or event


# --- preferências ------------------------------------------------------------


def _preference_payload(row: UserPlanningPreference | None) -> dict[str, object]:
    if row is None or row.view not in PLANNING_VIEWS:
        return {"view": "month", "hide_weekends": False}
    return {"view": row.view, "hide_weekends": bool(row.hide_weekends)}


def get_planning_preferences(db: Session, ctx: AuthContext) -> dict[str, object]:
    row = (
        db.query(UserPlanningPreference)
        .filter(UserPlanningPreference.user_id == ctx.user.id)
        .one_or_none()
    )
    return _preference_payload(row)


def update_planning_preferences(
    db: Session, ctx: AuthContext, changes: dict[str, object]
) -> dict[str, object]:
    if "view" in changes:
        view = changes["view"]
        if view is None or view not in PLANNING_VIEWS:
            raise PlanningPreferenceValidationError("view deve ser month, week ou list.")
    if "hide_weekends" in changes and changes["hide_weekends"] is None:
        raise PlanningPreferenceValidationError("hide_weekends não pode ser null.")

    try:
        row = (
            db.query(UserPlanningPreference)
            .filter(UserPlanningPreference.user_id == ctx.user.id)
            .one_or_none()
        )
        if row is None:
            row = UserPlanningPreference(user_id=ctx.user.id, view="month", hide_weekends=False)
            db.add(row)
        if "view" in changes:
            row.view = str(changes["view"])
        if "hide_weekends" in changes:
            row.hide_weekends = bool(changes["hide_weekends"])
        db.commit()
        db.refresh(row)
    except SQLAlchemyError as exc:
        db.rollback()
        raise PlanningPreferenceValidationError("Não foi possível guardar a preferência de planeamento.") from exc
    return _preference_payload(row)


# --- projeção do Processo ----------------------------------------------------


def _as_lisbon(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=LISBON)
    return value.astimezone(LISBON)


def _lisbon_day_range(start: dt.date, end: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """Intervalo [início do primeiro dia, início do dia seguinte] em Lisboa.

    Construir os dois midnights com ZoneInfo, em vez de somar 24h, conserva a
    mudança de hora Europe/Lisbon no intervalo pedido.
    """
    return (
        dt.datetime.combine(start, dt.time.min, tzinfo=LISBON),
        dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min, tzinfo=LISBON),
    )


def _process_category(phase_code: str | None) -> str:
    # Códigos do catálogo são estáveis; os títulos reais não entram nesta regra.
    if phase_code in {"visita", "visita_tecnica"}:
        return "technical_visit"
    if phase_code in {"comissionamento", "commissioning"}:
        return "commissioning"
    if phase_code in {"inspecao_final", "final_inspection"}:
        return "final_inspection"
    if phase_code in {"obra", "entrada_obra", "work"}:
        return "work"
    if phase_code in {"pendencia", "pending"}:
        return "pending"
    return "other"


def _category_metadata(category: str) -> tuple[str, str]:
    return CALENDAR_EVENT_CATEGORIES.get(category, CALENDAR_EVENT_CATEGORIES["other"])


def _role_holders(
    db: Session, role_codes: set[str]
) -> dict[str, _ResponsiblePeople]:
    if not role_codes:
        return {}
    rows = (
        db.query(Role.code, Person.id, Person.display_name)
        .join(UserRole, UserRole.role_id == Role.id)
        .join(User, User.id == UserRole.user_id)
        .join(Person, Person.id == User.person_id)
        .filter(Role.code.in_(role_codes), User.is_active.is_(True), Person.is_active.is_(True))
        .order_by(Person.display_name, Person.id)
        .all()
    )
    result: dict[str, _ResponsiblePeople] = {}
    for code, person_id, name in rows:
        previous = result.setdefault(code, _ResponsiblePeople([], []))
        if person_id not in previous.ids:
            result[code] = _ResponsiblePeople(
                [*previous.ids, person_id], [*previous.names, name]
            )
    return result


def _stage_responsible(
    stage: WorkflowStage,
    project: Project,
    *,
    role_holders: dict[str, _ResponsiblePeople],
    support_ids_by_pm: dict[uuid.UUID, uuid.UUID],
    support_names: dict[uuid.UUID, str],
) -> _ResponsiblePeople:
    rule = stage.responsible_rule
    if rule == "role":
        return role_holders.get(stage.responsible_role_code or "", _ResponsiblePeople([], []))
    if rule == "pm":
        return (
            _ResponsiblePeople([project.pm_person_id], [project.pm.display_name])
            if project.pm_person_id is not None and project.pm is not None
            else _ResponsiblePeople([], [])
        )
    if rule == "support_delegate":
        support_id = support_ids_by_pm.get(project.pm_person_id) if project.pm_person_id else None
        if support_id is not None and support_id in support_names:
            return _ResponsiblePeople([support_id], [support_names[support_id]])
        if project.pm_person_id is not None and project.pm is not None:
            return _ResponsiblePeople([project.pm_person_id], [project.pm.display_name])
        return _ResponsiblePeople([], [])
    if rule == "installer":
        name = project.installer.name if project.installer is not None else None
        return _ResponsiblePeople([], [name] if name else [])
    if rule == "team_leader":
        names: list[str] = []
        for assignment in project.team_assignments:
            name = assignment.team.leader_name if assignment.team is not None else None
            if name and name not in names:
                names.append(name)
        if not names and project.installer_team is not None and project.installer_team.leader_name:
            names.append(project.installer_team.leader_name)
        return _ResponsiblePeople([], names)
    return _ResponsiblePeople([], [])


def _projection_projects(
    db: Session, ctx: AuthContext, project_id: uuid.UUID | None
) -> list[Project]:
    query = visible_projects_query(db, ctx).filter(Project.start_date.is_not(None)).options(
        joinedload(Project.pm),
        joinedload(Project.installer),
        joinedload(Project.installer_team),
        selectinload(Project.team_assignments).joinedload(ProjectTeamAssignment.team),
    )
    # A requested hidden project becomes an empty read.
    if project_id is not None:
        query = query.filter(Project.id == project_id)
    return query.order_by(Project.start_date, Project.id).all()


def list_process_calendar_events(
    db: Session,
    ctx: AuthContext,
    *,
    project_id: uuid.UUID | None = None,
    assigned_to_person_id: uuid.UUID | None = None,
    mine_only: bool = False,
    category: str | None = None,
    starts_from: dt.datetime | None = None,
    starts_to: dt.datetime | None = None,
) -> list[dict[str, object]]:
    if category is not None and category not in CALENDAR_EVENT_CATEGORY_CODES:
        raise CalendarEventValidationError("Categoria de evento desconhecida.")
    from_boundary = _as_lisbon(starts_from)
    to_boundary = _as_lisbon(starts_to)
    if from_boundary is not None and to_boundary is not None and to_boundary < from_boundary:
        raise CalendarEventValidationError("O fim da janela não pode ser anterior ao início.")

    phases = (
        db.query(Phase)
        .options(selectinload(Phase.stages).selectinload(WorkflowStage.subtasks))
        .order_by(Phase.sort_order)
        .all()
    )
    stage_rows = [(phase.code, stage) for phase in phases for stage in sorted(phase.stages, key=lambda item: item.sort_order)]
    role_codes = {
        stage.responsible_role_code
        for _, stage in stage_rows
        if stage.responsible_rule == "role" and stage.responsible_role_code
    }
    role_holders = _role_holders(db, role_codes)
    projects = _projection_projects(db, ctx, project_id)
    pm_ids = [project.pm_person_id for project in projects if project.pm_person_id is not None]
    delegation_rows = (
        db.query(SupportDelegation)
        .filter(SupportDelegation.pm_person_id.in_(pm_ids)).all()
        if pm_ids
        else []
    )
    support_ids_by_pm = {row.pm_person_id: row.support_person_id for row in delegation_rows}
    support_ids = list(set(support_ids_by_pm.values()))
    support_names = (
        {
            person.id: person.display_name
            for person in db.query(Person).filter(Person.id.in_(support_ids), Person.is_active.is_(True)).all()
        }
        if support_ids
        else {}
    )

    result: list[dict[str, object]] = []
    for project in projects:
        assert project.start_date is not None
        for phase_code, stage in stage_rows:
            # Só uma etapa com os dois offsets tem uma janela factual. Uma
            # subtarefa nunca recebe uma data artificial nesta projeção.
            if stage.planned_start_offset_days is None or stage.planned_end_offset_days is None:
                continue
            planned_start = business_day(project.start_date, stage.planned_start_offset_days)
            planned_end = business_day(project.start_date, stage.planned_end_offset_days)
            starts_at, ends_at = _lisbon_day_range(planned_start, planned_end)
            if from_boundary is not None and ends_at < from_boundary:
                continue
            if to_boundary is not None and starts_at > to_boundary:
                continue
            event_category = _process_category(phase_code)
            if category is not None and event_category != category:
                continue
            responsible = _stage_responsible(
                stage,
                project,
                role_holders=role_holders,
                support_ids_by_pm=support_ids_by_pm,
                support_names=support_names,
            )
            if assigned_to_person_id is not None and assigned_to_person_id not in responsible.ids:
                continue
            if mine_only and ctx.person_id not in responsible.ids:
                continue
            source_id = uuid.uuid5(
                _PROCESS_EVENT_NAMESPACE,
                f"{project.id}:{stage.id}:{starts_at.isoformat()}:{ends_at.isoformat()}",
            )
            category_label, category_color = _category_metadata(event_category)
            result.append(
                {
                    "id": source_id,
                    "visit_id": None,
                    "project_id": project.id,
                    "task_id": None,
                    "assigned_to_person_id": responsible.ids[0] if responsible.ids else None,
                    "assigned_to_person_ids": responsible.ids,
                    "title": stage.title,
                    "category": event_category,
                    "starts_at": starts_at,
                    "ends_at": ends_at,
                    "status": "projected",
                    "graph_event_id": None,
                    "created_at": starts_at,
                    "project_name": project.name,
                    "project_url": f"/projects/{project.id}?tab=processo",
                    "task_title": None,
                    "assigned_to_display_name": responsible.names[0] if responsible.names else None,
                    "assigned_to_display_names": responsible.names,
                    "process_stage_id": stage.id,
                    "process_stage_code": stage.code,
                    "process_stage_title": stage.title,
                    "process_subtask_id": None,
                    "process_subtask_code": None,
                    "process_subtask_title": None,
                    "responsible_person_ids": responsible.ids,
                    "responsible_display_names": responsible.names,
                    "source": "process",
                    "source_id": source_id,
                    "category_label": category_label,
                    "category_color": category_color,
                    "can_manage": False,
                }
            )
    result.sort(key=lambda event: (event["starts_at"], str(event["id"])))
    return result


def list_process_options(
    db: Session, ctx: AuthContext, project_id: uuid.UUID
) -> list[dict[str, object]] | None:
    project = (
        db.query(Project)
        .filter(Project.id == project_id)
        .one_or_none()
    )
    if project is None:
        return None
    # build_project_process already applies the real date/responsibility
    # resolver for one authorized project; no dates are invented for subtasks.
    from app.security.permissions import can_view_project

    if not can_view_project(ctx, project):
        return None
    process = build_project_process(db, project, ctx, dt.date.today())
    options: list[dict[str, object]] = []
    for phase in process.phases:
        for stage in phase.stages:
            options.append(
                {
                    "project_id": project.id,
                    "stage_id": stage.id,
                    "stage_code": stage.code,
                    "stage_title": stage.title,
                    "planned_start": stage.planned_start,
                    "planned_end": stage.planned_end,
                    "responsible_person_ids": (
                        [project.pm_person_id]
                        if stage.responsible.rule == "pm" and project.pm_person_id is not None
                        else []
                    ),
                    "responsible_display_names": stage.responsible.names,
                    "subtasks": [
                        {"id": subtask.id, "code": subtask.code, "title": subtask.title}
                        for subtask in stage.subtasks
                    ],
                }
            )
    return options
