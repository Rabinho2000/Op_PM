"""Canonical service for personal Projects-list preferences and views."""
from __future__ import annotations

import copy
import uuid
from collections.abc import Mapping
from typing import cast

from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.identity import User
from app.models.people import Person
from app.models.project import Project
from app.models.project_list_views import ProjectListView, UserProjectListPreference
from app.security.permissions import AuthContext, is_installer_readonly_scope
from app.services.projects import visible_projects_query
from app.schemas.project_list_views import (
    PROJECT_LIST_DEFAULT_COLUMNS,
    ProjectListConfig,
)

PROJECT_LIST_DEFAULT_CONFIG: dict[str, object] = {
    "columns": list(PROJECT_LIST_DEFAULT_COLUMNS),
    "sort_by": "name",
    "sort_direction": "asc",
    "filters": {
        "search": "",
        "status": "",
        "lifecycle": [
            "on_hold_cliente",
            "preparacao",
            "construcao",
            "construido",
        ],
        "pm": "",
        "active": "active",
        "startFrom": "",
        "startTo": "",
    },
}


class ProjectListPermissionError(PermissionError):
    """The authenticated account cannot use the Projects-list settings API."""


class ProjectListNotFoundError(LookupError):
    """A view is absent or owned by another account."""


class ProjectListValidationError(ValueError):
    """A config, name, or scoped reference violates the closed contract."""


class ProjectListDuplicateError(ValueError):
    """An active view with the same account/name already exists."""


class ProjectListStorageError(RuntimeError):
    """A database failure while persisting project-list state."""


def require_project_list_permission(ctx: AuthContext) -> None:
    """Use project visibility capabilities, never a client-selected role.

    A pure assigned-installer account is intentionally rejected for this new
    personal-settings surface.  If that account also has a broad project
    capability, the existing additive permission semantics remain in force.
    """
    if is_installer_readonly_scope(ctx):
        raise ProjectListPermissionError("O canal externo tem acesso somente de leitura.")
    if not any(
        ctx.has_permission(code)
        for code in (
            "project.view_all",
            "project.view_own",
            "project.view_delegated",
            "project.view_assigned_installer",
        )
    ):
        raise ProjectListPermissionError("Sem permissão para ver a lista de Projetos.")


def _default_config() -> dict[str, object]:
    return cast(dict[str, object], copy.deepcopy(PROJECT_LIST_DEFAULT_CONFIG))


def _parse_config(config: object) -> dict[str, object]:
    try:
        parsed = ProjectListConfig.model_validate(config)
    except ValidationError as exc:
        raise ProjectListValidationError("Configuração da lista de Projetos inválida.") from exc
    return cast(dict[str, object], parsed.model_dump())


def _visible_pm_ids(db: Session, ctx: AuthContext) -> set[uuid.UUID]:
    rows = (
        visible_projects_query(db, ctx)
        .filter(Project.pm_person_id.is_not(None))
        .with_entities(Project.pm_person_id)
        .distinct()
        .all()
    )
    return {
        cast(uuid.UUID, value)
        for (value,) in rows
        if value is not None
    }


def _pm_is_reachable(db: Session, ctx: AuthContext, value: str) -> bool:
    try:
        pm_id = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        return False
    if pm_id in _visible_pm_ids(db, ctx):
        return True
    # A PM can keep a self-filter even while the current visible project set is
    # empty, provided the authenticated person is still an active Person.
    if pm_id == ctx.person_id and ctx.has_permission("project.view_own"):
        return (
            db.query(Person.id)
            .filter(Person.id == ctx.person_id, Person.is_active.is_(True))
            .one_or_none()
            is not None
        )
    return False


def _validate_config_for_write(
    db: Session, ctx: AuthContext, config: object
) -> dict[str, object]:
    payload = _parse_config(config)
    filters = cast(dict[str, object], payload["filters"])
    pm = cast(str, filters["pm"])
    if pm and not _pm_is_reachable(db, ctx, pm):
        raise ProjectListValidationError("O filtro pm está fora do âmbito visível.")
    return payload


def _scoped_config(db: Session, ctx: AuthContext, config: object) -> dict[str, object]:
    """Return a detached response copy; never redact the ORM JSON in place."""
    payload = _parse_config(config)
    filters = cast(dict[str, object], payload["filters"])
    pm = cast(str, filters["pm"])
    if pm and not _pm_is_reachable(db, ctx, pm):
        filters["pm"] = ""
    return payload


def _preference_payload(db: Session, ctx: AuthContext, row: UserProjectListPreference | None) -> dict[str, object]:
    if row is None:
        return {"config": _default_config()}
    return {"config": _scoped_config(db, ctx, row.config)}


def get_project_list_preferences(db: Session, ctx: AuthContext) -> dict[str, object]:
    require_project_list_permission(ctx)
    row = (
        db.query(UserProjectListPreference)
        .filter(UserProjectListPreference.user_id == ctx.user.id)
        .one_or_none()
    )
    return _preference_payload(db, ctx, row)


