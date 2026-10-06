"""Endpoints de férias/ausências.

As transições de estado têm endpoints próprios; o PATCH genérico só altera a
nota e nunca pode mudar o estado.
"""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.absence import STATUS_APROVADA, STATUS_PENDENTE, Absence
from app.models.people import Person
from app.models.project import Project
from app.schemas.absences import (
    AbsenceCreate,
    AbsenceDecision,
    AbsenceOverlapRead,
    AbsenceRead,
    AbsenceUpdate,
    WorkOverlapRead,
)
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, PermissionDenied, can_approve_absence, can_manage_absence
from app.services.absences import (
    approve_absence,
    build_absence_warning_map,
    cancel_absence,
    create_absence,
    get_visible_absence,
    list_absences,
    reject_absence,
)
from app.services.absences import update_absence as update_absence_service

router = APIRouter(prefix="/api/absences", tags=["absences"])


def _people_by_id(db: Session, absences: list[Absence]) -> dict[uuid.UUID, Person]:
    ids = {
        person_id
        for absence in absences
        for person_id in (
            absence.person_id,
            absence.decided_by_person_id,
            absence.cancelled_by_person_id,
        )
        if person_id is not None
    }
    if not ids:
        return {}
    return {person.id: person for person in db.query(Person).filter(Person.id.in_(ids)).all()}


def _to_read(
    db: Session,
    absence: Absence,
    ctx: AuthContext,
    *,
    warning_map: dict[uuid.UUID, dict[str, list[Absence | Project]]] | None = None,
    people: dict[uuid.UUID, Person] | None = None,
) -> AbsenceRead:
    data = AbsenceRead.model_validate(absence)
    people = people or _people_by_id(db, [absence])
    person = people.get(absence.person_id)
    decided_by = people.get(absence.decided_by_person_id) if absence.decided_by_person_id else None
    cancelled_by = people.get(absence.cancelled_by_person_id) if absence.cancelled_by_person_id else None
    data.person_display_name = person.display_name if person else None
    data.decided_by_display_name = decided_by.display_name if decided_by else None
    data.cancelled_by_display_name = cancelled_by.display_name if cancelled_by else None

    data.can_approve = can_approve_absence(ctx) and absence.status == STATUS_PENDENTE
    data.can_reject = data.can_approve
    data.can_cancel = absence.status in (STATUS_PENDENTE, STATUS_APROVADA) and can_manage_absence(ctx, absence)

    if can_approve_absence(ctx):
        warnings = (warning_map or build_absence_warning_map(db, [absence])).get(absence.id, {})
        overlapping_absences = [item for item in warnings.get("absences", []) if isinstance(item, Absence)]
        overlapping_projects = [item for item in warnings.get("projects", []) if isinstance(item, Project)]

        data.overlapping_absences = [AbsenceOverlapRead.model_validate(item) for item in overlapping_absences]
        data.overlapping_absences_count = len(data.overlapping_absences)
        data.overlapping_projects = [WorkOverlapRead.model_validate(item) for item in overlapping_projects]
        data.overlapping_projects_count = len(data.overlapping_projects)
    return data


def _get_visible_or_404(db: Session, ctx: AuthContext, absence_id: uuid.UUID) -> Absence:
    absence = get_visible_absence(db, ctx, absence_id)
    if absence is None:
        raise HTTPException(status_code=404, detail="Ausência não encontrada ou sem permissão para a ver.")
    return absence


def _state_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionDenied):
        return HTTPException(status_code=403, detail=f"Sem permissão para alterar esta ausência: {exc}")
    return HTTPException(status_code=400, detail=str(exc))


@router.get("", response_model=list[AbsenceRead])
def list_absences_endpoint(
    person_id: uuid.UUID | None = None,
    status: str | None = None,
    active_on_or_after: dt.date | None = None,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[AbsenceRead]:
    absences = list_absences(db, ctx, person_id=person_id, status=status, active_on_or_after=active_on_or_after)
    people = _people_by_id(db, absences)
    warning_map = build_absence_warning_map(db, absences) if can_approve_absence(ctx) else None
    return [_to_read(db, a, ctx, warning_map=warning_map, people=people) for a in absences]


@router.get("/{absence_id}", response_model=AbsenceRead)
def get_absence_endpoint(
    absence_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> AbsenceRead:
    absence = _get_visible_or_404(db, ctx, absence_id)
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


@router.post("/{absence_id}/approve", response_model=AbsenceRead)
def approve_absence_endpoint(
    absence_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> AbsenceRead:
    absence = _get_visible_or_404(db, ctx, absence_id)
    try:
        updated = approve_absence(db, absence=absence, ctx=ctx)
    except (PermissionDenied, ValueError) as exc:
        raise _state_error(exc)
    return _to_read(db, updated, ctx)


@router.post("/{absence_id}/reject", response_model=AbsenceRead)
def reject_absence_endpoint(
    absence_id: uuid.UUID,
    body: AbsenceDecision,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> AbsenceRead:
    absence = _get_visible_or_404(db, ctx, absence_id)
    try:
        updated = reject_absence(db, absence=absence, note=body.note, ctx=ctx)
    except (PermissionDenied, ValueError) as exc:
        raise _state_error(exc)
    return _to_read(db, updated, ctx)


@router.post("/{absence_id}/cancel", response_model=AbsenceRead)
def cancel_absence_endpoint(
    absence_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> AbsenceRead:
    absence = _get_visible_or_404(db, ctx, absence_id)
    try:
        updated = cancel_absence(db, absence=absence, ctx=ctx)
    except (PermissionDenied, ValueError) as exc:
        raise _state_error(exc)
    return _to_read(db, updated, ctx)


@router.patch("/{absence_id}", response_model=AbsenceRead)
def update_absence_endpoint(
    absence_id: uuid.UUID,
    body: AbsenceUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> AbsenceRead:
    absence = _get_visible_or_404(db, ctx, absence_id)
    try:
        updated = update_absence_service(db, absence=absence, changes=body, ctx=ctx)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=f"Sem permissão para editar esta ausência: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _to_read(db, updated, ctx)
