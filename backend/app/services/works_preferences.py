"""Leitura e escrita da preferência persistente do Calendário de obras."""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import cast

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.identity import User
from app.models.installer import Installer, InstallerTeam
from app.models.people import Person
from app.models.project import Project, ProjectTeamAssignment
from app.models.works_preferences import UserWorksPreference
from app.security.permissions import AuthContext, is_installer_readonly_scope
from app.services.project_lifecycle import LIFECYCLE_STATUS_CODES
from app.services.projects import visible_projects_query

WORKS_PREFERENCE_ZOOMS: frozenset[str] = frozenset(
    {"weeks", "months", "quarters", "month_days"}
)
DEFAULT_WORKS_PREFERENCE: dict[str, object] = {
    "zoom": "month_days",
    "lifecycle_status": [],
    "pm_person_id": None,
    "installer_id": None,
    "team_id": None,
    "show_idle": False,
}


class WorksPreferenceValidationError(ValueError):
    """Payload ou estado final incompatível com o Calendário de obras."""


class WorksPreferenceStorageError(RuntimeError):
    """Falha de persistência ao criar/atualizar a preferência."""


def _default_payload() -> dict[str, object]:
    # Cada resposta recebe uma lista independente.
    return {**DEFAULT_WORKS_PREFERENCE, "lifecycle_status": []}


def _preference_payload(row: UserWorksPreference | None) -> dict[str, object]:
    if row is None:
        return _default_payload()
    return {
        "zoom": row.zoom,
        "lifecycle_status": list(row.lifecycle_status),
        "pm_person_id": row.pm_person_id,
        "installer_id": row.installer_id,
        "team_id": row.team_id,
        "show_idle": bool(row.show_idle),
    }


def get_works_preferences(db: Session, ctx: AuthContext) -> dict[str, object]:
    """Lê apenas a linha do utilizador; não cria defaults nem faz rollback."""
    row = (
        db.query(UserWorksPreference)
        .filter(UserWorksPreference.user_id == ctx.user.id)
        .one_or_none()
    )
    payload = _preference_payload(row)
    visible_pm_ids, visible_installer_ids, visible_team_ids = _visible_reference_ids(db, ctx)
    if payload["pm_person_id"] not in visible_pm_ids:
        payload["pm_person_id"] = None
    if payload["installer_id"] not in visible_installer_ids:
        payload["installer_id"] = None
    if payload["team_id"] not in visible_team_ids:
        payload["team_id"] = None
    return payload


def _dedupe_statuses(values: Iterable[str]) -> list[str]:
    statuses = list(values)
    if any(status not in LIFECYCLE_STATUS_CODES for status in statuses):
        # Não devolver a lista de códigos inválidos: o catálogo é uma
        # validação de contrato, não uma sonda de dados.
        raise WorksPreferenceValidationError("Filtro de estado do ciclo de vida inválido.")
    return list(dict.fromkeys(statuses))


def _visible_reference_ids(db: Session, ctx: AuthContext) -> tuple[set[uuid.UUID], set[uuid.UUID], set[uuid.UUID]]:
    """IDs de PM/instalador/equipa que o calendário efetivo pode alcançar."""
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
        db.query(ProjectTeamAssignment.installer_id, ProjectTeamAssignment.team_id)
        .join(Project, Project.id == ProjectTeamAssignment.project_id)
        .filter(Project.is_active.is_(True))
        .filter(Project.id.in_(projects.with_entities(Project.id)))
        .distinct()
        .all()
    )
    installer_ids.update(value for value, _team_id in assignment_rows if value is not None)
    team_ids.update(value for _installer_id, value in assignment_rows if value is not None)
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
        raise WorksPreferenceValidationError("Filtro de pessoa inválido.")


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
    allowed = ctx.has_permission("project.view_all") or installer_id in visible_installer_ids
    if installer is None or not allowed:
        raise WorksPreferenceValidationError("Filtro de instalador inválido.")
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
            .filter(Installer.id == team.installer_id, Installer.is_active.is_(True))
            .one_or_none()
        )
    allowed = ctx.has_permission("project.view_all") or team_id in visible_team_ids
    if team is None or installer is None or not allowed:
        raise WorksPreferenceValidationError("Filtro de equipa inválido.")
    return team


