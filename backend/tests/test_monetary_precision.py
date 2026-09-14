"""Precisão monetária: `Numeric`/`Decimal`, nunca `Float` (ver
docs/DECISIONS.md D-018). O caso clássico `0.1 + 0.1 + 0.1 != 0.3` em
`float` binário é usado deliberadamente para provar que o problema que
`Numeric` evita é real, não teórico.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.adapters.financial.csv_adapter import CsvFinancialAdapter
from app.models.cost import CostLine
from app.models.inventory import MaterialRequest, MaterialRequestItem
from app.models.project import Project


def test_float_would_lose_precision_here_but_decimal_does_not():
    """Não testa o código da aplicação — prova, para o registo, que o
    problema que motivou D-018 é real neste ambiente Python/SQLite."""
    assert 0.1 + 0.1 + 0.1 != 0.3  # o problema que Numeric/Decimal evita
    assert Decimal("0.1") + Decimal("0.1") + Decimal("0.1") == Decimal("0.3")


def test_cost_line_amount_round_trips_as_decimal_without_error(db_session):
    db = db_session
    project = Project(name="Projeto Sintético para Custos")
    db.add(project)
    db.flush()

    amounts = [Decimal("0.10"), Decimal("0.10"), Decimal("0.10")]
    for amount in amounts:
        db.add(
            CostLine(
                project_id=project.id,
                category="material",
                cost_type="estimado",
                amount=amount,
            )
        )
    db.flush()

    total = sum(
        (cl.amount for cl in db.query(CostLine).filter(CostLine.project_id == project.id).all()),
        start=Decimal("0"),
    )
    assert isinstance(total, Decimal)
    assert total == Decimal("0.30")
    db.rollback()


def test_cost_line_amount_is_decimal_type_after_read_back(db_session):
    db = db_session
    project = Project(name="Projeto Sintético para Tipo de Custo")
    db.add(project)
    db.flush()
    db.add(CostLine(project_id=project.id, category="material", cost_type="real", amount=Decimal("1234.56")))
    db.commit()

    fetched = db.query(CostLine).filter(CostLine.project_id == project.id).one()
    assert isinstance(fetched.amount, Decimal)
    assert fetched.amount == Decimal("1234.56")


def test_material_request_item_unit_price_is_decimal(db_session):
    db = db_session
    project = Project(name="Projeto Sintético para Pedido de Material")
    db.add(project)
    db.flush()
    request = MaterialRequest(project_id=project.id, status="rascunho")
    db.add(request)
    db.flush()
    item = MaterialRequestItem(
        request_id=request.id,
        description="Item sintético",
        quantity=3,
        unit_price=Decimal("19.99"),
    )
    db.add(item)
    db.commit()

    fetched = db.query(MaterialRequestItem).filter(MaterialRequestItem.request_id == request.id).one()
    assert isinstance(fetched.unit_price, Decimal)
    assert fetched.unit_price * 3 == Decimal("59.97")


def test_csv_financial_adapter_parses_amount_as_exact_decimal():
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_financial_costs.csv"
    adapter = CsvFinancialAdapter(csv_path=str(fixture))
    records = adapter.fetch_real_costs()

    assert all(isinstance(r.amount, Decimal) for r in records)
    total = sum((r.amount for r in records), start=Decimal("0"))
    # 1234.56 + 2500.00 + 800.00 = 4534.56 — soma exata, sem resíduo de
    # arredondamento binário (o que aconteceria facilmente com float).
    assert total == Decimal("4534.56")
