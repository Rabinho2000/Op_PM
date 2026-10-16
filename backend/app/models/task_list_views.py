"""Persisted personal configuration for the Tasks list."""
from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import GUID, Base
from app.models.base import TimestampMixin, UUIDPk


class UserTaskListPreference(UUIDPk, TimestampMixin, Base):
    """One complete Tasks-list configuration per authenticated account."""

    __tablename__ = "task_list_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    config: Mapped[dict] = mapped_column(JSON, nullable=False)

    user: Mapped["User"] = relationship()


class TaskListView(UUIDPk, TimestampMixin, Base):
    """A named, active personal Tasks-list configuration."""

    __tablename__ = "task_list_views"
    __table_args__ = (
        Index(
            "uq_task_list_views_active_user_name",
            "user_id",
            "name",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active IS TRUE"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped["User"] = relationship()


TaskListPreference = UserTaskListPreference
TaskListSavedView = TaskListView

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.identity import User
