"""Canonical service for personal Tasks-list preferences and views."""
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
from app.models.task import Task
from app.models.task_list_views import TaskListView, UserTaskListPreference
from app.schemas.task_list_views import TASK_LIST_DEFAULT_COLUMNS, TaskListConfig
from app.security.permissions import (
    AuthContext,
    has_only_delegated_project_scope,
    is_installer_readonly_scope,
)
from app.services.projects import visible_projects_query
from app.services.tasks import list_tasks, visible_tasks_query

TASK_LIST_DEFAULT_CONFIG: dict[str, object] = {
    "columns": list(TASK_LIST_DEFAULT_COLUMNS),
    "sort_by": "default",
    "sort_direction": "asc",
    "view": "lista",
    "filters": {
        "project_id": "",
        "assigned_to_person_id": "",
        "priority": "",
        "status": "",
        "overdue_only": False,
    },
}


class TaskListPermissionError(PermissionError):
    """The authenticated account cannot use the Tasks-list settings API."""


class TaskListNotFoundError(LookupError):
    """A view is absent or owned by another account."""


class TaskListValidationError(ValueError):
    """A config, name, or scoped reference violates the closed contract."""


class TaskListDuplicateError(ValueError):
    """An active view with the same account/name already exists."""


class TaskListStorageError(RuntimeError):
    """A database failure while persisting Task-list state."""


def require_task_list_permission(ctx: AuthContext) -> None:
    """Use task capabilities and preserve additive role semantics."""
    if is_installer_readonly_scope(ctx):
        raise TaskListPermissionError("O canal externo tem acesso somente de leitura.")
    if not any(
        ctx.has_permission(code)
        for code in (
            "task.view_all",
            "task.view_own",
            "task.view_assigned_installer",
        )
    ):
        raise TaskListPermissionError("Sem permissão para ver a lista de Tarefas.")


def _default_config() -> dict[str, object]:
    return cast(dict[str, object], copy.deepcopy(TASK_LIST_DEFAULT_CONFIG))


def _parse_config(config: object) -> dict[str, object]:
    try:
        parsed = TaskListConfig.model_validate(config)
    except ValidationError as exc:
        raise TaskListValidationError("Configuração da lista de Tarefas inválida.") from exc
    return cast(dict[str, object], parsed.model_dump())


