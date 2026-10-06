"""API do relatório semanal ao cliente.

A rota mantém o contrato consumido por `frontend/src/api/client.ts`; a decisão
de autorização continua no serviço para também proteger scheduler/CLI futuros.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.client_reports import ClientReportConfigInput
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext
from app.services.client_reports import (
    ClientReportError,
    ClientReportForbidden,
    ClientReportNotFound,
    ClientReportValidationError,
    _send_row_dict,
    approve_send,
    discard_send,
    get_report,
    list_reports,
    preview_report,
    send_report,
    update_report,
)

router = APIRouter(tags=["client-reports"])


def _raise(error: ClientReportError) -> None:
    if isinstance(error, ClientReportNotFound):
        raise HTTPException(status_code=404, detail=str(error))
    if isinstance(error, ClientReportForbidden):
        raise HTTPException(status_code=403, detail=str(error))
    raise HTTPException(status_code=400, detail=str(error))


@router.get("/api/projects/{project_id}/client-report")
def get_client_report(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict:
    try:
        return get_report(db, project_id, ctx)
    except ClientReportError as error:
        _raise(error)
    raise AssertionError("unreachable")


@router.put("/api/projects/{project_id}/client-report")
def put_client_report(
    project_id: uuid.UUID,
    body: ClientReportConfigInput,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict:
    try:
        result = update_report(db, project_id, body.model_dump(), ctx)
        db.commit()
        return result
    except ClientReportError as error:
        db.rollback()
        _raise(error)
    raise AssertionError("unreachable")


@router.get("/api/projects/{project_id}/client-report/preview")
def preview_client_report(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict:
    try:
        return preview_report(db, project_id, ctx)
    except ClientReportError as error:
        _raise(error)
    raise AssertionError("unreachable")


@router.post("/api/projects/{project_id}/client-report/send-now")
def send_client_report_now(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict:
    try:
        result = send_report(db, project_id, ctx, trigger="manual")
        db.commit()
        return _send_row_dict(result)
    except ClientReportError as error:
        db.rollback()
        _raise(error)
    raise AssertionError("unreachable")


@router.post("/api/client-report-sends/{send_id}/approve")
def approve_client_report_send(
    send_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict:
    try:
        result = approve_send(db, send_id, ctx)
        db.commit()
        return _send_row_dict(result)
    except ClientReportError as error:
        db.rollback()
        _raise(error)
    raise AssertionError("unreachable")


@router.post("/api/client-report-sends/{send_id}/discard")
def discard_client_report_send(
    send_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict:
    try:
        result = discard_send(db, send_id, ctx)
        db.commit()
        return _send_row_dict(result)
    except ClientReportError as error:
        db.rollback()
        _raise(error)
    raise AssertionError("unreachable")


@router.get("/api/client-reports")
def list_client_reports(
    status: str | None = Query(default=None),
    pm_person_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[dict]:
    try:
        return list_reports(db, ctx, status=status, pm_person_id=pm_person_id)
    except ClientReportError as error:
        _raise(error)
    raise AssertionError("unreachable")
