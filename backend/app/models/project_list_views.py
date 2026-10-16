"""Persisted personal configuration for the Projects list."""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk


class UserProjectListPreference(UUIDPk, TimestampMixin, Base):
    """One complete Projects-list configuration per authenticated account."""

    __tablename__ = "project_list_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    config: Mapped[dict] = mapped_column(JSON, nullable=False)

    user: Mapped["User"] = relationship()


class ProjectListView(UUIDPk, TimestampMixin, Base):
    """A named, active personal Projects-list configuration.

    Deleted views stay in this table with ``is_active=False``.  The partial
    unique index lets an account reuse a name after a logical deletion while
    still making active duplicates impossible at the database boundary.
    """

    __tablename__ = "project_list_views"
    __table_args__ = (
        Index(
            "uq_project_list_views_active_user_name",
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


# Explicit aliases keep the domain names easy to discover for callers while
# retaining the table/model names used by the API service.
ProjectListPreference = UserProjectListPreference
ProjectListSavedView = ProjectListView

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.identity import User
