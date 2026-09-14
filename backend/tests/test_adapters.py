"""Adapters de integração — todos em modo mock/fallback local nesta fase,
sem qualquer chamada de rede."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.adapters.clickup.mock import MockClickUpAdapter
from app.adapters.financial.csv_adapter import CsvFinancialAdapter
from app.adapters.financial.mock import MockFinancialAdapter
from app.adapters.graph.local_fallback import LocalFallbackGraphAdapter


def test_clickup_mock_reads_synthetic_fixture_only():
    adapter = MockClickUpAdapter()
    tasks = adapter.fetch_tasks()
    assert len(tasks) == 3
    assert all(t.task_id.startswith("cu_synth_") for t in tasks)


def test_financial_mock_returns_synthetic_record():
    adapter = MockFinancialAdapter()
    records = adapter.fetch_real_costs()
    assert len(records) == 1
    assert records[0].external_project_ref == "fin_synth_001"


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


def test_graph_fallback_writes_local_eml_never_sends():
    with tempfile.TemporaryDirectory() as tmp:
        adapter = LocalFallbackGraphAdapter(output_dir=tmp)
        result = adapter.create_draft_email(to="cliente.sintetico@example.invalid", subject="Assunto de teste", body="Corpo de teste")
        assert result.was_sent is False
        assert Path(result.reference).exists()
        assert Path(result.reference).suffix == ".eml"


def test_graph_fallback_send_mail_requires_approval_and_still_never_sends():
    with tempfile.TemporaryDirectory() as tmp:
        adapter = LocalFallbackGraphAdapter(output_dir=tmp)
        with pytest.raises(PermissionError):
            adapter.send_mail(to="x@example.invalid", subject="s", body="b", approved_by="")

        result = adapter.send_mail(to="x@example.invalid", subject="s", body="b", approved_by="chefe.sintetico@example.invalid")
        assert result.was_sent is False  # nunca envia realmente, mesmo aprovado
        assert Path(result.reference).exists()


def test_graph_fallback_create_event_writes_ics_never_publishes():
    with tempfile.TemporaryDirectory() as tmp:
        adapter = LocalFallbackGraphAdapter(output_dir=tmp)
        result = adapter.create_event(
            title="Visita sintética",
            starts_at="2026-01-10T09:00:00+00:00",
            ends_at="2026-01-10T10:00:00+00:00",
            attendees=["pm.um.sintetico@example.invalid"],
            approved_by="chefe.sintetico@example.invalid",
        )
        assert result.was_published is False
        assert Path(result.reference).suffix == ".ics"
        content = Path(result.reference).read_text(encoding="utf-8")
        assert "BEGIN:VEVENT" in content
