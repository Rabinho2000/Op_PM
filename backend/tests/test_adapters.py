"""Adapters de integração que ficam no código (ClickUp mock, Financial CSV):
sem qualquer chamada de rede."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.clickup.mock import MockClickUpAdapter
from app.adapters.financial.csv_adapter import CsvFinancialAdapter


def test_clickup_mock_reads_synthetic_fixture_only():
    adapter = MockClickUpAdapter()
    tasks = adapter.fetch_tasks()
    assert len(tasks) == 3
    assert all(t.task_id.startswith("cu_synth_") for t in tasks)


def test_financial_csv_adapter_reads_real_synthetic_csv():
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_financial_costs.csv"
    adapter = CsvFinancialAdapter(csv_path=str(fixture))
    records = adapter.fetch_real_costs()
    assert len(records) == 3
    assert {r.category for r in records} == {"material", "subempreiteiro", "mao_obra"}


def test_financial_csv_adapter_rejects_missing_file():
    adapter = CsvFinancialAdapter(csv_path="does_not_exist.csv")
    with pytest.raises(FileNotFoundError):
        adapter.fetch_real_costs()
