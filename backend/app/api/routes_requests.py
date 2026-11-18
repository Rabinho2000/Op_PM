from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.user_requests import (
    RequestCreate,
    RequestDetail,
    RequestListResponse,
    RequestMessageCreate,
    RequestMessageRead,
    RequestListItem,
    RequestStatusFilter,
    RequestStatusUpdate,
    RequestSummary,
)
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext
from app.services.user_requests import (
    UserRequestConflict,
    UserRequestError,
    UserRequestForbidden,
    UserRequestNotFound,
    add_message,
    change_status,
    create_request,
    get_request_detail,
    list_requests,
    request_detail_for_response,
    summarize_requests,
)

router = APIRouter(prefix="/api/requests", tags=["requests"])


def _raise(exc: Exception) -> HTTPException:
    if isinstance(exc, UserRequestForbidden):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, UserRequestNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, UserRequestConflict):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _rollback(db: Session) -> None:
    try:
        db.rollback()
    except SQLAlchemyError:
        pass


def _storage_error(exc: SQLAlchemyError) -> HTTPException:
    return HTTPException(status_code=503, detail="Não foi possível concluir a operação de pedidos.")


@router.get("", response_model=RequestListResponse)
def list_requests_endpoint(
    scope: Literal["mine", "all"] | None = Query(default=None),
    status: RequestStatusFilter = Query(default="all"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> RequestListResponse:
    try:
        items, total = list_requests(
            db,
            ctx,
            scope=scope,
            status=status,
            limit=limit,
            offset=offset,
        )
        return RequestListResponse(
            items=[RequestListItem.model_validate(item) for item in items],
            total=total,
        )
    except UserRequestError as exc:
        raise _raise(exc) from exc
    except SQLAlchemyError as exc:
        raise _storage_error(exc) from exc


# Keep this route before /{request_id}; otherwise "summary" is parsed as an ID.
@router.get("/summary", response_model=RequestSummary)
def request_summary_endpoint(
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> RequestSummary:
    try:
        return RequestSummary(open=summarize_requests(db, ctx))
    except SQLAlchemyError as exc:
        raise _storage_error(exc) from exc


@router.post("", response_model=RequestDetail, status_code=201)
def create_request_endpoint(
    body: RequestCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> RequestDetail:
    try:
        request = create_request(db, ctx, body)
        response = RequestDetail.model_validate(request_detail_for_response(db, ctx, request))
        db.commit()
        return response
    except UserRequestError as exc:
        _rollback(db)
        raise _raise(exc) from exc
    except SQLAlchemyError as exc:
        _rollback(db)
        raise _storage_error(exc) from exc


@router.post("/{request_id}/messages", response_model=RequestMessageRead, status_code=201)
def add_request_message_endpoint(
    request_id: uuid.UUID,
    body: RequestMessageCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> RequestMessageRead:
    try:
        message = RequestMessageRead.model_validate(add_message(db, ctx, request_id, body))
        db.commit()
        return message
    except UserRequestError as exc:
        _rollback(db)
        raise _raise(exc) from exc
    except SQLAlchemyError as exc:
        _rollback(db)
        raise _storage_error(exc) from exc


@router.post("/{request_id}/status", response_model=RequestDetail)
def change_request_status_endpoint(
    request_id: uuid.UUID,
    body: RequestStatusUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> RequestDetail:
    try:
        response = RequestDetail.model_validate(change_status(db, ctx, request_id, body.status))
        db.commit()
        return response
    except UserRequestError as exc:
        _rollback(db)
        raise _raise(exc) from exc
    except SQLAlchemyError as exc:
        _rollback(db)
        raise _storage_error(exc) from exc


@router.get("/{request_id}", response_model=RequestDetail)
def get_request_endpoint(
    request_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> RequestDetail:
    try:
        return RequestDetail.model_validate(get_request_detail(db, ctx, request_id))
    except UserRequestError as exc:
        raise _raise(exc) from exc
    except SQLAlchemyError as exc:
        raise _storage_error(exc) from exc
