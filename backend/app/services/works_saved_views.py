"""Serviço de vistas pessoais guardadas do Calendário de obras."""
from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import cast

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.installer import Installer, InstallerTeam
from app.models.people import Person
from app.models.project import Project, ProjectTeamAssignment
from app.models.works_saved_views import WorksCalendarSavedView
from app.security.permissions import (
    AuthContext,
    can_view_installers,
    is_installer_readonly_scope,
)
from app.services.project_lifecycle import LIFECYCLE_STATUS_CODES
from app.services.projects import visible_projects_query

WORKS_SAVED_VIEW_ZOOMS: frozenset[str] = frozenset(
    {"weeks", "months", "quarters", "month_days"}
)
SAVED_VIEW_FILTER_FIELDS = (
    "zoom",
    "lifecycle_status",
    "pm_person_id",
    "installer_id",
    "team_id",
    "show_idle",
)


class SavedViewPermissionError(PermissionError):
    """A conta não pode ver o calendário de obras."""


class SavedViewNotFoundError(LookupError):
    """A vista não existe ou pertence a outra conta."""


class SavedViewValidationError(ValueError):
    """Nome ou filtros incompatíveis com o Calendário de obras."""


class SavedViewDuplicateError(ValueError):
    """O utilizador já tem uma vista com esse nome."""


class SavedViewStorageError(RuntimeError):
    """Falha de persistência de uma vista guardada."""


def require_saved_views_permission(ctx: AuthContext) -> None:
    """Aplica no serviço o mesmo âmbito de /api/works/calendar."""
    if not (can_view_installers(ctx) or ctx.has_permission("works_calendar.view_assigned_installer")):
        raise SavedViewPermissionError(
            "Sem permissão para ver o calendário de obras."
        )


def require_saved_views_write_permission(ctx: AuthContext) -> None:
    require_saved_views_permission(ctx)
    if is_installer_readonly_scope(ctx) or not ctx.has_permission("calendar.view"):
        raise SavedViewPermissionError("O papel externo tem acesso somente de leitura.")


def _default_filters() -> dict[str, object]:
    return {
        "zoom": "month_days",
        "lifecycle_status": [],
        "pm_person_id": None,
        "installer_id": None,
        "team_id": None,
        "show_idle": False,
    }


