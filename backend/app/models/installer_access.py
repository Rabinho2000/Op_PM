"""Identity-to-installer memberships for the scoped external collaborator role.

The mapping deliberately stores only database identifiers.  Email/name matching
belongs to the later provisioning workflow and is never part of authorization.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import GUID, Base
from app.models.base import TimestampMixin, UUIDPk


class InstallerAccessMembership(UUIDPk, TimestampMixin, Base):
    __tablename__ = "installer_access_memberships"
    __table_args__ = (
        UniqueConstraint("person_id", "installer_id", name="uq_installer_access_membership_pair"),
        Index("ix_installer_access_memberships_person_active", "person_id", "is_active"),
        Index("ix_installer_access_memberships_installer_active", "installer_id", "is_active"),
    )

    person_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("people.id"), nullable=False)
    installer_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("installers.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    granted_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    granted_by_person_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("people.id"), nullable=True)
    revoked_by_person_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("people.id"), nullable=True)

    history: Mapped[list["InstallerAccessMembershipHistory"]] = relationship(
        back_populates="membership", cascade="all, delete-orphan", order_by="InstallerAccessMembershipHistory.occurred_at"
    )


class InstallerAccessMembershipHistory(UUIDPk, Base):
    __tablename__ = "installer_access_membership_history"
    __table_args__ = (Index("ix_installer_access_membership_history_pair", "person_id", "installer_id"),)

    membership_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("installer_access_memberships.id", ondelete="CASCADE"), nullable=False
    )
    person_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("people.id"), nullable=False)
    installer_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("installers.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    old_is_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    new_is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    changed_by_person_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("people.id"), nullable=True)
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    membership: Mapped[InstallerAccessMembership] = relationship(back_populates="history")
