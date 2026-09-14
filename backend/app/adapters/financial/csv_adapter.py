"""Implementação real (sem rede) que lê um CSV estruturado exportado do
Financial. Formato esperado (cabeçalho obrigatório):

    external_project_ref,category,amount,currency,reference

Uso previsto: enquanto não há decisão sobre API do Financial, um operador
exporta um CSV manualmente e aponta `FINANCIAL_CSV_PATH` para ele.
"""
from __future__ import annotations

import csv
from pathlib import Path

from app.adapters.financial.base import FinancialCostRecord

REQUIRED_COLUMNS = {"external_project_ref", "category", "amount", "currency"}


class CsvFinancialAdapter:
    def __init__(self, csv_path: str):
        self.csv_path = Path(csv_path)

    def fetch_real_costs(self) -> list[FinancialCostRecord]:
        if not self.csv_path.exists():
            raise FileNotFoundError(f"FINANCIAL_CSV_PATH não encontrado: {self.csv_path}")

        with self.csv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"CSV do Financial sem colunas obrigatórias: {sorted(missing)}")

            records = []
            for row in reader:
                records.append(
                    FinancialCostRecord(
                        external_project_ref=row["external_project_ref"],
                        category=row["category"],
                        amount=float(row["amount"]),
                        currency=row["currency"],
                        reference=row.get("reference") or None,
                    )
                )
            return records
