"""Metas e indicadores — página única "Metas e indicadores" (nunca duas
áreas separadas de menu "Metas"/"Dashboards", ver docs/PLAN_OPERATIONS_MVP.md
secção 8 e docs/PERFORMANCE_METRICS.md). `GoalPeriod` é só o objetivo
guardado; o cálculo do realizado é sempre feito no backend a partir dos
dados existentes (`Task`, `Project`) — nunca um segundo valor guardado que
possa divergir da fonte real.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk

PERIOD_TYPES: frozenset[str] = frozenset({"year", "quarter", "semester", "month"})
GOAL_METRICS: frozenset[str] = frozenset(
    {
        "installations",
        "kwp",
        "projects_completed",
        "projects_certified",
        "power_installed",
        "power_delivered",
    }
)
GOAL_SCOPES: frozenset[str] = frozenset({"company", "pm"})

# Numeric em vez de Float: uma meta de kWp tem casas decimais e entra em
# cálculos de percentagem/projeção — mesma regra de dinheiro/quantidades
# (D-018, e a extensão desta fase a quantidades de inventário).
GOAL_VALUE = Numeric(14, 3)


class GoalPeriod(UUIDPk, TimestampMixin, Base):
    __tablename__ = "goal_periods"

    period_type: Mapped[str] = mapped_column(String(16), nullable=False)
    year: Mapped[int] = mapped_column(nullable=False)
    quarter: Mapped[int | None] = mapped_column(nullable=True)
    semester: Mapped[int | None] = mapped_column(nullable=True)
    month: Mapped[int | None] = mapped_column(nullable=True)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    target_value: Mapped[Decimal] = mapped_column(GOAL_VALUE, nullable=False)
    scope: Mapped[str] = mapped_column(String(16), default="company", nullable=False)
    pm_person_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("people.id"), nullable=True)
    created_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")


class GoalPeriodHistory(UUIDPk, Base):
    """Append-only — mesmo padrão de `ProjectHistory`/`TaskHistory`."""

    __tablename__ = "goal_period_history"

    goal_period_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("goal_periods.id"), nullable=False)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(32), default="ui", nullable=False)
    changed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
