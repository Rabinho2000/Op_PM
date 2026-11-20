from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.support_delegations import SupportDelegationRead, SupportDelegationUpsert
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext
from app.services.support_delegations import (
    SupportDelegationError,
    SupportDelegationNotFound,
    delete_delegation,
    list_delegations,
    upsert_delegation,
)

router = APIRouter(prefix="/api/support-delegations", tags=["support-delegations"])


@router.get("", response_model=list[SupportDelegationRead])
def get_support_delegations(db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)):
    return list_delegations(db, ctx)


@router.put("", response_model=SupportDelegationRead)
def put_support_delegation(body: SupportDelegationUpsert, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)):
    try:
        return upsert_delegation(db, pm_person_id=body.pm_person_id, support_person_id=body.support_person_id, ctx=ctx)
    except SupportDelegationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except SupportDelegationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/{pm_person_id}", status_code=204)
def remove_support_delegation(pm_person_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)) -> Response:
    try:
        delete_delegation(db, pm_person_id=pm_person_id, ctx=ctx)
    except SupportDelegationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except SupportDelegationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return Response(status_code=204)
