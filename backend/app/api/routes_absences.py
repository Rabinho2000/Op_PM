"""Endpoints de férias/ausências: listagem/filtros, criação, e edição de
estado (ex. cancelar). Toda a escrita passa por `app/services/absences.py`.
"""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.absence import STATUS_CANCELADA, Absence
from app.models.people import Person
from app.schemas.absences import AbsenceCreate, AbsenceRead, AbsenceUpdate
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, PermissionDenied, can_manage_absence
from app.services.absences import create_absence, get_visible_absence, list_absences
from app.services.absences import update_absence as update_absence_service

router = APIRouter(prefix="/api/absences", tags=["absences"])


def _to_read(db: Session, absence: Absence, ctx: AuthContext) -> AbsenceRead:
    data = AbsenceRead.model_validate(absence)
    person = absence.person or db.get(Person, absence.person_id)
    data.person_display_name = person.display_name if person else None
    data.can_cancel = absence.status != STATUS_CANCELADA and can_manage_absence(ctx, absence)
    return data


@router.get("", response_model=list[AbsenceRead])
def list_absences_endpoint(
    person_id: uuid.UUID | None = None,
    status: str | None = None,
    active_on_or_after: dt.date | None = None,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[AbsenceRead]:
    absences = list_absences(db, ctx, person_id=person_id, status=status, active_on_or_after=active_on_or_after)
    return [_to_read(db, a, ctx) for a in absences]


@router.get("/{absence_id}", response_model=AbsenceRead)
def get_absence_endpoint(
    absence_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> AbsenceRead:
    absence = get_visible_absence(db, ctx, absence_id)
    if absence is None:
        raise HTTPException(status_code=404, detail="Ausência não encontrada ou sem permissão para a ver.")
    return _to_read(db, absence, ctx)


@router.post("", response_model=AbsenceRead, status_code=201)
def create_absence_endpoint(
    body: AbsenceCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> AbsenceRead:
    try:
        absence = create_absence(db, changes=body, ctx=ctx)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=f"Sem permissão para registar esta ausência: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _to_read(db, absence, ctx)


@router.patch("/{absence_id}", response_model=AbsenceRead)
def update_absence_endpoint(
    absence_id: uuid.UUID,
    body: AbsenceUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> AbsenceRead:
    absence = db.get(Absence, absence_id)
    if absence is None:
        raise HTTPException(status_code=404, detail="Ausência não encontrada.")
    try:
        updated = update_absence_service(db, absence=absence, changes=body, ctx=ctx)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=f"Sem permissão para editar esta ausência: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _to_read(db, updated, ctx)
