"""Vistas pessoais guardadas do Calendário de obras."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.works_preferences import WorksPreferenceRead
from app.schemas.works_saved_views import SavedViewCreate, SavedViewPatch, SavedViewRead
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, can_view_installers, is_installer_readonly_scope
from app.services.works_preferences import (
    WorksPreferenceStorageError,
    WorksPreferenceValidationError,
)
from app.services.works_saved_views import (
    SavedViewDuplicateError,
    SavedViewNotFoundError,
    SavedViewPermissionError,
    SavedViewStorageError,
    SavedViewValidationError,
    apply_saved_view,
    create_saved_view,
    delete_saved_view,
    list_saved_views,
    update_saved_view,
)

router = APIRouter(prefix="/api/me/works-saved-views", tags=["works-saved-views"])

_DETAIL_READ_FAILURE = "Não foi possível carregar as vistas guardadas do calendário de obras."
_DETAIL_WRITE_FAILURE = "Não foi possível guardar a vista do calendário de obras."
_DETAIL_DELETE_FAILURE = "Não foi possível apagar a vista do calendário de obras."


def _require_view(ctx: AuthContext) -> None:
    if not (can_view_installers(ctx) or ctx.has_permission("works_calendar.view_assigned_installer")):
        raise HTTPException(
            status_code=403,
            detail="Sem permissão para ver o calendário de obras.",
        )


def _require_write(ctx: AuthContext) -> None:
    if is_installer_readonly_scope(ctx) or not ctx.has_permission("calendar.view"):
        raise HTTPException(status_code=403, detail="O papel externo tem acesso somente de leitura.")


def _permission_error(exc: SavedViewPermissionError) -> HTTPException:
    return HTTPException(status_code=403, detail=str(exc))


@router.get("", response_model=list[SavedViewRead])
def get_saved_views_endpoint(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> list[dict[str, object]]:
    _require_view(ctx)
    try:
        return list_saved_views(db, ctx)
    except SavedViewPermissionError as exc:
        raise _permission_error(exc) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=_DETAIL_READ_FAILURE) from exc


@router.post("", response_model=SavedViewRead, status_code=201)
def create_saved_view_endpoint(
    body: SavedViewCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, object]:
    _require_view(ctx)
    _require_write(ctx)
    try:
        return create_saved_view(db, ctx, body.model_dump())
    except SavedViewPermissionError as exc:
        raise _permission_error(exc) from exc
    except SavedViewDuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SavedViewValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SavedViewStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=_DETAIL_WRITE_FAILURE) from exc


@router.post("/{saved_view_id}/apply", response_model=WorksPreferenceRead)
def apply_saved_view_endpoint(
    saved_view_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, object]:
    _require_view(ctx)
    _require_write(ctx)
    try:
        return apply_saved_view(db, ctx, saved_view_id)
    except SavedViewPermissionError as exc:
        raise _permission_error(exc) from exc
    except SavedViewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorksPreferenceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except WorksPreferenceStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SavedViewStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=_DETAIL_WRITE_FAILURE) from exc


@router.patch("/{saved_view_id}", response_model=SavedViewRead)
def patch_saved_view_endpoint(
    saved_view_id: uuid.UUID,
    body: SavedViewPatch,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, object]:
    _require_view(ctx)
    _require_write(ctx)
    try:
        return update_saved_view(
            db,
            ctx,
            saved_view_id,
            body.model_dump(exclude_unset=True),
        )
    except SavedViewPermissionError as exc:
        raise _permission_error(exc) from exc
    except SavedViewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SavedViewDuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SavedViewValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SavedViewStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=_DETAIL_WRITE_FAILURE) from exc


@router.delete("/{saved_view_id}", status_code=204)
def delete_saved_view_endpoint(
    saved_view_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> Response:
    _require_view(ctx)
    _require_write(ctx)
    try:
        delete_saved_view(db, ctx, saved_view_id)
    except SavedViewPermissionError as exc:
        raise _permission_error(exc) from exc
    except SavedViewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SavedViewStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=_DETAIL_DELETE_FAILURE) from exc
    return Response(status_code=204)
