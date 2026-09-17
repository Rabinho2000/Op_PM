"""Regras de negócio do livro de movimentos de inventário — ver
app/services/inventory.py e docs/INVENTORY_RULES.md. Testes ao nível do
serviço (sem HTTP) para isolar a lógica de cálculo de stock das
permissões, que são testadas em test_inventory_api.py.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.inventory import InventoryItem
from app.models.project import Project
from app.services.inventory import (
    InsufficientReservationError,
    InsufficientStockError,
    adjust_stock,
    available_stock,
    consume_from_project,
    consumed_for_project,
    enter_stock,
    material_requirement_status,
    physical_stock_central,
    release_reservation,
    reserve_for_project,
    reserved_for_project,
    return_to_stock,
)


@pytest.fixture()
def cable_item(db_session):
    item = InventoryItem(sku="TEST-CABLE", name="Cabo de teste", unit="km")
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


@pytest.fixture()
def project_a(db_session):
    return db_session.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


def test_worked_example_from_the_request(db_session, cable_item, project_a):
    """100 km entram -> reservar 20 km para o Projeto A -> consumir 5 km ->
    libertar 10 km ⇒ físico 95, disponível 90, reservado 5, consumido 5 —
    exatamente o exemplo do pedido original."""
    db = db_session
    enter_stock(db, item=cable_item, quantity=Decimal("100"), created_by_person_id=None)
    reserve_for_project(
        db, item=cable_item, project_id=project_a.id, quantity=Decimal("20"), created_by_person_id=None
    )
    consume_from_project(
        db, item=cable_item, project_id=project_a.id, quantity=Decimal("5"), created_by_person_id=None
    )
    release_reservation(
        db, item=cable_item, project_id=project_a.id, quantity=Decimal("10"), created_by_person_id=None
    )

    assert physical_stock_central(db, cable_item.id) == Decimal("95")
    assert available_stock(db, cable_item.id) == Decimal("90")
    assert reserved_for_project(db, cable_item.id, project_a.id) == Decimal("5")
    assert consumed_for_project(db, cable_item.id, project_a.id) == Decimal("5")


def test_cannot_reserve_more_than_available(db_session, cable_item, project_a):
    db = db_session
    enter_stock(db, item=cable_item, quantity=Decimal("10"), created_by_person_id=None)
    with pytest.raises(InsufficientStockError):
        reserve_for_project(
            db, item=cable_item, project_id=project_a.id, quantity=Decimal("11"), created_by_person_id=None
        )


def test_cannot_consume_more_than_reserved(db_session, cable_item, project_a):
    db = db_session
    enter_stock(db, item=cable_item, quantity=Decimal("10"), created_by_person_id=None)
    reserve_for_project(
        db, item=cable_item, project_id=project_a.id, quantity=Decimal("5"), created_by_person_id=None
    )
    with pytest.raises(InsufficientReservationError):
        consume_from_project(
            db, item=cable_item, project_id=project_a.id, quantity=Decimal("6"), created_by_person_id=None
        )


def test_cannot_release_more_than_reserved(db_session, cable_item, project_a):
    db = db_session
    enter_stock(db, item=cable_item, quantity=Decimal("10"), created_by_person_id=None)
    reserve_for_project(
        db, item=cable_item, project_id=project_a.id, quantity=Decimal("5"), created_by_person_id=None
    )
    with pytest.raises(InsufficientReservationError):
        release_reservation(
            db, item=cable_item, project_id=project_a.id, quantity=Decimal("6"), created_by_person_id=None
        )


def test_return_to_stock_increases_physical_without_reopening_reservation(db_session, cable_item, project_a):
    db = db_session
    enter_stock(db, item=cable_item, quantity=Decimal("10"), created_by_person_id=None)
    reserve_for_project(
        db, item=cable_item, project_id=project_a.id, quantity=Decimal("10"), created_by_person_id=None
    )
    consume_from_project(
        db, item=cable_item, project_id=project_a.id, quantity=Decimal("4"), created_by_person_id=None
    )
    return_to_stock(
        db, item=cable_item, project_id=project_a.id, quantity=Decimal("4"), created_by_person_id=None
    )

    assert physical_stock_central(db, cable_item.id) == Decimal("10")  # 10 - 4 + 4
    assert reserved_for_project(db, cable_item.id, project_a.id) == Decimal("6")  # reserva não reabre
    assert consumed_for_project(db, cable_item.id, project_a.id) == Decimal("0")  # 4 - 4


def test_cannot_return_more_than_consumed(db_session, cable_item, project_a):
    db = db_session
    enter_stock(db, item=cable_item, quantity=Decimal("10"), created_by_person_id=None)
    reserve_for_project(
        db, item=cable_item, project_id=project_a.id, quantity=Decimal("5"), created_by_person_id=None
    )
    consume_from_project(
        db, item=cable_item, project_id=project_a.id, quantity=Decimal("2"), created_by_person_id=None
    )
    with pytest.raises(Exception):
        return_to_stock(
            db, item=cable_item, project_id=project_a.id, quantity=Decimal("3"), created_by_person_id=None
        )


def test_adjust_stock_cannot_make_physical_stock_negative(db_session, cable_item):
    db = db_session
    enter_stock(db, item=cable_item, quantity=Decimal("5"), created_by_person_id=None)
    with pytest.raises(InsufficientStockError):
        adjust_stock(db, item=cable_item, delta=Decimal("-6"), created_by_person_id=None)


def test_adjust_stock_positive_and_negative(db_session, cable_item):
    db = db_session
    enter_stock(db, item=cable_item, quantity=Decimal("5"), created_by_person_id=None)
    adjust_stock(db, item=cable_item, delta=Decimal("2"), created_by_person_id=None, reference="Contagem física")
    assert physical_stock_central(db, cable_item.id) == Decimal("7")
    adjust_stock(db, item=cable_item, delta=Decimal("-3"), created_by_person_id=None, reference="Quebra")
    assert physical_stock_central(db, cable_item.id) == Decimal("4")


def test_idempotency_key_prevents_duplicate_movement(db_session, cable_item):
    db = db_session
    m1 = enter_stock(
        db, item=cable_item, quantity=Decimal("5"), created_by_person_id=None, idempotency_key="retry-1"
    )
    m2 = enter_stock(
        db, item=cable_item, quantity=Decimal("5"), created_by_person_id=None, idempotency_key="retry-1"
    )
    assert m1.id == m2.id
    assert physical_stock_central(db, cable_item.id) == Decimal("5")


def test_reservations_do_not_affect_other_projects(db_session, cable_item, project_a):
    db = db_session
    other_project = db_session.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()
    enter_stock(db, item=cable_item, quantity=Decimal("20"), created_by_person_id=None)
    reserve_for_project(
        db, item=cable_item, project_id=project_a.id, quantity=Decimal("10"), created_by_person_id=None
    )
    assert reserved_for_project(db, cable_item.id, other_project.id) == Decimal("0")
    assert available_stock(db, cable_item.id) == Decimal("10")


def test_material_requirement_status_reports_missing_and_sufficiency(db_session, cable_item, project_a):
    db = db_session
    enter_stock(db, item=cable_item, quantity=Decimal("10"), created_by_person_id=None)
    reserve_for_project(
        db, item=cable_item, project_id=project_a.id, quantity=Decimal("4"), created_by_person_id=None
    )
    status = material_requirement_status(
        db, project_id=project_a.id, item=cable_item, quantity_required=Decimal("10")
    )
    assert status.reserved == Decimal("4")
    assert status.missing == Decimal("6")
    # disponível = 10 - 4 = 6, exatamente o que falta -> suficiente
    assert status.available_stock_sufficient is True

    status_short = material_requirement_status(
        db, project_id=project_a.id, item=cable_item, quantity_required=Decimal("20")
    )
    assert status_short.missing == Decimal("16")
    assert status_short.available_stock_sufficient is False
