"""Modelos append-only dos pedidos de suporte iniciados pelos utilizadores."""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import GUID, Base
from app.models.base import TimestampMixin, UUIDPk

REQUEST_STATUS_OPEN = "open"
REQUEST_STATUS_RESOLVED = "resolved"
REQUEST_STATUSES = frozenset({REQUEST_STATUS_OPEN, REQUEST_STATUS_RESOLVED})


class UserRequest(UUIDPk, TimestampMixin, Base):
    """A request thread; messages are never edited or deleted by the API."""

    __tablename__ = "user_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'resolved')",
            name="ck_user_requests_status",
        ),
        Index("ix_user_requests_status_updated_at", "status", "updated_at"),
    )

    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=REQUEST_STATUS_OPEN,
        server_default=REQUEST_STATUS_OPEN,
    )
    page_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=True
    )

    created_by_user: Mapped["User"] = relationship(
        foreign_keys=[created_by_user_id]
    )
    resolved_by_user: Mapped["User | None"] = relationship(
        foreign_keys=[resolved_by_user_id]
    )
    messages: Mapped[list["UserRequestMessage"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="UserRequestMessage.created_at, UserRequestMessage.id",
    )


class UserRequestMessage(UUIDPk, Base):
    """One immutable message in a user request thread."""

    __tablename__ = "user_request_messages"
    __table_args__ = (
        Index(
            "ix_user_request_messages_request_id_created_at",
            "request_id",
            "created_at",
        ),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("user_requests.id", ondelete="CASCADE"), nullable=False
    )
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=False
    )
    is_staff_reply: Mapped[bool] = mapped_column(Boolean(), nullable=False)
    body: Mapped[str] = mapped_column(Text(), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    request: Mapped[UserRequest] = relationship(back_populates="messages")
    author_user: Mapped["User"] = relationship(foreign_keys=[author_user_id])


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.identity import User
