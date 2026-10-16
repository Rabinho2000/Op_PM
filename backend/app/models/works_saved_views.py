"""Vistas pessoais guardadas do Calendário de obras."""
from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import GUID, Base
from app.models.base import TimestampMixin, UUIDPk


class WorksCalendarSavedView(UUIDPk, TimestampMixin, Base):
    """Uma combinação nomeada de filtros persistentes, propriedade do utilizador."""

    __tablename__ = "works_calendar_saved_views"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "name",
            name="uq_works_calendar_saved_views_user_name",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    zoom: Mapped[str] = mapped_column(
        String(16), default="month_days", nullable=False
    )
    lifecycle_status: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    pm_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    installer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("installers.id"), nullable=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("installer_teams.id"), nullable=True
    )
    show_idle: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    user: Mapped["User"] = relationship()


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.identity import User
