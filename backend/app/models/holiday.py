from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDPk
from app.models.constraints import vocabulary_check

HOLIDAY_SCOPES = frozenset({"nacional", "municipal", "empresa"})


class Holiday(UUIDPk, TimestampMixin, Base):
    __tablename__ = "holidays"
    __table_args__ = (
        Index("ix_holidays_date_active", "date", "is_active"),
        vocabulary_check("scope", HOLIDAY_SCOPES, name="ck_holidays_scope"),
    )

    date: Mapped[dt.date] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"), nullable=False)