def _uuid_or_none(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        return None


def _visible_project_ids(db: Session, ctx: AuthContext):
    """Union project and task scopes used by the existing selectors."""
    projects = visible_projects_query(db, ctx).with_entities(Project.id.label("project_id"))
    task_projects = visible_tasks_query(db, ctx).with_entities(Task.project_id.label("project_id"))
    return projects.union(task_projects).subquery()


def _project_is_reachable(db: Session, ctx: AuthContext, value: str) -> bool:
    project_id = _uuid_or_none(value)
    if project_id is None:
        return False
    visible_project_ids = _visible_project_ids(db, ctx)
    return (
        db.query(visible_project_ids.c.project_id)
        .filter(visible_project_ids.c.project_id == project_id)
        .one_or_none()
        is not None
    )


def _assignee_is_reachable(db: Session, ctx: AuthContext, value: str) -> bool:
    person_id = _uuid_or_none(value)
    if person_id is None:
        return False
    if list_tasks(db, ctx, assigned_to_person_id=person_id):
        return True
    # A user's own Person remains a legitimate filter even when no current
    # task happens to be assigned to it, provided the task scope is not only a
    # delegated/external project scope.
    if person_id == ctx.person_id and (
        ctx.has_permission("task.view_all") or ctx.has_permission("task.view_own")
    ):
        return (
            not has_only_delegated_project_scope(ctx)
            and db.query(Person.id)
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
    project_id = cast(str, filters["project_id"])
    assigned_to_person_id = cast(str, filters["assigned_to_person_id"])
    if project_id and not _project_is_reachable(db, ctx, project_id):
        raise TaskListValidationError("O filtro de projeto está fora do âmbito visível.")
    if assigned_to_person_id and not _assignee_is_reachable(db, ctx, assigned_to_person_id):
        raise TaskListValidationError("O filtro de responsável está fora do âmbito visível.")
    return payload


def _scoped_config(db: Session, ctx: AuthContext, config: object) -> dict[str, object]:
    """Return a detached response copy; never redact ORM JSON in place."""
    payload = _parse_config(config)
    filters = cast(dict[str, object], payload["filters"])
    project_id = cast(str, filters["project_id"])
    assigned_to_person_id = cast(str, filters["assigned_to_person_id"])
    if project_id and not _project_is_reachable(db, ctx, project_id):
        filters["project_id"] = ""
    if assigned_to_person_id and not _assignee_is_reachable(db, ctx, assigned_to_person_id):
        filters["assigned_to_person_id"] = ""
    return payload


def _preference_payload(
    db: Session, ctx: AuthContext, row: UserTaskListPreference | None
) -> dict[str, object]:
    if row is None:
        return {"config": _default_config()}
    return {"config": _scoped_config(db, ctx, row.config)}


def get_task_list_preferences(db: Session, ctx: AuthContext) -> dict[str, object]:
    require_task_list_permission(ctx)
    row = (
        db.query(UserTaskListPreference)
        .filter(UserTaskListPreference.user_id == ctx.user.id)
        .one_or_none()
    )
    return _preference_payload(db, ctx, row)


def put_task_list_preferences(
    db: Session, ctx: AuthContext, config: object
) -> dict[str, object]:
    require_task_list_permission(ctx)
    validated = _validate_config_for_write(db, ctx, config)
    row = (
        db.query(UserTaskListPreference)
        .filter(UserTaskListPreference.user_id == ctx.user.id)
        .one_or_none()
    )
    if row is None:
        # The preference row does not exist yet, so lock the existing User row
        # and read the preference again at READ COMMITTED before inserting.
        db.query(User).filter(User.id == ctx.user.id).populate_existing().with_for_update().one()
        row = (
            db.query(UserTaskListPreference)
            .filter(UserTaskListPreference.user_id == ctx.user.id)
            .populate_existing()
            .one_or_none()
        )
        if row is None:
            row = UserTaskListPreference(user_id=ctx.user.id)
            db.add(row)
    row.config = validated
    response_payload: dict[str, object] = {"config": copy.deepcopy(validated)}
    try:
        db.flush()
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise TaskListStorageError(
            "Não foi possível guardar as preferências da lista de Tarefas."
        ) from exc
    return response_payload


def _normalise_name(value: object) -> str:
    if not isinstance(value, str):
        raise TaskListValidationError("O nome da vista é inválido.")
    name = value.strip()
    if not name or len(name) > 120:
        raise TaskListValidationError(
            "O nome da vista tem de ter entre 1 e 120 caracteres."
        )
    return name


def _get_owned_active_view(
    db: Session, ctx: AuthContext, view_id: uuid.UUID
) -> TaskListView:
    row = (
        db.query(TaskListView)
        .filter(
            TaskListView.id == view_id,
            TaskListView.user_id == ctx.user.id,
            TaskListView.is_active.is_(True),
        )
        .one_or_none()
    )
    if row is None:
        raise TaskListNotFoundError("Vista da lista de Tarefas não encontrada.")
    return row


def _ensure_unique_name(
    db: Session,
    ctx: AuthContext,
    name: str,
    *,
    excluding_id: uuid.UUID | None = None,
) -> None:
    query = db.query(TaskListView).filter(
        TaskListView.user_id == ctx.user.id,
        TaskListView.name == name,
        TaskListView.is_active.is_(True),
    )
    if excluding_id is not None:
        query = query.filter(TaskListView.id != excluding_id)
    if query.first() is not None:
        raise TaskListDuplicateError("Já existe uma vista ativa com esse nome.")


def _view_payload(db: Session, ctx: AuthContext, row: TaskListView) -> dict[str, object]:
    return {
        "id": row.id,
        "name": row.name,
        "config": _scoped_config(db, ctx, row.config),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def list_task_list_views(db: Session, ctx: AuthContext) -> list[dict[str, object]]:
    require_task_list_permission(ctx)
    rows = (
        db.query(TaskListView)
        .filter(
            TaskListView.user_id == ctx.user.id,
            TaskListView.is_active.is_(True),
        )
        .order_by(
            func.lower(TaskListView.name).asc(),
            TaskListView.name.asc(),
            TaskListView.id.asc(),
        )
        .all()
    )
    return [_view_payload(db, ctx, row) for row in rows]


def create_task_list_view(
    db: Session, ctx: AuthContext, name: object, config: object
) -> dict[str, object]:
    require_task_list_permission(ctx)
    normalised_name = _normalise_name(name)
    validated = _validate_config_for_write(db, ctx, config)
    _ensure_unique_name(db, ctx, normalised_name)
    row = TaskListView(
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
        raise TaskListDuplicateError("Já existe uma vista ativa com esse nome.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise TaskListStorageError(
            "Não foi possível guardar a vista da lista de Tarefas."
        ) from exc
    return response_payload


def patch_task_list_view(
    db: Session,
    ctx: AuthContext,
    view_id: uuid.UUID,
    changes: Mapping[str, object],
) -> dict[str, object]:
    require_task_list_permission(ctx)
    row = _get_owned_active_view(db, ctx, view_id)
    if not changes:
        raise TaskListValidationError("O PATCH tem de indicar name ou config.")

    if "name" in changes:
        normalised_name = _normalise_name(changes["name"])
    else:
        normalised_name = row.name
    if "config" in changes:
        if changes["config"] is None:
            raise TaskListValidationError("config não pode ser null.")
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
        raise TaskListDuplicateError("Já existe uma vista ativa com esse nome.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise TaskListStorageError(
            "Não foi possível atualizar a vista da lista de Tarefas."
        ) from exc
    return response_payload


def delete_task_list_view(db: Session, ctx: AuthContext, view_id: uuid.UUID) -> None:
    require_task_list_permission(ctx)
    row = _get_owned_active_view(db, ctx, view_id)
    row.is_active = False
    try:
        db.flush()
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise TaskListStorageError(
            "Não foi possível remover a vista da lista de Tarefas."
        ) from exc
