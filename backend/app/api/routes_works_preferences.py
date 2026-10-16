"""Preferências pessoais do Calendário de obras."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.works_preferences import WorksPreferencePatch, WorksPreferenceRead
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, can_view_installers, is_installer_readonly_scope
from app.services.works_preferences import (
    WorksPreferenceStorageError,
    WorksPreferenceValidationError,
    get_works_preferences,
    update_works_preferences,
)

router = APIRouter(prefix="/api/me", tags=["works-preferences"])


_DETAIL_READ_FAILURE = "Não foi possível carregar as preferências do calendário de obras."
_DETAIL_WRITE_FAILURE = "Não foi possível guardar as preferências do calendário de obras."


def _require_view(ctx: AuthContext) -> None:
    # Mantém o catálogo global e aceita o canal explicitamente scoped.
    if not (can_view_installers(ctx) or ctx.has_permission("works_calendar.view_assigned_installer")):
        raise HTTPException(status_code=403, detail="Sem permissão para ver o calendário de obras.")


def _require_write(ctx: AuthContext) -> None:
    if is_installer_readonly_scope(ctx) or not ctx.has_permission("calendar.view"):
        raise HTTPException(status_code=403, detail="O papel externo tem acesso somente de leitura.")


@router.get("/works-preferences", response_model=WorksPreferenceRead)
def get_works_preferences_endpoint(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> dict[str, object]:
    _require_view(ctx)
    try:
        return get_works_preferences(db, ctx)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=_DETAIL_READ_FAILURE) from exc


@router.patch("/works-preferences", response_model=WorksPreferenceRead)
def patch_works_preferences_endpoint(
    body: WorksPreferencePatch,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, object]:
    _require_view(ctx)
    _require_write(ctx)
    try:
        return update_works_preferences(db, ctx, body.model_dump(exclude_unset=True))
    except WorksPreferenceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except WorksPreferenceStorageError as exc:
        raise HTTPException(status_code=503, detail=_DETAIL_WRITE_FAILURE) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=_DETAIL_WRITE_FAILURE) from exc