def put_project_list_preferences(
    db: Session, ctx: AuthContext, config: object
) -> dict[str, object]:
    require_project_list_permission(ctx)
    validated = _validate_config_for_write(db, ctx, config)
    row = (
        db.query(UserProjectListPreference)
        .filter(UserProjectListPreference.user_id == ctx.user.id)
        .one_or_none()
    )
    if row is None:
        # A preference row does not exist yet, so it cannot be locked. Lock
        # the already-existing User row to serialize first creation, then
        # re-read the preference at READ COMMITTED after the lock is acquired.
        # The second read also avoids relying on a stale identity-map result.
        (
            db.query(User)
            .filter(User.id == ctx.user.id)
            .populate_existing()
            .with_for_update()
            .one()
        )
        row = (
            db.query(UserProjectListPreference)
            .filter(UserProjectListPreference.user_id == ctx.user.id)
            .populate_existing()
            .one_or_none()
        )
        if row is None:
            row = UserProjectListPreference(user_id=ctx.user.id)
            db.add(row)
    row.config = validated
    response_payload = {"config": copy.deepcopy(validated)}
    try:
        db.flush()
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise ProjectListStorageError(
            "Não foi possível guardar as preferências da lista de Projetos."
        ) from exc
    return response_payload


def _normalise_name(value: object) -> str:
    if not isinstance(value, str):
        raise ProjectListValidationError("O nome da vista é inválido.")
    name = value.strip()
    if not name or len(name) > 120:
        raise ProjectListValidationError(
            "O nome da vista tem de ter entre 1 e 120 caracteres."
        )
    return name


def _get_owned_active_view(
    db: Session, ctx: AuthContext, view_id: uuid.UUID
) -> ProjectListView:
    row = (
        db.query(ProjectListView)
        .filter(
            ProjectListView.id == view_id,
            ProjectListView.user_id == ctx.user.id,
            ProjectListView.is_active.is_(True),
        )
        .one_or_none()
    )
    if row is None:
        raise ProjectListNotFoundError("Vista da lista de Projetos não encontrada.")
    return row


def _ensure_unique_name(
    db: Session,
    ctx: AuthContext,
    name: str,
    *,
    excluding_id: uuid.UUID | None = None,
) -> None:
    query = db.query(ProjectListView).filter(
        ProjectListView.user_id == ctx.user.id,
        ProjectListView.name == name,
        ProjectListView.is_active.is_(True),
    )
    if excluding_id is not None:
        query = query.filter(ProjectListView.id != excluding_id)
    if query.first() is not None:
        raise ProjectListDuplicateError("Já existe uma vista ativa com esse nome.")


def _view_payload(db: Session, ctx: AuthContext, row: ProjectListView) -> dict[str, object]:
    return {
        "id": row.id,
        "name": row.name,
        "config": _scoped_config(db, ctx, row.config),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def list_project_list_views(db: Session, ctx: AuthContext) -> list[dict[str, object]]:
    require_project_list_permission(ctx)
    rows = (
        db.query(ProjectListView)
        .filter(
            ProjectListView.user_id == ctx.user.id,
            ProjectListView.is_active.is_(True),
        )
        .order_by(
            func.lower(ProjectListView.name).asc(),
            ProjectListView.name.asc(),
            ProjectListView.id.asc(),
        )
        .all()
    )
    return [_view_payload(db, ctx, row) for row in rows]


def create_project_list_view(
    db: Session, ctx: AuthContext, name: object, config: object
) -> dict[str, object]:
    require_project_list_permission(ctx)
    normalised_name = _normalise_name(name)
    validated = _validate_config_for_write(db, ctx, config)
    _ensure_unique_name(db, ctx, normalised_name)
    row = ProjectListView(
        user_id=ctx.user.id,
        name=normalised_name,
        config=validated,
        is_active=True,
    )
    try:
        db.add(row)
        db.flush()
        response_payload = _view_payload(db, ctx, row)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ProjectListDuplicateError("Já existe uma vista ativa com esse nome.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise ProjectListStorageError(
            "Não foi possível guardar a vista da lista de Projetos."
        ) from exc
    return response_payload


def patch_project_list_view(
    db: Session,
    ctx: AuthContext,
    view_id: uuid.UUID,
    changes: Mapping[str, object],
) -> dict[str, object]:
    require_project_list_permission(ctx)
    row = _get_owned_active_view(db, ctx, view_id)
    if not changes:
        raise ProjectListValidationError("O PATCH tem de indicar name ou config.")

    if "name" in changes:
        normalised_name = _normalise_name(changes["name"])
    else:
        normalised_name = row.name
    if "config" in changes:
        if changes["config"] is None:
            raise ProjectListValidationError("config não pode ser null.")
        validated = _validate_config_for_write(db, ctx, changes["config"])
    else:
        validated = copy.deepcopy(row.config)
    _ensure_unique_name(db, ctx, normalised_name, excluding_id=row.id)

    row.name = normalised_name
    row.config = validated
    try:
        db.flush()
        response_payload = _view_payload(db, ctx, row)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ProjectListDuplicateError("Já existe uma vista ativa com esse nome.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise ProjectListStorageError(
            "Não foi possível atualizar a vista da lista de Projetos."
        ) from exc
    return response_payload


def delete_project_list_view(db: Session, ctx: AuthContext, view_id: uuid.UUID) -> None:
    require_project_list_permission(ctx)
    row = _get_owned_active_view(db, ctx, view_id)
    row.is_active = False
    try:
        db.flush()
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise ProjectListStorageError(
            "Não foi possível remover a vista da lista de Projetos."
        ) from exc
