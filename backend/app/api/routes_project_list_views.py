"""Personal configuration and saved views for the Projects list."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.project_list_views import (
    ProjectListPreferencePut,
    ProjectListPreferenceRead,
    ProjectListViewCreate,
    ProjectListViewPatch,
    ProjectListViewRead,
)
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext
from app.services.project_list_views import (
    ProjectListDuplicateError,
    ProjectListNotFoundError,
    ProjectListPermissionError,
    ProjectListStorageError,
    ProjectListValidationError,
    create_project_list_view,
    delete_project_list_view,
    get_project_list_preferences,
    list_project_list_views,
    patch_project_list_view,
    put_project_list_preferences,
)

preferences_router = APIRouter(prefix="/api/me", tags=["project-list-preferences"])
views_router = APIRouter(prefix="/api/me/project-list-views", tags=["project-list-views"])

_READ_PREFERENCES_FAILURE = "Não foi possível carregar as preferências da lista de Projetos."
_WRITE_PREFERENCES_FAILURE = "Não foi possível guardar as preferências da lista de Projetos."
_READ_VIEWS_FAILURE = "Não foi possível carregar as vistas da lista de Projetos."
_WRITE_VIEWS_FAILURE = "Não foi possível guardar a vista da lista de Projetos."
_DELETE_VIEW_FAILURE = "Não foi possível remover a vista da lista de Projetos."


def _permission_error(exc: ProjectListPermissionError) -> HTTPException:
    return HTTPException(status_code=403, detail=str(exc))


@preferences_router.get(
    "/project-list-preferences", response_model=ProjectListPreferenceRead
)
def get_project_list_preferences_endpoint(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> dict[str, object]:
    try:
        return get_project_list_preferences(db, ctx)
    except ProjectListPermissionError as exc:
        raise _permission_error(exc) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=_READ_PREFERENCES_FAILURE) from exc


@preferences_router.put(
    "/project-list-preferences", response_model=ProjectListPreferenceRead
)
def put_project_list_preferences_endpoint(
    body: ProjectListPreferencePut,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, object]:
    try:
        return put_project_list_preferences(db, ctx, body.config.model_dump())
    except ProjectListPermissionError as exc:
        raise _permission_error(exc) from exc
    except ProjectListValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProjectListStorageError as exc:
        raise HTTPException(status_code=503, detail=_WRITE_PREFERENCES_FAILURE) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=_WRITE_PREFERENCES_FAILURE) from exc


@views_router.get("", response_model=list[ProjectListViewRead])
def list_project_list_views_endpoint(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> list[dict[str, object]]:
    try:
        return list_project_list_views(db, ctx)
    except ProjectListPermissionError as exc:
        raise _permission_error(exc) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=_READ_VIEWS_FAILURE) from exc


@views_router.post("", response_model=ProjectListViewRead, status_code=201)
def create_project_list_view_endpoint(
    body: ProjectListViewCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, object]:
    try:
        return create_project_list_view(
            db, ctx, body.name, body.config.model_dump()
        )
    except ProjectListPermissionError as exc:
        raise _permission_error(exc) from exc
    except ProjectListDuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ProjectListValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProjectListStorageError as exc:
        raise HTTPException(status_code=503, detail=_WRITE_VIEWS_FAILURE) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=_WRITE_VIEWS_FAILURE) from exc


@views_router.patch("/{view_id}", response_model=ProjectListViewRead)
def patch_project_list_view_endpoint(
    view_id: uuid.UUID,
    body: ProjectListViewPatch,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, object]:
    try:
        changes = body.model_dump(exclude_unset=True)
        if "config" in changes and body.config is not None:
            changes["config"] = body.config.model_dump()
        return patch_project_list_view(db, ctx, view_id, changes)
    except ProjectListPermissionError as exc:
        raise _permission_error(exc) from exc
    except ProjectListNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProjectListDuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ProjectListValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProjectListStorageError as exc:
        raise HTTPException(status_code=503, detail=_WRITE_VIEWS_FAILURE) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=_WRITE_VIEWS_FAILURE) from exc


@views_router.delete("/{view_id}", status_code=204)
def delete_project_list_view_endpoint(
    view_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> Response:
    try:
        delete_project_list_view(db, ctx, view_id)
    except ProjectListPermissionError as exc:
        raise _permission_error(exc) from exc
    except ProjectListNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProjectListStorageError as exc:
        raise HTTPException(status_code=503, detail=_DELETE_VIEW_FAILURE) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=_DELETE_VIEW_FAILURE) from exc
    return Response(status_code=204)
