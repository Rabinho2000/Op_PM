"""Atomic installer membership mapping.

Provisioning is intentionally not an API operation in this stage.  These
helpers are the narrow data-layer contract for a later administrative runner;
callers own the surrounding transaction and must never match by email/name.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy.orm import Session, joinedload

from app.models.installer import Installer
from app.models.installer_access import InstallerAccessMembership, InstallerAccessMembershipHistory
from app.models.people import Person


class InstallerMembershipError(ValueError):
    pass


class InstallerMembershipNotFound(InstallerMembershipError):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _ensure_pair_exists(db: Session, *, person_id: uuid.UUID, installer_id: uuid.UUID) -> None:
    if db.get(Person, person_id) is None:
        raise InstallerMembershipNotFound("Pessoa não encontrada.")
    installer = db.get(Installer, installer_id)
    if installer is None:
        raise InstallerMembershipNotFound("Instalador não encontrado.")
    if not installer.is_active:
        raise InstallerMembershipError("O instalador não está ativo para provisionamento.")

def grant_installer_membership(
    db: Session,
    *,
    person_id: uuid.UUID,
    installer_id: uuid.UUID,
    changed_by_person_id: uuid.UUID | None = None,
) -> InstallerAccessMembership:
    """Activate one unique membership and append one grant transition.

    No commit is performed: membership and history are committed by the
    caller in one transaction, so a failed audit cannot leave access behind.
    """
    _ensure_pair_exists(db, person_id=person_id, installer_id=installer_id)
    membership = (
        db.query(InstallerAccessMembership)
        .filter(
            InstallerAccessMembership.person_id == person_id,
            InstallerAccessMembership.installer_id == installer_id,
        )
        .one_or_none()
    )
    if membership is None:
        membership = InstallerAccessMembership(
            person_id=person_id,
            installer_id=installer_id,
            is_active=True,
            granted_at=_now(),
            granted_by_person_id=changed_by_person_id,
        )
        db.add(membership)
        db.flush()
        old_is_active = None
    elif not membership.is_active:
        old_is_active = False
        membership.is_active = True
        membership.revoked_at = None
        membership.revoked_by_person_id = None
        membership.granted_at = _now()
        membership.granted_by_person_id = changed_by_person_id
        db.flush()
    else:
        return membership

    db.add(
        InstallerAccessMembershipHistory(
            membership_id=membership.id,
            person_id=person_id,
            installer_id=installer_id,
            action="grant",
            old_is_active=old_is_active,
            new_is_active=True,
            changed_by_person_id=changed_by_person_id,
            occurred_at=_now(),
        )
    )
    db.flush()
    return membership


def revoke_installer_membership(
    db: Session,
    *,
    person_id: uuid.UUID,
    installer_id: uuid.UUID,
    changed_by_person_id: uuid.UUID | None = None,
) -> InstallerAccessMembership:
    """Deactivate one membership and append a revoke transition idempotently."""
    membership = (
        db.query(InstallerAccessMembership)
        .filter(
            InstallerAccessMembership.person_id == person_id,
            InstallerAccessMembership.installer_id == installer_id,
        )
        .one_or_none()
    )
    if membership is None:
        raise InstallerMembershipNotFound("Associação instalador-pessoa não encontrada.")
    if not membership.is_active:
        return membership
    membership.is_active = False
    membership.revoked_at = _now()
    membership.revoked_by_person_id = changed_by_person_id
    db.flush()
    db.add(
        InstallerAccessMembershipHistory(
            membership_id=membership.id,
            person_id=person_id,
            installer_id=installer_id,
            action="revoke",
            old_is_active=True,
            new_is_active=False,
            changed_by_person_id=changed_by_person_id,
            occurred_at=_now(),
        )
    )
    db.flush()
    return membership


def list_assigned_installers(db: Session, ctx) -> list[Installer]:
    """Return only installers explicitly linked to the authenticated person."""
    if not ctx.has_permission("installer_team.view_assigned_installer"):
        return []
    if not ctx.active_installer_ids:
        return []
    return (
        db.query(Installer)
        .filter(Installer.id.in_(ctx.active_installer_ids))
        .options(joinedload(Installer.teams))
        .order_by(Installer.name.asc(), Installer.id.asc())
        .all()
    )



def active_installer_ids(db: Session, person_id: uuid.UUID) -> frozenset[uuid.UUID]:
    return frozenset(
        installer_id
        for (installer_id,) in db.query(InstallerAccessMembership.installer_id)
        .filter(
            InstallerAccessMembership.person_id == person_id,
            InstallerAccessMembership.is_active.is_(True),
        )
        .all()
    )
