from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.support_delegations import SupportDelegationRead, SupportDelegationUpsert
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, PermissionDenied
from app.services.support_delegations import (
    SupportDelegationError,
    SupportDelegationNotFound,
    delete_delegation,
    list_delegations,
    upsert_delegation,
)

router = APIRouter(prefix="/api/support-delegations", tags=["support-delegations"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionDenied):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get("", response_model=list[SupportDelegationRead])
def get_support_delegations(db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)):
    try:
        return list_delegations(db, ctx)
    except PermissionDenied as exc:
        raise _error(exc)


@router.put("", response_model=SupportDelegationRead)
def put_support_delegation(body: SupportDelegationUpsert, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)):
    try:
        return upsert_delegation(db, pm_person_id=body.pm_person_id, support_person_id=body.support_person_id, ctx=ctx)
    except PermissionDenied as exc:
        raise _error(exc)
    except SupportDelegationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except SupportDelegationError as exc:
        raise _error(exc)


@router.delete("/{pm_person_id}", status_code=204)
def remove_support_delegation(pm_person_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)) -> Response:
    try:
        delete_delegation(db, pm_person_id=pm_person_id, ctx=ctx)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except SupportDelegationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except SupportDelegationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return Response(status_code=204)
