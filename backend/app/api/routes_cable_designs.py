"""HTTP routes for project-scoped cable dimensioning studies."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.cable_designs import (
    CableDesignCreate,
    CableDesignExpectedVersion,
    CableDesignHistoryRead,
    CableDesignListRead,
    CableDesignRead,
    CableDesignRevisionListRead,
    CableDesignRevisionUpdate,
)
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext
from app.services.cable_designs import (
    CableDesignConflictError,
    CableDesignLockedError,
    CableDesignNotFoundError,
    CableDesignPayloadTooLargeError,
    CableDesignPermissionError,
    CableDesignStorageError,
    CableDesignValidationError,
    approve_cable_design,
    create_cable_design,
    deactivate_cable_design,
    get_cable_design,
    list_cable_design_history,
    list_cable_design_revisions,
    list_cable_designs,
    new_cable_design_revision,
    update_current_cable_design_revision,
)

projects_router = APIRouter(prefix="/api/projects", tags=["cable-designs"])
designs_router = APIRouter(prefix="/api/cable-designs", tags=["cable-designs"])

_GENERIC_READ_FAILURE = "Não foi possível carregar o estudo de cabos."
_GENERIC_WRITE_FAILURE = "Não foi possível guardar o estudo de cabos."
_GENERIC_DELETE_FAILURE = "Não foi possível desativar o estudo de cabos."


def _permission_error(exc: CableDesignPermissionError) -> HTTPException:
    return HTTPException(status_code=403, detail=str(exc))


def _not_found_error(exc: CableDesignNotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _storage_error(exc: CableDesignStorageError, message: str) -> HTTPException:
    return HTTPException(status_code=503, detail=message)


def _validation_error(exc: CableDesignValidationError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


def _conflict_error(exc: CableDesignConflictError) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


def _locked_error(exc: CableDesignLockedError) -> HTTPException:
    return HTTPException(status_code=423, detail=str(exc))


class _SanitisedValidationRoute(APIRoute):
    """Do not serialize untrusted request values into validation responses."""

    def get_route_handler(self):
        original_route_handler = super().get_route_handler()

        async def sanitised_handler(request):
            try:
                return await original_route_handler(request)
            except RequestValidationError:
                return JSONResponse(status_code=422, content={"detail": "Corpo inválido."})

        return sanitised_handler


projects_router.route_class = _SanitisedValidationRoute
designs_router.route_class = _SanitisedValidationRoute


@projects_router.get(
    "/{project_id}/cable-designs", response_model=list[CableDesignListRead]
)
def list_cable_designs_endpoint(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[dict[str, object]]:
    try:
        return list_cable_designs(db, ctx, project_id)
    except CableDesignPermissionError as exc:
        raise _permission_error(exc) from exc
    except CableDesignNotFoundError as exc:
        raise _not_found_error(exc) from exc
    except (CableDesignStorageError, SQLAlchemyError) as exc:
        raise _storage_error(exc, _GENERIC_READ_FAILURE) from exc


@projects_router.post(
    "/{project_id}/cable-designs",
    response_model=CableDesignRead,
    status_code=201,
)
def create_cable_design_endpoint(
    project_id: uuid.UUID,
    body: CableDesignCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, object]:
    try:
        return create_cable_design(
            db,
            ctx,
            project_id,
            title=body.title,
            input_json=body.input_json,
            engine_version=body.engine_version,
        )
    except CableDesignPermissionError as exc:
        raise _permission_error(exc) from exc
    except CableDesignNotFoundError as exc:
        raise _not_found_error(exc) from exc
    except CableDesignPayloadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except CableDesignValidationError as exc:
        raise _validation_error(exc) from exc
    except (CableDesignStorageError, SQLAlchemyError) as exc:
        raise _storage_error(exc, _GENERIC_WRITE_FAILURE) from exc


@designs_router.get("/{design_id}", response_model=CableDesignRead)
def get_cable_design_endpoint(
    design_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, object]:
    try:
        return get_cable_design(db, ctx, design_id)
    except CableDesignPermissionError as exc:
        raise _permission_error(exc) from exc
    except CableDesignNotFoundError as exc:
        raise _not_found_error(exc) from exc
    except CableDesignStorageError as exc:
        raise _storage_error(exc, _GENERIC_READ_FAILURE) from exc
    except SQLAlchemyError as exc:
        raise _storage_error(exc, _GENERIC_READ_FAILURE) from exc


@designs_router.put(
    "/{design_id}/revisions/current", response_model=CableDesignRead
)
def update_current_cable_design_revision_endpoint(
    design_id: uuid.UUID,
    body: CableDesignRevisionUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, object]:
    try:
        return update_current_cable_design_revision(
            db,
            ctx,
            design_id,
            expected_version=body.expected_version,
            title=body.title,
            input_value=body.input,
            result_value=body.result,
            engine_version=body.engine_version,
        )
    except CableDesignPermissionError as exc:
        raise _permission_error(exc) from exc
    except CableDesignNotFoundError as exc:
        raise _not_found_error(exc) from exc
    except CableDesignLockedError as exc:
        raise _locked_error(exc) from exc
    except CableDesignConflictError as exc:
        raise _conflict_error(exc) from exc
    except CableDesignPayloadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except CableDesignValidationError as exc:
        raise _validation_error(exc) from exc
    except (CableDesignStorageError, SQLAlchemyError) as exc:
        raise _storage_error(exc, _GENERIC_WRITE_FAILURE) from exc


@designs_router.post("/{design_id}/approve", response_model=CableDesignRead)
def approve_cable_design_endpoint(
    design_id: uuid.UUID,
    body: CableDesignExpectedVersion,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, object]:
    try:
        return approve_cable_design(
            db, ctx, design_id, expected_version=body.expected_version
        )
    except CableDesignPermissionError as exc:
        raise _permission_error(exc) from exc
    except CableDesignNotFoundError as exc:
        raise _not_found_error(exc) from exc
    except CableDesignLockedError as exc:
        raise _locked_error(exc) from exc
    except CableDesignConflictError as exc:
        raise _conflict_error(exc) from exc
    except CableDesignValidationError as exc:
        raise _validation_error(exc) from exc
    except (CableDesignStorageError, SQLAlchemyError) as exc:
        raise _storage_error(exc, _GENERIC_WRITE_FAILURE) from exc


@designs_router.post(
    "/{design_id}/new-revision", response_model=CableDesignRead, status_code=201
)
def new_cable_design_revision_endpoint(
    design_id: uuid.UUID,
    body: CableDesignExpectedVersion,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, object]:
    try:
        return new_cable_design_revision(
            db, ctx, design_id, expected_version=body.expected_version
        )
    except CableDesignPermissionError as exc:
        raise _permission_error(exc) from exc
    except CableDesignNotFoundError as exc:
        raise _not_found_error(exc) from exc
    except CableDesignConflictError as exc:
        raise _conflict_error(exc) from exc
    except CableDesignLockedError as exc:
        raise _locked_error(exc) from exc
    except CableDesignValidationError as exc:
        raise _validation_error(exc) from exc
    except (CableDesignStorageError, SQLAlchemyError) as exc:
        raise _storage_error(exc, _GENERIC_WRITE_FAILURE) from exc


@designs_router.get(
    "/{design_id}/revisions", response_model=list[CableDesignRevisionListRead]
)
def list_cable_design_revisions_endpoint(
    design_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[dict[str, object]]:
    try:
        return list_cable_design_revisions(db, ctx, design_id)
    except CableDesignPermissionError as exc:
        raise _permission_error(exc) from exc
    except CableDesignNotFoundError as exc:
        raise _not_found_error(exc) from exc
    except CableDesignStorageError as exc:
        raise _storage_error(exc, _GENERIC_READ_FAILURE) from exc
    except SQLAlchemyError as exc:
        raise _storage_error(exc, _GENERIC_READ_FAILURE) from exc


@designs_router.get(
    "/{design_id}/history", response_model=list[CableDesignHistoryRead]
)
def list_cable_design_history_endpoint(
    design_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[dict[str, object]]:
    try:
        return list_cable_design_history(db, ctx, design_id)
    except CableDesignPermissionError as exc:
        raise _permission_error(exc) from exc
    except CableDesignNotFoundError as exc:
        raise _not_found_error(exc) from exc
    except CableDesignStorageError as exc:
        raise _storage_error(exc, _GENERIC_READ_FAILURE) from exc
    except SQLAlchemyError as exc:
        raise _storage_error(exc, _GENERIC_READ_FAILURE) from exc


@designs_router.delete("/{design_id}", status_code=204)
def deactivate_cable_design_endpoint(
    design_id: uuid.UUID,
    expected_version: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> Response:
    try:
        deactivate_cable_design(
            db, ctx, design_id, expected_version=expected_version
        )
    except CableDesignPermissionError as exc:
        raise _permission_error(exc) from exc
    except CableDesignNotFoundError as exc:
        raise _not_found_error(exc) from exc
    except CableDesignConflictError as exc:
        raise _conflict_error(exc) from exc
    except CableDesignValidationError as exc:
        raise _validation_error(exc) from exc
    except (CableDesignStorageError, SQLAlchemyError) as exc:
        raise _storage_error(exc, _GENERIC_DELETE_FAILURE) from exc
    return Response(status_code=204)
