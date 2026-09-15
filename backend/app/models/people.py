"""Pessoas reais referenciadas no histórico operacional — PMs, chefe de
operações, técnicos — independentemente de terem ou não uma conta de login
(`User`). Ver app/models/identity.py para a justificação desta separação.
"""
from __future__ import annotations

import datetime as dt

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
    # Só o dia/mês importa para "aniversários próximos" no dashboard — o ano
    # é guardado tal como fornecido, mas nunca usado para calcular idade
    # nesta fase (ver app/services/dashboard.py).
    birth_date: Mapped[dt.date | None] = mapped_column(nullable=True)

    user: Mapped["User | None"] = relationship(back_populates="person", uselist=False)
