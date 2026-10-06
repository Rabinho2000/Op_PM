"""Camada de serviço para férias/ausências.

A autorização e a máquina de estados vivem aqui para que nenhum cliente possa
contornar a aprovação através de um PATCH ou de um payload manipulado.
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable

from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

from app.models.absence import (
    ABSENCE_TYPES,
    STATUS_APROVADA,
    STATUS_CANCELADA,
    STATUS_PENDENTE,
    STATUS_REJEITADA,
    TYPE_FERIAS,
    Absence,
)
from app.models.people import Person
from app.models.project import Project
from app.schemas.absences import AbsenceCreate, AbsenceUpdate
from app.security.permissions import (
    AuthContext,
    PermissionDenied,
    can_approve_absence,
    can_create_absence_for,
    can_manage_absence,
    can_view_absence,
)


APPROVAL_STATUSES = (STATUS_PENDENTE, STATUS_APROVADA)
WORK_STATUSES = ("preparacao", "construcao")


def visible_absences_query(db: Session, ctx: AuthContext) -> Query:
    # `absence.approve` é uma capacidade de decisão global. O catálogo atual
    # também concede `view_all` ao Chefe/Admin, mas manter este ramo torna a
    # regra segura para permissões atribuídas individualmente.
    if ctx.has_permission("absence.view_all") or can_approve_absence(ctx):
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


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def create_absence(db: Session, *, changes: AbsenceCreate, ctx: AuthContext) -> Absence:
    if not can_create_absence_for(ctx, changes.person_id):
        raise PermissionDenied("absence.manage_all|absence.manage_own")
    if db.get(Person, changes.person_id) is None:
        raise ValueError("Pessoa não encontrada.")
    if changes.type not in ABSENCE_TYPES:
        raise ValueError(f"Tipo de ausência inválido: {changes.type!r}")
    if changes.end_date < changes.start_date:
        raise ValueError("A data final não pode ser anterior à data inicial.")

    auto_approved = changes.type != TYPE_FERIAS or can_approve_absence(ctx)
    decided_at = _now_utc() if auto_approved else None
    absence = Absence(
        person_id=changes.person_id,
        start_date=changes.start_date,
        end_date=changes.end_date,
        type=changes.type,
        note=changes.note,
        status=STATUS_APROVADA if auto_approved else STATUS_PENDENTE,
        created_by_person_id=ctx.person_id,
        decided_by_person_id=ctx.person_id if auto_approved else None,
        decided_at=decided_at,
        decision_note="",
    )
    db.add(absence)
    db.commit()
    db.refresh(absence)
    return absence


def update_absence(db: Session, *, absence: Absence, changes: AbsenceUpdate, ctx: AuthContext) -> Absence:
    if not can_manage_absence(ctx, absence):
        raise PermissionDenied("absence.manage_all|absence.manage_own")

    changed_fields = changes.model_dump(exclude_unset=True)
    if "note" in changed_fields and changed_fields["note"] is not None:
        absence.note = changed_fields["note"]

    db.commit()
    db.refresh(absence)
    return absence


def approve_absence(db: Session, *, absence: Absence, ctx: AuthContext) -> Absence:
    if not can_approve_absence(ctx):
        raise PermissionDenied("absence.approve")
    if absence.status != STATUS_PENDENTE:
        raise ValueError("Só é possível aprovar uma ausência pendente.")
    absence.status = STATUS_APROVADA
    absence.decided_by_person_id = ctx.person_id
    absence.decided_at = _now_utc()
    db.commit()
    db.refresh(absence)
    return absence


def reject_absence(db: Session, *, absence: Absence, note: str, ctx: AuthContext) -> Absence:
    if not can_approve_absence(ctx):
        raise PermissionDenied("absence.approve")
    if absence.status != STATUS_PENDENTE:
        raise ValueError("Só é possível rejeitar uma ausência pendente.")
    clean_note = note.strip()
    if not clean_note:
        raise ValueError("A nota de rejeição é obrigatória.")
    absence.status = STATUS_REJEITADA
    absence.decided_by_person_id = ctx.person_id
    absence.decided_at = _now_utc()
    absence.decision_note = clean_note
    db.commit()
    db.refresh(absence)
    return absence


def cancel_absence(db: Session, *, absence: Absence, ctx: AuthContext) -> Absence:
    if not can_manage_absence(ctx, absence):
        raise PermissionDenied("absence.manage_all|absence.manage_own")
    if absence.status not in APPROVAL_STATUSES:
        raise ValueError("Uma ausência rejeitada ou já cancelada não pode voltar a ser alterada.")
    absence.status = STATUS_CANCELADA
    # O cancelamento é uma ação posterior à decisão. Nunca substituir a
    # auditoria de quem aprovou/rejeitou a ausência.
    absence.cancelled_by_person_id = ctx.person_id
    absence.cancelled_at = _now_utc()
    db.commit()
    db.refresh(absence)
    return absence


def _intersects(start: dt.date, end: dt.date, other_start: dt.date, other_end: dt.date) -> bool:
    return other_start <= end and other_end >= start


def build_absence_warning_map(
    db: Session, absences: Iterable[Absence]
) -> dict[uuid.UUID, dict[str, list[Absence | Project]]]:
    """Calcula avisos para uma listagem em bloco, sem consultas por linha."""
    targets = list(absences)
    if not targets:
        return {}
    person_ids = {absence.person_id for absence in targets}
    min_start = min(absence.start_date for absence in targets)
    max_end = max(absence.end_date for absence in targets)

    other_absences = (
        db.query(Absence)
        .filter(
            Absence.person_id.in_(person_ids),
            Absence.status.in_((STATUS_PENDENTE, STATUS_APROVADA)),
            Absence.end_date >= min_start,
            Absence.start_date <= max_end,
        )
        .all()
    )
    projects = (
        db.query(Project)
        .filter(
            Project.pm_person_id.in_(person_ids),
            Project.is_active.is_(True),
            or_(Project.lifecycle_status.in_(WORK_STATUSES), Project.lifecycle_status.is_(None)),
            Project.work_start_date.isnot(None),
            Project.work_end_date.isnot(None),
            Project.work_end_date >= min_start,
            Project.work_start_date <= max_end,
        )
        .all()
    )

    result: dict[uuid.UUID, dict[str, list[Absence | Project]]] = {}
    for absence in targets:
        overlaps: list[Absence | Project] = [
            other
            for other in other_absences
            if other.id != absence.id
            and other.person_id == absence.person_id
            and _intersects(absence.start_date, absence.end_date, other.start_date, other.end_date)
        ]
        project_overlaps: list[Absence | Project] = [
            project
            for project in projects
            if project.pm_person_id == absence.person_id
            and project.work_start_date is not None
            and project.work_end_date is not None
            and _intersects(absence.start_date, absence.end_date, project.work_start_date, project.work_end_date)
        ]
        result[absence.id] = {
            "absences": overlaps,
            "projects": project_overlaps,
        }
    return result
