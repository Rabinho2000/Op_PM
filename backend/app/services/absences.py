"""Camada de serviço para férias/ausências — visibilidade e escrita
sempre verificadas aqui, nunca confiadas ao chamador (mesmo padrão de
app/services/projects.py e app/services/tasks.py)."""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy.orm import Query, Session

from app.models.absence import ABSENCE_STATUSES, ABSENCE_TYPES, Absence
from app.models.people import Person
from app.schemas.absences import AbsenceCreate, AbsenceUpdate
from app.security.permissions import (
    AuthContext,
    PermissionDenied,
    can_create_absence_for,
    can_manage_absence,
    can_view_absence,
)


def visible_absences_query(db: Session, ctx: AuthContext) -> Query:
    if ctx.has_permission("absence.view_all"):
        return db.query(Absence)
    if ctx.has_permission("absence.view_own"):
        return db.query(Absence).filter(Absence.person_id == ctx.person_id)
    return db.query(Absence).filter(False)


def list_absences(
    db: Session,
    ctx: AuthContext,
    *,
    person_id: uuid.UUID | None = None,
    status: str | None = None,
    active_on_or_after: dt.date | None = None,
) -> list[Absence]:
    query = visible_absences_query(db, ctx)
    if person_id is not None:
        query = query.filter(Absence.person_id == person_id)
    if status is not None:
        query = query.filter(Absence.status == status)
    if active_on_or_after is not None:
        query = query.filter(Absence.end_date >= active_on_or_after)
    return query.order_by(Absence.start_date.asc()).all()


def get_visible_absence(db: Session, ctx: AuthContext, absence_id: uuid.UUID) -> Absence | None:
    absence = db.get(Absence, absence_id)
    if absence is None:
        return None
    if not can_view_absence(ctx, absence):
        return None
    return absence


def create_absence(db: Session, *, changes: AbsenceCreate, ctx: AuthContext) -> Absence:
    if not can_create_absence_for(ctx, changes.person_id):
        raise PermissionDenied("absence.manage_all|absence.manage_own")
    if db.get(Person, changes.person_id) is None:
        raise ValueError("Pessoa não encontrada.")
    if changes.type not in ABSENCE_TYPES:
        raise ValueError(f"Tipo de ausência inválido: {changes.type!r}")
    if changes.end_date < changes.start_date:
        raise ValueError("A data final não pode ser anterior à data inicial.")

    absence = Absence(
        person_id=changes.person_id,
        start_date=changes.start_date,
        end_date=changes.end_date,
        type=changes.type,
        note=changes.note,
        created_by_person_id=ctx.person_id,
    )
    db.add(absence)
    db.commit()
    db.refresh(absence)
    return absence


def update_absence(db: Session, *, absence: Absence, changes: AbsenceUpdate, ctx: AuthContext) -> Absence:
    if not can_manage_absence(ctx, absence):
        raise PermissionDenied("absence.manage_all|absence.manage_own")

    changed_fields = changes.model_dump(exclude_unset=True)
    if "status" in changed_fields and changed_fields["status"] not in ABSENCE_STATUSES:
        raise ValueError(f"Estado inválido: {changed_fields['status']!r}")

    for field_name, new_value in changed_fields.items():
        setattr(absence, field_name, new_value)

    db.commit()
    db.refresh(absence)
    return absence
