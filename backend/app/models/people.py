"""Pessoas reais referenciadas no histórico operacional — PMs, chefe de
operações, técnicos — independentemente de terem ou não uma conta de login
(`User`). Ver app/models/identity.py para a justificação desta separação.
"""
from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UUIDPk


class Person(UUIDPk, TimestampMixin, Base):
    __tablename__ = "people"

    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    # Identificador herdado do sistema anterior (ex.: slug "pm_<nome>" usado
    # em files/pm_<nome>.json) — mantido só para rastreabilidade da migração,
    # nunca usado como chave de negócio.
    legacy_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped["User | None"] = relationship(back_populates="person", uselist=False)