def _validate_final_state(db: Session, ctx: AuthContext, state: dict[str, object]) -> None:
    zoom = cast(str | None, state["zoom"])
    statuses = state["lifecycle_status"]
    if zoom is None or zoom not in WORKS_PREFERENCE_ZOOMS:
        raise WorksPreferenceValidationError("Escala do calendário inválida.")
    if not isinstance(statuses, list):
        raise WorksPreferenceValidationError("Filtro de estado do ciclo de vida inválido.")
    state["lifecycle_status"] = _dedupe_statuses(statuses)
    if state["show_idle"] is None or not isinstance(state["show_idle"], bool):
        raise WorksPreferenceValidationError("show_idle tem de ser um booleano.")

    pm_ids, installer_ids, team_ids = _visible_reference_ids(db, ctx)
    pm_person_id = cast(uuid.UUID | None, state["pm_person_id"])
    installer_id = cast(uuid.UUID | None, state["installer_id"])
    team_id = cast(uuid.UUID | None, state["team_id"])
    if pm_person_id is not None:
        _validate_person(db, ctx, pm_person_id, pm_ids)
    if installer_id is not None:
        _validate_installer(db, ctx, installer_id, installer_ids)
    team = None
    if team_id is not None:
        team = _validate_team(db, ctx, team_id, team_ids)

    # O filtro de equipa é guardado com o instalador correspondente para que
    # o estado persistido possa ser reaplicado sem uma relação ambígua.
    if team_id is not None and installer_id is None:
        raise WorksPreferenceValidationError(
            "Os filtros de instalador e equipa não são compatíveis."
        )
    if installer_id is not None and team_id is not None:
        if team is None or team.installer_id != installer_id:
            raise WorksPreferenceValidationError(
                "Os filtros de instalador e equipa não são compatíveis."
            )


def update_works_preferences(
    db: Session, ctx: AuthContext, changes: dict[str, object]
) -> dict[str, object]:
    """Valida e grava o estado completo numa única transação."""
    row = (
        db.query(UserWorksPreference)
        .filter(UserWorksPreference.user_id == ctx.user.id)
        .one_or_none()
    )
    state = _preference_payload(row)
    state.update(changes)
    _validate_final_state(db, ctx, state)

    if row is None:
        # A preference row does not exist yet, so it cannot be locked. Lock
        # the already-existing User row to serialize first creation, then
        # re-read the preference at READ COMMITTED after the lock is acquired.
        # The second validation is required because another creator may have
        # committed a state while this request waited.
        (
            db.query(User)
            .filter(User.id == ctx.user.id)
            .populate_existing()
            .with_for_update()
            .one()
        )
        row = (
            db.query(UserWorksPreference)
            .filter(UserWorksPreference.user_id == ctx.user.id)
            .populate_existing()
            .one_or_none()
        )
        if row is None:
            row = UserWorksPreference(user_id=ctx.user.id)
            db.add(row)
        else:
            state = _preference_payload(row)
            state.update(changes)
            _validate_final_state(db, ctx, state)
    row.zoom = str(state["zoom"])
    row.lifecycle_status = list(cast(list[str], state["lifecycle_status"]))
    row.pm_person_id = cast(uuid.UUID | None, state["pm_person_id"])
    row.installer_id = cast(uuid.UUID | None, state["installer_id"])
    row.team_id = cast(uuid.UUID | None, state["team_id"])
    row.show_idle = cast(bool, state["show_idle"])
    try:
        db.flush()
        response_payload = _preference_payload(row)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise WorksPreferenceStorageError(
            "Não foi possível guardar as preferências do calendário de obras."
        ) from exc
    return response_payload
