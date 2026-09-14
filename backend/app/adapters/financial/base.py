"""Interface de leitura de custos reais a partir do Financial (sistema real
não identificado no código legado — ver docs/OPEN_QUESTIONS.md, pergunta
bloqueante nº 5). Esta interface só lê; a plataforma nunca escreve custos
reais de volta no Financial. Suporta três modos possíveis (API, CSV, Excel);
nesta fase só o modo CSV tem implementação real (útil assim que exista um
export estruturado), API/Excel ficam como interface preparada.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass
class FinancialCostRecord:
    external_project_ref: str
    category: str
    # Decimal, nunca float — ver app/models/cost.py:MONEY e
    # tests/test_monetary_precision.py.
    amount: Decimal
    currency: str
    reference: str | None = None


class FinancialAdapter(Protocol):
    def fetch_real_costs(self) -> list[FinancialCostRecord]: ...
