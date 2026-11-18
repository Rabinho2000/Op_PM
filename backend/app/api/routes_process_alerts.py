"""Alarmes de etapas do processo: subscrições e notificações do próprio utilizador.

Só o próprio utilizador lê/altera as suas subscrições e notificações; um id alheio
devolve 404. Instalador externo (leitura) recebe 403. Ver
`app/services/process_alerts.py`.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.process_alerts import (
    AlertSubscriptionsRead,
    AlertSubscriptionsUpdate,
    MarkAllReadRead,
    NotificationListRead,
    NotificationRead,
    UnreadCountRead,
)
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext
from app.services import process_alerts as service

router = APIRouter(prefix="/api/me", tags=["process-alerts"])


def _raise(exc: Exception) -> HTTPException:
    if isinstance(exc, service.ProcessAlertForbidden):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, service.ProcessAlertNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/process-alerts/subscriptions", response_model=AlertSubscriptionsRead)
def get_subscriptions_endpoint(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> AlertSubscriptionsRead:
    try:
        service.require_alert_permission(ctx)
    except service.ProcessAlertError as exc:
        raise _raise(exc)
    return AlertSubscriptionsRead(phases=service.catalog_with_subscriptions(db, ctx.user))


@router.put("/process-alerts/subscriptions", response_model=AlertSubscriptionsRead)
def put_subscriptions_endpoint(
    body: AlertSubscriptionsUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> AlertSubscriptionsRead:
    try:
        service.set_subscriptions(db, ctx, body.stage_ids)
    except service.ProcessAlertError as exc:
        raise _raise(exc)
    return AlertSubscriptionsRead(phases=service.catalog_with_subscriptions(db, ctx.user))


# `/notifications/unread-count` e `/notifications/read-all` antes de `/{id}` (não há GET com id,
# mas mantém-se a ordem por clareza).
@router.get("/notifications", response_model=NotificationListRead)
def list_notifications_endpoint(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=service.MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> NotificationListRead:
    try:
        page = service.list_notifications(db, ctx, unread_only=unread_only, limit=limit, offset=offset)
    except service.ProcessAlertError as exc:
        raise _raise(exc)
    return NotificationListRead(
        items=[NotificationRead(**item) for item in page["items"]],
        total=page["total"],
        limit=page["limit"],
        offset=page["offset"],
    )


@router.get("/notifications/unread-count", response_model=UnreadCountRead)
def unread_count_endpoint(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> UnreadCountRead:
    try:
        return UnreadCountRead(unread=service.unread_count(db, ctx))
    except service.ProcessAlertError as exc:
        raise _raise(exc)


@router.post("/notifications/read-all", response_model=MarkAllReadRead)
def mark_all_read_endpoint(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> MarkAllReadRead:
    try:
        return MarkAllReadRead(marked=service.mark_all_read(db, ctx))
    except service.ProcessAlertError as exc:
        raise _raise(exc)


@router.post("/notifications/{notification_id}/read", response_model=NotificationRead)
def mark_read_endpoint(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> NotificationRead:
    try:
        return NotificationRead(**service.mark_read(db, ctx, notification_id))
    except service.ProcessAlertError as exc:
        raise _raise(exc)
