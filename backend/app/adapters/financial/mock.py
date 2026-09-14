from __future__ import annotations

from app.adapters.financial.base import FinancialCostRecord


class MockFinancialAdapter:
    def fetch_real_costs(self) -> list[FinancialCostRecord]:
        return [
            FinancialCostRecord(
                external_project_ref="fin_synth_001",
                category="material",
                amount=1234.56,
                currency="EUR",
                reference="FAT-SYNTH-0001",
            )
        ]
