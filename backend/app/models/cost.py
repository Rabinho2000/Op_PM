"""Linhas de custo, separadas por tipo — nunca um único valor editável por
projeto. Ver docs/ARCHITECTURE_PROPOSAL.md secção "Fonte de verdade": valores
`real` só existem aqui como espelho do Financial (`source_system=financial`);
a plataforma nunca inventa um custo real, só o estimado/orçamentado.

`amount` usa `Numeric`, nunca `Float`: valores monetários não podem sofrer
erro de arredondamento binário (`0.1 + 0.1 + 0.1 != 0.3` em `float`) — ver
`tests/test_monetary_precision.py`.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk

# 12 dígitos, 2 casas decimais — suficiente para valores em EUR até
# 9 999 999 999,99. Rever se um dia forem necessárias moedas com mais casas
# decimais.
MONEY = Numeric(12, 2)


class CostLine(UUIDPk, TimestampMixin, Base):
    __tablename__ = "cost_lines"

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)  # material|subempreiteiro|mao_obra|deslocacao|outro
    # estimado | orcamentado | adjudicado | real
    cost_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    # plataforma | financial | ai_suggestion (nunca fonte de verdade sozinha)
    source_system: Mapped[str] = mapped_column(String(32), default="plataforma")
    reference: Mapped[str | None] = mapped_column(String(256), nullable=True)
