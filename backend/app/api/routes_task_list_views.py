"""Personal preferences and saved views for the Tasks list."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.task_list_views import (
    TaskListPreferencePut,
    TaskListPreferenceRead,
    TaskListViewCreate,
    TaskListViewPatch,
    TaskListViewRead,
)
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext
from app.services.task_list_views import (
    TaskListDuplicateError,
    TaskListNotFoundError,
    TaskListPermissionError,
    TaskListStorageError,
    TaskListValidationError,
    create_task_list_view,
    delete_task_list_view,
    get_task_list_preferences,
    list_task_list_views,
    patch_task_list_view,
    put_task_list_preferences,
)

preferences_router = APIRouter(prefix="/api/me", tags=["task-list-preferences"])
views_router = APIRouter(prefix="/api/me/task-list-views", tags=["task-list-views"])

_READ_PREFERENCES_FAILURE = "Não foi possível carregar as preferências da lista de Tarefas."
_WRITE_PREFERENCES_FAILURE = "Não foi possível guardar as preferências da lista de Tarefas."
_READ_VIEWS_FAILURE = "Não foi possível carregar as vistas da lista de Tarefas."
_WRITE_VIEWS_FAILURE = "Não foi possível guardar a vista da lista de Tarefas."
_DELETE_VIEW_FAILURE = "Não foi possível remover a vista da lista de Tarefas."


def _permission_error(exc: TaskListPermissionError) -> HTTPException:
    return HTTPException(status_code=403, detail=str(exc))


@preferences_router.get(
    "/task-list-preferences", response_model=TaskListPreferenceRead
)
def get_task_list_preferences_endpoint(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> dict[str, object]:
    try:
        return get_task_list_preferences(db, ctx)
    except TaskListPermissionError as exc:
        raise _permission_error(exc) from exc
    except (TaskListStorageError, TaskListValidationError, SQLAlchemyError) as exc:
        raise HTTPException(status_code=503, detail=_READ_PREFERENCES_FAILURE) from exc


@preferences_router.put(
    "/task-list-preferences", response_model=TaskListPreferenceRead
)
def put_task_list_preferences_endpoint(
    body: TaskListPreferencePut,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, object]:
    try:
        return put_task_list_preferences(db, ctx, body.config.model_dump())
    except TaskListPermissionError as exc:
        raise _permission_error(exc) from exc
    except TaskListValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TaskListStorageError as exc:
        raise HTTPException(status_code=503, detail=_WRITE_PREFERENCES_FAILURE) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=_WRITE_PREFERENCES_FAILURE) from exc


@views_router.get("", response_model=list[TaskListViewRead])
def list_task_list_views_endpoint(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> list[dict[str, object]]:
    try:
        return list_task_list_views(db, ctx)
    except TaskListPermissionError as exc:
        raise _permission_error(exc) from exc
    except (TaskListStorageError, TaskListValidationError, SQLAlchemyError) as exc:
        raise HTTPException(status_code=503, detail=_READ_VIEWS_FAILURE) from exc


@views_router.post("", response_model=TaskListViewRead, status_code=201)
def create_task_list_view_endpoint(
    body: TaskListViewCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, object]:
    try:
        return create_task_list_view(db, ctx, body.name, body.config.model_dump())
    except TaskListPermissionError as exc:
        raise _permission_error(exc) from exc
    except TaskListDuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except TaskListValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TaskListStorageError as exc:
        raise HTTPException(status_code=503, detail=_WRITE_VIEWS_FAILURE) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=_WRITE_VIEWS_FAILURE) from exc


@views_router.patch("/{view_id}", response_model=TaskListViewRead)
def patch_task_list_view_endpoint(
    view_id: uuid.UUID,
    body: TaskListViewPatch,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, object]:
    try:
        changes = body.model_dump(exclude_unset=True)
        if "config" in changes and body.config is not None:
            changes["config"] = body.config.model_dump()
        return patch_task_list_view(db, ctx, view_id, changes)
    except TaskListPermissionError as exc:
        raise _permission_error(exc) from exc
    except TaskListNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TaskListDuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except TaskListValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TaskListStorageError as exc:
        raise HTTPException(status_code=503, detail=_WRITE_VIEWS_FAILURE) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=_WRITE_VIEWS_FAILURE) from exc


@views_router.delete("/{view_id}", status_code=204)
def delete_task_list_view_endpoint(
    view_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> Response:
    try:
        delete_task_list_view(db, ctx, view_id)
    except TaskListPermissionError as exc:
        raise _permission_error(exc) from exc
    except TaskListNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TaskListStorageError as exc:
        raise HTTPException(status_code=503, detail=_DELETE_VIEW_FAILURE) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=_DELETE_VIEW_FAILURE) from exc
    return Response(status_code=204)
