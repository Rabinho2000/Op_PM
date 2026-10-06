from __future__ import annotations

import uuid
import datetime as dt

from sqlalchemy.orm import Session


from app.models.people import Person
from app.models.workflow import SupportDelegation, SupportDelegationHistory
from app.security.permissions import AuthContext, can_manage_support_delegations, PermissionDenied
from app.schemas.support_delegations import SupportDelegationRead


class SupportDelegationError(ValueError):
    pass


class SupportDelegationNotFound(SupportDelegationError):
    """A delegação ou pessoa indicada não existe."""


def _read(db: Session, row: SupportDelegation) -> SupportDelegationRead:
    pm = db.get(Person, row.pm_person_id)
    support = db.get(Person, row.support_person_id)
    return SupportDelegationRead(
        pm_person_id=row.pm_person_id,
        pm_display_name=pm.display_name if pm else "—",
        support_person_id=row.support_person_id,
        support_display_name=support.display_name if support else "—",
    )


def list_delegations(db: Session, ctx: AuthContext) -> list[SupportDelegationRead]:
    if not can_manage_support_delegations(ctx):
        raise PermissionDenied("admin.manage_users")
    return [_read(db, row) for row in db.query(SupportDelegation).all()]


def upsert_delegation(db: Session, *, pm_person_id: uuid.UUID, support_person_id: uuid.UUID, ctx: AuthContext) -> SupportDelegationRead:
    if not can_manage_support_delegations(ctx):
        raise PermissionDenied("admin.manage_users")
    if pm_person_id == support_person_id:
        raise SupportDelegationError("O PM não pode delegar em si próprio.")
    if db.get(Person, pm_person_id) is None or db.get(Person, support_person_id) is None:
        raise SupportDelegationNotFound("Pessoa não encontrada.")
    row = db.query(SupportDelegation).filter(SupportDelegation.pm_person_id == pm_person_id).one_or_none()
    old = row.support_person_id if row else None
    if row is None:
        row = SupportDelegation(pm_person_id=pm_person_id, support_person_id=support_person_id)
        db.add(row)
        action = "created"
    elif old == support_person_id:
        return _read(db, row)
    else:
        row.support_person_id = support_person_id
        action = "updated"
    db.add(SupportDelegationHistory(
        action=action,
        pm_person_id=pm_person_id,
        old_support_person_id=old,
        new_support_person_id=support_person_id,
        changed_by_person_id=ctx.person_id,
        created_at=dt.datetime.now(dt.UTC),
    ))
    try:
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(row)
    return _read(db, row)


def delete_delegation(db: Session, *, pm_person_id: uuid.UUID, ctx: AuthContext) -> None:
    if not can_manage_support_delegations(ctx):
        raise PermissionDenied("admin.manage_users")
    row = db.query(SupportDelegation).filter(SupportDelegation.pm_person_id == pm_person_id).one_or_none()
    if row is None:
        raise SupportDelegationNotFound("Delegação não encontrada.")
    db.delete(row)
    db.add(SupportDelegationHistory(
        action="deleted",
        pm_person_id=pm_person_id,
        old_support_person_id=row.support_person_id,
        new_support_person_id=None,
        changed_by_person_id=ctx.person_id,
        created_at=dt.datetime.now(dt.UTC),
    ))
    try:
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise
