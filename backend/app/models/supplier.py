from __future__ import annotations

from sqlalchemy import Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDPk


class Supplier(UUIDPk, TimestampMixin, Base):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(256), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_preferred: Mapped[bool] = mapped_column(default=False, nullable=False)
    lead_time_days: Mapped[int | None] = mapped_column(nullable=True)
    # Lista livre de materiais fornecidos (texto, sem tabela de associação
    # nesta fase — ver docs/PLAN_OPERATIONS_MVP.md secção 11, decisão assumida).
    materials: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
