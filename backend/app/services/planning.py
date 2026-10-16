"""Calendário de planeamento local, com participantes e projeção do Processo.

Os eventos manuais continuam a ser dados persistidos em ``calendar_events``.
Os marcos do Processo são um read model determinístico: não criam tarefas nem
linhas em ``calendar_events`` e nunca são editáveis através das rotas de
escrita. Não há chamadas a Graph/Exchange nesta camada.
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Query, Session, joinedload, selectinload

from app.models.calendar import CalendarEvent
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


class CalendarEventValidationError(ValueError):
    """Erro de input existente; a rota devolve 400 para compatibilidade."""

    status_code = 400


class CalendarEventReferenceError(CalendarEventValidationError):
    """Referência inexistente/fora do âmbito; a API devolve 422."""

    status_code = 422


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


def _participant_condition(person_id: uuid.UUID):
    return or_(
        CalendarEvent.assigned_to_person_id == person_id,
        CalendarEvent.assignees.any(Person.id == person_id),
    )


def _project_scope_condition(ctx: AuthContext):
    conditions = []
    if ctx.has_permission("project.view_own"):
        conditions.append(Project.pm_person_id == ctx.person_id)
    if ctx.has_permission("project.view_delegated") and ctx.delegating_pm_ids:
        conditions.append(Project.pm_person_id.in_(ctx.delegating_pm_ids))
    conditions.extend(installer_project_scope_conditions(ctx))
    return conditions


def visible_events_query(db: Session, ctx: AuthContext) -> Query:
    """A visibilidade dos eventos é a união aditiva dos âmbitos de projeto.

    Um participante adicional nunca transforma um evento de projeto fora do
    âmbito num evento visível a Suporte. Só eventos sem projeto podem ser
    vistos por um perfil exclusivamente delegado quando esse perfil participa.
    """
    if not (ctx.has_permission("calendar.view") or ctx.has_permission("works_calendar.view_assigned_installer")):
        return db.query(CalendarEvent).filter(False)
    if ctx.has_permission("project.view_all"):
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
    if ctx.has_permission("project.view_all"):
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
            selectinload(CalendarEvent.assignees),
        )
        .filter(CalendarEvent.id == event_id)
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
    project = db.get(Project, project_id) if project_id is not None else None
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
    db.commit()
    db.refresh(event)
    return get_visible_event(db, ctx, event.id) or event


def update_calendar_event(
    db: Session, *, event: CalendarEvent, changes: dict, ctx: AuthContext
) -> CalendarEvent:
    old_project = event.project if event.project_id else None
    if not can_manage_calendar_event(ctx, old_project):
        raise PermissionError("Sem permissão para editar este evento de calendário.")

    new_project_id = changes.get("project_id", event.project_id)
    new_project = db.get(Project, new_project_id) if new_project_id is not None else None
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

    db.commit()
    db.refresh(event)
    return get_visible_event(db, ctx, event.id) or event


def cancel_calendar_event(db: Session, *, event: CalendarEvent, ctx: AuthContext) -> CalendarEvent:
    project = event.project if event.project_id else None
    if not can_manage_calendar_event(ctx, project):
        raise PermissionError("Sem permissão para cancelar este evento de calendário.")
    event.status = "cancelado"
    db.commit()
    db.refresh(event)
    return event


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
    query = (
        db.query(Project)
        .filter(Project.start_date.is_not(None))
        .options(
            joinedload(Project.pm),
            joinedload(Project.installer),
            joinedload(Project.installer_team),
            selectinload(Project.team_assignments).joinedload(ProjectTeamAssignment.team),
        )
    )
    # Reuse the same SQL project scope without querying each project through
    # build_project_process. A requested hidden project becomes an empty read.
    if not ctx.has_permission("project.view_all"):
        conditions = _project_scope_condition(ctx)
        if not conditions:
            return []
        query = query.filter(or_(*conditions))
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