def _row_payload(row: WorksCalendarSavedView) -> dict[str, object]:
    return {
        "id": row.id,
        "name": row.name,
        "zoom": row.zoom,
        "lifecycle_status": list(row.lifecycle_status),
        "pm_person_id": row.pm_person_id,
        "installer_id": row.installer_id,
        "team_id": row.team_id,
        "show_idle": bool(row.show_idle),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _filter_payload(row: WorksCalendarSavedView) -> dict[str, object]:
    payload = _row_payload(row)
    return {field: payload[field] for field in SAVED_VIEW_FILTER_FIELDS}


def _scoped_row_payload(db: Session, ctx: AuthContext, row: WorksCalendarSavedView) -> dict[str, object]:
    payload = _row_payload(row)
    visible_pm_ids, visible_installer_ids, visible_team_ids = _visible_reference_ids(db, ctx)
    if payload["pm_person_id"] not in visible_pm_ids:
        payload["pm_person_id"] = None
    if payload["installer_id"] not in visible_installer_ids:
        payload["installer_id"] = None
    if payload["team_id"] not in visible_team_ids:
        payload["team_id"] = None
    return payload


def _normalise_name(value: object) -> str:
    if not isinstance(value, str):
        raise SavedViewValidationError("O nome da vista é inválido.")
    name = value.strip()
    if not name:
        raise SavedViewValidationError("O nome da vista não pode ficar vazio.")
    if len(name) > 120:
        raise SavedViewValidationError(
            "O nome da vista não pode exceder 120 caracteres."
        )
    return name


def _dedupe_statuses(values: object) -> list[str]:
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise SavedViewValidationError(
            "Filtro de estado do ciclo de vida inválido."
        )
    if any(value not in LIFECYCLE_STATUS_CODES for value in values):
        raise SavedViewValidationError(
            "Filtro de estado do ciclo de vida inválido."
        )
    return list(dict.fromkeys(values))


def _visible_reference_ids(
    db: Session, ctx: AuthContext
) -> tuple[set[uuid.UUID], set[uuid.UUID], set[uuid.UUID]]:
    """Referências alcançáveis pelo calendário no âmbito da conta."""
    if is_installer_readonly_scope(ctx):
        if not ctx.active_installer_ids:
            return set(), set(), set()
        team_ids = {
            value
            for (value,) in db.query(InstallerTeam.id)
            .filter(InstallerTeam.installer_id.in_(ctx.active_installer_ids))
            .all()
            if value is not None
        }
        return set(), set(ctx.active_installer_ids), team_ids

    projects = visible_projects_query(db, ctx).filter(Project.is_active.is_(True))
    pm_ids = {
        value
        for (value,) in projects.with_entities(Project.pm_person_id).distinct().all()
        if value is not None
    }
    installer_ids = {
        value
        for (value,) in projects.with_entities(Project.installer_id).distinct().all()
        if value is not None
    }
    team_ids = {
        value
        for (value,) in projects.with_entities(Project.installer_team_id).distinct().all()
        if value is not None
    }
    assignment_rows = (
        db.query(ProjectTeamAssignment.team_id)
        .join(Project, Project.id == ProjectTeamAssignment.project_id)
        .filter(Project.is_active.is_(True))
        .filter(Project.id.in_(projects.with_entities(Project.id)))
        .distinct()
        .all()
    )
    team_ids.update(value for (value,) in assignment_rows if value is not None)
    return pm_ids, installer_ids, team_ids


def _validate_person(
    db: Session,
    ctx: AuthContext,
    person_id: uuid.UUID,
    visible_pm_ids: set[uuid.UUID],
) -> None:
    person = (
        db.query(Person)
        .filter(Person.id == person_id, Person.is_active.is_(True))
        .one_or_none()
    )
    allowed = ctx.has_permission("project.view_all") or person_id in visible_pm_ids
    if person is None or not allowed:
        raise SavedViewValidationError("Filtro de pessoa inválido.")


def _validate_installer(
    db: Session,
    ctx: AuthContext,
    installer_id: uuid.UUID,
    visible_installer_ids: set[uuid.UUID],
) -> Installer:
    installer = (
        db.query(Installer)
        .filter(Installer.id == installer_id, Installer.is_active.is_(True))
        .one_or_none()
    )
    allowed = (
        ctx.has_permission("project.view_all")
        or installer_id in visible_installer_ids
    )
    if installer is None or not allowed:
        raise SavedViewValidationError("Filtro de instalador inválido.")
    return installer


def _validate_team(
    db: Session,
    ctx: AuthContext,
    team_id: uuid.UUID,
    visible_team_ids: set[uuid.UUID],
) -> InstallerTeam:
    team = (
        db.query(InstallerTeam)
        .filter(InstallerTeam.id == team_id, InstallerTeam.is_active.is_(True))
        .one_or_none()
    )
    installer = None
    if team is not None:
        installer = (
            db.query(Installer)
            .filter(
                Installer.id == team.installer_id,
                Installer.is_active.is_(True),
            )
            .one_or_none()
        )
    allowed = ctx.has_permission("project.view_all") or team_id in visible_team_ids
    if team is None or installer is None or not allowed:
        raise SavedViewValidationError("Filtro de equipa inválido.")
    return team


def _validate_final_state(db: Session, ctx: AuthContext, state: dict[str, object]) -> None:
    zoom = state.get("zoom")
    if not isinstance(zoom, str) or zoom not in WORKS_SAVED_VIEW_ZOOMS:
        raise SavedViewValidationError("Escala do calendário inválida.")

    state["lifecycle_status"] = _dedupe_statuses(state.get("lifecycle_status"))
    show_idle = state.get("show_idle")
    if type(show_idle) is not bool:
        raise SavedViewValidationError("show_idle tem de ser um booleano.")

    pm_person_id = state.get("pm_person_id")
    installer_id = state.get("installer_id")
    team_id = state.get("team_id")
    for value in (pm_person_id, installer_id, team_id):
        if value is not None and not isinstance(value, uuid.UUID):
            raise SavedViewValidationError("Filtro de referência inválido.")

    visible_pm_ids, visible_installer_ids, visible_team_ids = _visible_reference_ids(
        db, ctx
    )
    if pm_person_id is not None:
        _validate_person(db, ctx, pm_person_id, visible_pm_ids)
    if installer_id is not None:
        _validate_installer(db, ctx, installer_id, visible_installer_ids)

    team = None
    if team_id is not None:
        team = _validate_team(db, ctx, team_id, visible_team_ids)

    if team_id is not None and installer_id is None:
        raise SavedViewValidationError(
            "Os filtros de instalador e equipa não são compatíveis."
        )
    if installer_id is not None and team_id is not None and (
        team is None or team.installer_id != installer_id
    ):
        raise SavedViewValidationError(
            "Os filtros de instalador e equipa não são compatíveis."
        )


def _get_owned(
    db: Session, ctx: AuthContext, saved_view_id: uuid.UUID
) -> WorksCalendarSavedView:
    row = (
        db.query(WorksCalendarSavedView)
        .filter(
            WorksCalendarSavedView.id == saved_view_id,
            WorksCalendarSavedView.user_id == ctx.user.id,
        )
        .one_or_none()
    )
    if row is None:
        raise SavedViewNotFoundError("Vista guardada não encontrada.")
    return row


def _ensure_unique_name(
    db: Session,
    ctx: AuthContext,
    name: str,
    *,
    excluding_id: uuid.UUID | None = None,
) -> None:
    query = db.query(WorksCalendarSavedView).filter(
        WorksCalendarSavedView.user_id == ctx.user.id,
        WorksCalendarSavedView.name == name,
    )
    if excluding_id is not None:
        query = query.filter(WorksCalendarSavedView.id != excluding_id)
    if query.first() is not None:
        raise SavedViewDuplicateError("Já existe uma vista guardada com esse nome.")


def _persist_new(db: Session, row: WorksCalendarSavedView) -> dict[str, object]:
    try:
        db.add(row)
        db.flush()
        db.commit()
        db.refresh(row)
        return _row_payload(row)
    except IntegrityError as exc:
        db.rollback()
        raise SavedViewDuplicateError(
            "Já existe uma vista guardada com esse nome."
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise SavedViewStorageError(
            "Não foi possível guardar a vista do calendário de obras."
        ) from exc


def _persist_existing(db: Session, row: WorksCalendarSavedView) -> dict[str, object]:
    try:
        db.flush()
        db.commit()
        db.refresh(row)
        return _row_payload(row)
    except IntegrityError as exc:
        db.rollback()
        raise SavedViewDuplicateError(
            "Já existe uma vista guardada com esse nome."
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise SavedViewStorageError(
            "Não foi possível guardar a vista do calendário de obras."
        ) from exc


def list_saved_views(
    db: Session, ctx: AuthContext
) -> list[dict[str, object]]:
    require_saved_views_permission(ctx)
    rows = (
        db.query(WorksCalendarSavedView)
        .filter(WorksCalendarSavedView.user_id == ctx.user.id)
        .order_by(
            func.lower(WorksCalendarSavedView.name).asc(),
            WorksCalendarSavedView.name.asc(),
            WorksCalendarSavedView.id.asc(),
        )
        .all()
    )
    return [_scoped_row_payload(db, ctx, row) for row in rows]


def create_saved_view(
    db: Session, ctx: AuthContext, payload: Mapping[str, object]
) -> dict[str, object]:
    require_saved_views_write_permission(ctx)
    name = _normalise_name(payload.get("name"))
    state = _default_filters()
    state.update({field: payload[field] for field in SAVED_VIEW_FILTER_FIELDS if field in payload})
    _validate_final_state(db, ctx, state)
    _ensure_unique_name(db, ctx, name)
    row = WorksCalendarSavedView(
        user_id=ctx.user.id,
        name=name,
        zoom=cast(str, state["zoom"]),
        lifecycle_status=list(cast(list[str], state["lifecycle_status"])),
        pm_person_id=cast(uuid.UUID | None, state["pm_person_id"]),
        installer_id=cast(uuid.UUID | None, state["installer_id"]),
        team_id=cast(uuid.UUID | None, state["team_id"]),
        show_idle=cast(bool, state["show_idle"]),
    )
    return _persist_new(db, row)


def update_saved_view(
    db: Session,
    ctx: AuthContext,
    saved_view_id: uuid.UUID,
    changes: Mapping[str, object],
) -> dict[str, object]:
    require_saved_views_write_permission(ctx)
    row = _get_owned(db, ctx, saved_view_id)
    state = _filter_payload(row)
    state.update({field: changes[field] for field in SAVED_VIEW_FILTER_FIELDS if field in changes})
    _validate_final_state(db, ctx, state)

    if "name" in changes:
        name = _normalise_name(changes["name"])
    else:
        name = row.name
    _ensure_unique_name(db, ctx, name, excluding_id=row.id)

    row.name = name
    row.zoom = cast(str, state["zoom"])
    row.lifecycle_status = list(cast(list[str], state["lifecycle_status"]))
    row.pm_person_id = cast(uuid.UUID | None, state["pm_person_id"])
    row.installer_id = cast(uuid.UUID | None, state["installer_id"])
    row.team_id = cast(uuid.UUID | None, state["team_id"])
    row.show_idle = cast(bool, state["show_idle"])
    return _persist_existing(db, row)


def delete_saved_view(db: Session, ctx: AuthContext, saved_view_id: uuid.UUID) -> None:
    require_saved_views_write_permission(ctx)
    row = _get_owned(db, ctx, saved_view_id)
    try:
        db.delete(row)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise SavedViewStorageError(
            "Não foi possível apagar a vista do calendário de obras."
        ) from exc


def apply_saved_view(
    db: Session, ctx: AuthContext, saved_view_id: uuid.UUID
) -> dict[str, object]:
    require_saved_views_write_permission(ctx)
    row = _get_owned(db, ctx, saved_view_id)
    from app.services.works_preferences import update_works_preferences

    return update_works_preferences(db, ctx, _filter_payload(row))
