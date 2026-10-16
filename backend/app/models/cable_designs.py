"""Project-linked AC cable dimensioning studies and their append-only audit."""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import GUID, Base
from app.models.base import TimestampMixin, UUIDPk


CABLE_DESIGN_STATUS_DRAFT = "rascunho"
CABLE_DESIGN_STATUS_REVIEW = "em_analise"
CABLE_DESIGN_STATUS_APPROVED = "aprovado"
CABLE_DESIGN_STATUSES = frozenset(
    {CABLE_DESIGN_STATUS_DRAFT, CABLE_DESIGN_STATUS_REVIEW, CABLE_DESIGN_STATUS_APPROVED}
)

CABLE_REVISION_STATUS_DRAFT = "rascunho"
CABLE_REVISION_STATUS_APPROVED = "aprovada"
CABLE_REVISION_STATUSES = frozenset(
    {CABLE_REVISION_STATUS_DRAFT, CABLE_REVISION_STATUS_APPROVED}
)

CABLE_DESIGN_HISTORY_ACTIONS = frozenset(
    {"created", "saved", "submitted", "approved", "new_revision", "deactivated"}
)


class CableDesign(UUIDPk, TimestampMixin, Base):
    """A cable-dimensioning study attached to exactly one project."""

    __tablename__ = "cable_designs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('rascunho', 'em_analise', 'aprovado')",
            name="ck_cable_designs_status",
        ),
        Index("ix_cable_designs_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=CABLE_DESIGN_STATUS_DRAFT, server_default=CABLE_DESIGN_STATUS_DRAFT
    )
    current_revision: Mapped[str] = mapped_column(
        String(8), nullable=False, default="A", server_default="A"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    created_by_person_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=False
    )

    project: Mapped["Project"] = relationship()
    created_by: Mapped["Person"] = relationship(foreign_keys=[created_by_person_id])
    revisions: Mapped[list["CableDesignRevision"]] = relationship(
        back_populates="design",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CableDesignRevision.rev",
    )
    history: Mapped[list["CableDesignHistory"]] = relationship(
        back_populates="design",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CableDesignHistory.created_at",
    )


class CableDesignRevision(UUIDPk, TimestampMixin, Base):
    """One revision's canonical JSON content.

    Only the current draft/review revision is updated by the service. Approved
    rows remain append-only and are copied into a new draft for further work.
    """

    __tablename__ = "cable_design_revisions"
    __table_args__ = (
        UniqueConstraint("design_id", "rev", name="uq_cable_design_revision"),
        CheckConstraint(
            "status IN ('rascunho', 'aprovada')",
            name="ck_cable_design_revisions_status",
        ),
    )

    design_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("cable_designs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rev: Mapped[str] = mapped_column(String(8), nullable=False)
    input_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    unresolved_circuits: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=CABLE_REVISION_STATUS_DRAFT, server_default=CABLE_REVISION_STATUS_DRAFT
    )
    approved_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    approved_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_person_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=False
    )

    design: Mapped[CableDesign] = relationship(back_populates="revisions")
    approved_by: Mapped["Person | None"] = relationship(foreign_keys=[approved_by_person_id])
    created_by: Mapped["Person"] = relationship(foreign_keys=[created_by_person_id])


class CableDesignHistory(UUIDPk, Base):
    """Append-only, short state transitions for a cable design."""

    __tablename__ = "cable_design_history"

    design_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("cable_designs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_person_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=False
    )
    rev: Mapped[str] = mapped_column(String(8), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    design: Mapped[CableDesign] = relationship(back_populates="history")
    actor: Mapped["Person"] = relationship(foreign_keys=[actor_person_id])


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.people import Person
    from app.models.project import Project
