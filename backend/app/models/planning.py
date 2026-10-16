"""Preferências pessoais da vista de planeamento.

A preferência é deliberadamente local à conta autenticada: não altera a
visibilidade, as permissões, nem as definições dos restantes utilizadores.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk

if TYPE_CHECKING:
    from app.models.identity import User


class UserPlanningPreference(UUIDPk, TimestampMixin, Base):
    __tablename__ = "planning_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    view: Mapped[str] = mapped_column(String(16), default="month", nullable=False)
    hide_weekends: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User"] = relationship()
