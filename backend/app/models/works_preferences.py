"""Preferência persistida da vista do Calendário de obras por utilizador."""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk


class UserWorksPreference(UUIDPk, TimestampMixin, Base):
    """Estado persistente da vista de obras, sempre ligado à conta autenticada."""

    __tablename__ = "works_calendar_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    zoom: Mapped[str] = mapped_column(String(16), default="month_days", nullable=False)
    lifecycle_status: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    pm_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    installer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("installers.id"), nullable=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("installer_teams.id"), nullable=True
    )
    show_idle: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User"] = relationship()


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.identity import User
