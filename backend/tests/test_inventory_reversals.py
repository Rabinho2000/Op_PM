"""Contract tests for project inventory reversals.

The original movement is immutable; an explicit compensating movement carries
its actor, timestamp, reason and a single link back to the original.
"""
from __future__ import annotations

from decimal import Decimal
from threading import Barrier, Thread
import uuid

import pytest

from app.db import Base
from app.models.inventory import (
    MOVEMENT_CONSUMO,
    MOVEMENT_DEVOLUCAO,
    MOVEMENT_ENTREGA,
    MOVEMENT_ENTRADA,
    MOVEMENT_RECOLHA,
    MOVEMENT_RESERVA,
    InventoryItem,
    InventoryLocation,
    InventoryMovement,
)
from app.models.project import Project
from app.services.inventory import (
    available_stock,
    consumed_for_project,
    on_site_for_project,
    physical_stock_central,
    reserved_for_project,
    reverse_project_movement,
    total_reserved,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _headers(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _own_project(db) -> Project:
    return db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


def _other_project(db) -> Project:
    return db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()


def _item(db, sku: str) -> InventoryItem:
    item = InventoryItem(sku=sku, name="Artigo de reversão sintético", unit="un")
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _seed_stock(api_client, item: InventoryItem, quantity: str = "20.000") -> None:
    response = api_client.post(
        "/api/inventory/movements",
        json={"item_id": str(item.id), "movement_type": "entrada", "quantity": quantity},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert response.status_code == 201, response.text


def _balance_snapshot(db, item: InventoryItem, project: Project) -> dict[str, Decimal | int]:
    return {
        "movement_count": db.query(InventoryMovement).filter(InventoryMovement.item_id == item.id).count(),
        "physical": physical_stock_central(db, item.id),
        "available": available_stock(db, item.id),
        "total_reserved": total_reserved(db, item.id),
        "reserved": reserved_for_project(db, item.id, project.id),
        "consumed": consumed_for_project(db, item.id, project.id),
        "on_site": on_site_for_project(db, item.id, project.id),
    }


def test_reverse_preserves_original_and_records_precise_audit(db_session, api_client):
    item = _item(db_session, "REVERSAL-CONTRACT-001")
    project = _own_project(db_session)
    _seed_stock(api_client, item)

    reserve = api_client.post(
        f"/api/projects/{project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "1.234"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert reserve.status_code == 201, reserve.text
    original_id = reserve.json()["id"]
    original_quantity = reserve.json()["quantity"]
    original_reference = reserve.json()["reference"]

    reversed_response = api_client.post(
        f"/api/projects/{project.id}/inventory/movements/{original_id}/reverse",
        json={"reason": "Lançamento duplicado"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )

    assert reversed_response.status_code == 201, reversed_response.text
    reversal = reversed_response.json()
    assert reversal["movement_type"] == "reserva"
    assert reversal["quantity"] == "-1.234"
    assert reversal["reversal_of_movement_id"] == original_id
    assert reversal["created_by_person_id"] is not None
    assert reversal["created_at"]
    assert reversal["reference"] == "Anulação: Lançamento duplicado"

    original = db_session.get(InventoryMovement, original_id)
    assert original is not None
    assert str(original.quantity) == original_quantity
    assert original.reference == original_reference
    assert original.reversal_of_movement_id is None


def test_reverse_is_single_compensation_and_second_attempt_conflicts(db_session, api_client):
    item = _item(db_session, "REVERSAL-CONTRACT-002")
    project = _own_project(db_session)
    _seed_stock(api_client, item)
    reserve = api_client.post(
        f"/api/projects/{project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "2.500"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert reserve.status_code == 201, reserve.text
    original_id = reserve.json()["id"]
    path = f"/api/projects/{project.id}/inventory/movements/{original_id}/reverse"

    first = api_client.post(path, json={}, headers=_headers("pm.um.sintetico@example.invalid"))
    second = api_client.post(path, json={}, headers=_headers("pm.um.sintetico@example.invalid"))

    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text
    assert db_session.query(InventoryMovement).filter(getattr(InventoryMovement, "reversal_of_movement_id") == original_id).count() == 1


def test_reverse_rejects_reservation_with_dependent_consumption(db_session, api_client):
    item = _item(db_session, "REVERSAL-CONTRACT-003")
    project = _own_project(db_session)
    _seed_stock(api_client, item)
    reserve = api_client.post(
        f"/api/projects/{project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "2.500"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert reserve.status_code == 201, reserve.text
    consume = api_client.post(
        f"/api/projects/{project.id}/inventory/consume",
        json={"item_id": str(item.id), "quantity": "1.000"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert consume.status_code == 201, consume.text

    response = api_client.post(
        f"/api/projects/{project.id}/inventory/movements/{reserve.json()['id']}/reverse",
        json={},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )

    assert response.status_code == 400, response.text
    assert "saldo" in response.json()["detail"].lower() or "depend" in response.json()["detail"].lower()
    assert db_session.query(InventoryMovement).filter(getattr(InventoryMovement, "reversal_of_movement_id") == reserve.json()["id"]).count() == 0


def test_reverse_rejects_release_that_would_make_available_stock_negative(db_session, api_client):
    item = _item(db_session, "REVERSAL-CONTRACT-004")
    first_project = _own_project(db_session)
    second_project = _other_project(db_session)
    _seed_stock(api_client, item)

    reserve_first = api_client.post(
        f"/api/projects/{first_project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "20.000"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert reserve_first.status_code == 201, reserve_first.text
    release = api_client.post(
        f"/api/projects/{first_project.id}/inventory/release",
        json={"item_id": str(item.id), "quantity": "20.000"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert release.status_code == 201, release.text
    reserve_second = api_client.post(
        f"/api/projects/{second_project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "20.000"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert reserve_second.status_code == 201, reserve_second.text

    response = api_client.post(
        f"/api/projects/{first_project.id}/inventory/movements/{release.json()['id']}/reverse",
        json={},
        headers=_headers("chefe.sintetico@example.invalid"),
    )

    assert response.status_code == 400, response.text
    assert "negativo" in response.json()["detail"].lower() or "saldo" in response.json()["detail"].lower()


def test_pm_cannot_reverse_movement_outside_project_scope(db_session, api_client):
    item = _item(db_session, "REVERSAL-CONTRACT-005")
    project = _other_project(db_session)
    _seed_stock(api_client, item)
    reserve = api_client.post(
        f"/api/projects/{project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "1.000"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert reserve.status_code == 201, reserve.text

    response = api_client.post(
        f"/api/projects/{project.id}/inventory/movements/{reserve.json()['id']}/reverse",
        json={},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )

    assert response.status_code in (403, 404)


def test_reverse_endpoint_rejects_more_than_column_precision(db_session, api_client):
    item = _item(db_session, "REVERSAL-CONTRACT-006")
    project = _own_project(db_session)
    _seed_stock(api_client, item)
    response = api_client.post(
        f"/api/projects/{project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "1.2345"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert response.status_code == 422, response.text


def test_concurrent_reversals_have_one_compensation_on_sqlite(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'reversal-race.db'}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
        future=True,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, autoflush=False)
    setup = Session()
    item = InventoryItem(sku="REVERSAL-RACE", name="Artigo de corrida", unit="un")
    project = Project(name="Projeto de corrida", is_active=True)
    central = InventoryLocation(code="CENTRAL-RACE", name="Central de corrida", location_type="central", is_active=True)
    setup.add_all([item, project, central])
    setup.flush()
    entry = InventoryMovement(item_id=item.id, movement_type=MOVEMENT_ENTRADA, quantity="10.000", location_id=central.id)
    original = InventoryMovement(item_id=item.id, movement_type=MOVEMENT_RESERVA, quantity="2.500", project_id=project.id)
    setup.add_all([entry, original])
    setup.commit()
    original_id = original.id
    setup.close()

    barrier = Barrier(2)
    outcomes: list[str] = []

    def attempt() -> None:
        db = Session()
        try:
            movement = db.get(InventoryMovement, original_id)
            assert movement is not None
            barrier.wait(timeout=10)
            reverse_project_movement(db, movement=movement, created_by_person_id=None)
            outcomes.append("created")
        except Exception as exc:  # the losing race must be the domain conflict
            outcomes.append(type(exc).__name__)
        finally:
            db.close()

    threads = [Thread(target=attempt), Thread(target=attempt)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    check = Session()
    try:
        assert sorted(outcomes) == ["MovementAlreadyReversedError", "created"]
        assert check.query(InventoryMovement).filter(getattr(InventoryMovement, "reversal_of_movement_id") == original_id).count() == 1
    finally:
        check.close()
        engine.dispose()


def test_reverse_without_json_uses_default_manual_reason(db_session, api_client):
    item = _item(db_session, "REVERSAL-BODY-DEFAULT")
    project = _own_project(db_session)
    _seed_stock(api_client, item)
    reserve = api_client.post(
        f"/api/projects/{project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "1.000"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert reserve.status_code == 201, reserve.text

    response = api_client.post(
        f"/api/projects/{project.id}/inventory/movements/{reserve.json()['id']}/reverse",
        headers=_headers("pm.um.sintetico@example.invalid"),
    )

    assert response.status_code == 201, response.text
    assert response.json()["reference"] == "Anulação: Anulação manual"


def test_reverse_consumption_keeps_available_balance_when_net_delta_is_zero(db_session, api_client):
    item = _item(db_session, "REVERSAL-BALANCE-CONSUMPTION")
    project = _own_project(db_session)
    _seed_stock(api_client, item, quantity="2.500")
    reserve = api_client.post(
        f"/api/projects/{project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "2.500"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert reserve.status_code == 201, reserve.text
    consume = api_client.post(
        f"/api/projects/{project.id}/inventory/consume",
        json={"item_id": str(item.id), "quantity": "2.500"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert consume.status_code == 201, consume.text
    before = _balance_snapshot(db_session, item, project)
    assert before == {
        "movement_count": 3,
        "physical": Decimal("0.000"),
        "available": Decimal("0.000"),
        "total_reserved": Decimal("0.000"),
        "reserved": Decimal("0.000"),
        "consumed": Decimal("2.500"),
        "on_site": Decimal("0.000"),
    }

    response = api_client.post(
        f"/api/projects/{project.id}/inventory/movements/{consume.json()['id']}/reverse",
        json={},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )

    assert response.status_code == 201, response.text
    after = _balance_snapshot(db_session, item, project)
    assert after == {
        "movement_count": 4,
        "physical": Decimal("2.500"),
        "available": Decimal("0.000"),
        "total_reserved": Decimal("2.500"),
        "reserved": Decimal("2.500"),
        "consumed": Decimal("0.000"),
        "on_site": Decimal("0.000"),
    }
    assert response.json()["quantity"] == "-2.500"


@pytest.mark.parametrize("movement_type", [
    MOVEMENT_RESERVA,
    MOVEMENT_CONSUMO,
    MOVEMENT_DEVOLUCAO,
    MOVEMENT_ENTREGA,
    MOVEMENT_RECOLHA,
])
def test_reverse_balance_matrix_preserves_each_project_movement_invariant(
    db_session, api_client, movement_type: str
):
    item = _item(db_session, f"REVERSAL-MATRIX-{movement_type}")
    project = _own_project(db_session)
    headers = _headers("pm.um.sintetico@example.invalid")

    if movement_type == MOVEMENT_RESERVA:
        _seed_stock(api_client, item, quantity="20.000")
        original = api_client.post(
            f"/api/projects/{project.id}/inventory/reserve",
            json={"item_id": str(item.id), "quantity": "2.500"},
            headers=headers,
        )
        expected_before = {
            "movement_count": 2,
            "physical": Decimal("20.000"),
            "available": Decimal("17.500"),
            "total_reserved": Decimal("2.500"),
            "reserved": Decimal("2.500"),
            "consumed": Decimal("0.000"),
            "on_site": Decimal("0.000"),
        }
        expected_after = {
            "movement_count": 3,
            "physical": Decimal("20.000"),
            "available": Decimal("20.000"),
            "total_reserved": Decimal("0.000"),
            "reserved": Decimal("0.000"),
            "consumed": Decimal("0.000"),
            "on_site": Decimal("0.000"),
        }
    elif movement_type == MOVEMENT_CONSUMO:
        _seed_stock(api_client, item, quantity="2.500")
        reserve = api_client.post(
            f"/api/projects/{project.id}/inventory/reserve",
            json={"item_id": str(item.id), "quantity": "2.500"},
            headers=headers,
        )
        assert reserve.status_code == 201, reserve.text
        original = api_client.post(
            f"/api/projects/{project.id}/inventory/consume",
            json={"item_id": str(item.id), "quantity": "2.500"},
            headers=headers,
        )
        expected_before = {
            "movement_count": 3,
            "physical": Decimal("0.000"),
            "available": Decimal("0.000"),
            "total_reserved": Decimal("0.000"),
            "reserved": Decimal("0.000"),
            "consumed": Decimal("2.500"),
            "on_site": Decimal("0.000"),
        }
        expected_after = {
            "movement_count": 4,
            "physical": Decimal("2.500"),
            "available": Decimal("0.000"),
            "total_reserved": Decimal("2.500"),
            "reserved": Decimal("2.500"),
            "consumed": Decimal("0.000"),
            "on_site": Decimal("0.000"),
        }
    elif movement_type == MOVEMENT_DEVOLUCAO:
        _seed_stock(api_client, item, quantity="5.000")
        reserve = api_client.post(
            f"/api/projects/{project.id}/inventory/reserve",
            json={"item_id": str(item.id), "quantity": "2.500"},
            headers=headers,
        )
        assert reserve.status_code == 201, reserve.text
        consume = api_client.post(
            f"/api/projects/{project.id}/inventory/consume",
            json={"item_id": str(item.id), "quantity": "2.500"},
            headers=headers,
        )
        assert consume.status_code == 201, consume.text
        original = api_client.post(
            f"/api/projects/{project.id}/inventory/return",
            json={"item_id": str(item.id), "quantity": "2.500"},
            headers=headers,
        )
        expected_before = {
            "movement_count": 4,
            "physical": Decimal("5.000"),
            "available": Decimal("5.000"),
            "total_reserved": Decimal("0.000"),
            "reserved": Decimal("0.000"),
            "consumed": Decimal("0.000"),
            "on_site": Decimal("0.000"),
        }
        expected_after = {
            "movement_count": 5,
            "physical": Decimal("2.500"),
            "available": Decimal("2.500"),
            "total_reserved": Decimal("0.000"),
            "reserved": Decimal("0.000"),
            "consumed": Decimal("2.500"),
            "on_site": Decimal("0.000"),
        }
    elif movement_type == MOVEMENT_ENTREGA:
        _seed_stock(api_client, item, quantity="5.000")
        original = api_client.post(
            f"/api/projects/{project.id}/inventory/deliver",
            json={"item_id": str(item.id), "quantity": "2.500"},
            headers=headers,
        )
        expected_before = {
            "movement_count": 2,
            "physical": Decimal("5.000"),
            "available": Decimal("5.000"),
            "total_reserved": Decimal("0.000"),
            "reserved": Decimal("0.000"),
            "consumed": Decimal("0.000"),
            "on_site": Decimal("2.500"),
        }
        expected_after = {
            "movement_count": 3,
            "physical": Decimal("5.000"),
            "available": Decimal("5.000"),
            "total_reserved": Decimal("0.000"),
            "reserved": Decimal("0.000"),
            "consumed": Decimal("0.000"),
            "on_site": Decimal("0.000"),
        }
    else:
        _seed_stock(api_client, item, quantity="5.000")
        deliver = api_client.post(
            f"/api/projects/{project.id}/inventory/deliver",
            json={"item_id": str(item.id), "quantity": "2.500"},
            headers=headers,
        )
        assert deliver.status_code == 201, deliver.text
        original = api_client.post(
            f"/api/projects/{project.id}/inventory/collect",
            json={"item_id": str(item.id), "quantity": "2.500"},
            headers=headers,
        )
        expected_before = {
            "movement_count": 3,
            "physical": Decimal("5.000"),
            "available": Decimal("5.000"),
            "total_reserved": Decimal("0.000"),
            "reserved": Decimal("0.000"),
            "consumed": Decimal("0.000"),
            "on_site": Decimal("0.000"),
        }
        expected_after = {
            "movement_count": 4,
            "physical": Decimal("5.000"),
            "available": Decimal("5.000"),
            "total_reserved": Decimal("0.000"),
            "reserved": Decimal("0.000"),
            "consumed": Decimal("0.000"),
            "on_site": Decimal("2.500"),
        }

    assert original.status_code == 201, original.text
    assert _balance_snapshot(db_session, item, project) == expected_before
    response = api_client.post(
        f"/api/projects/{project.id}/inventory/movements/{original.json()['id']}/reverse",
        json={"reason": "Matriz sintética"},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    assert response.json()["movement_type"] == movement_type
    assert response.json()["quantity"] == "-2.500"
    assert response.json()["reversal_of_movement_id"] == original.json()["id"]
    assert _balance_snapshot(db_session, item, project) == expected_after


def test_reverse_return_rejects_dependent_reservation_that_would_make_available_negative(db_session, api_client):
    item = _item(db_session, "REVERSAL-BALANCE-AVAILABLE-DEPENDENT")
    first_project = _own_project(db_session)
    second_project = _other_project(db_session)
    _seed_stock(api_client, item, quantity="10.000")
    first_headers = _headers("pm.um.sintetico@example.invalid")
    reserve_first = api_client.post(
        f"/api/projects/{first_project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "5.000"},
        headers=first_headers,
    )
    assert reserve_first.status_code == 201, reserve_first.text
    consume_first = api_client.post(
        f"/api/projects/{first_project.id}/inventory/consume",
        json={"item_id": str(item.id), "quantity": "5.000"},
        headers=first_headers,
    )
    assert consume_first.status_code == 201, consume_first.text
    returned = api_client.post(
        f"/api/projects/{first_project.id}/inventory/return",
        json={"item_id": str(item.id), "quantity": "5.000"},
        headers=first_headers,
    )
    assert returned.status_code == 201, returned.text
    reserve_second = api_client.post(
        f"/api/projects/{second_project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "10.000"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert reserve_second.status_code == 201, reserve_second.text
    before = _balance_snapshot(db_session, item, first_project)
    assert before["available"] == Decimal("0.000")
    assert before["physical"] == Decimal("10.000")
    assert before["total_reserved"] == Decimal("10.000")

    response = api_client.post(
        f"/api/projects/{first_project.id}/inventory/movements/{returned.json()['id']}/reverse",
        json={},
        headers=_headers("chefe.sintetico@example.invalid"),
    )

    assert response.status_code == 400, response.text
    assert "disponível" in response.json()["detail"].lower()
    assert _balance_snapshot(db_session, item, first_project) == before


def test_reverse_checks_consumed_balance_after_partial_return(db_session, api_client):
    item = _item(db_session, "REVERSAL-BALANCE-CONSUMED-DEPENDENT")
    project = _own_project(db_session)
    _seed_stock(api_client, item, quantity="5.000")
    headers = _headers("pm.um.sintetico@example.invalid")
    reserve = api_client.post(
        f"/api/projects/{project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "5.000"},
        headers=headers,
    )
    assert reserve.status_code == 201, reserve.text
    consume = api_client.post(
        f"/api/projects/{project.id}/inventory/consume",
        json={"item_id": str(item.id), "quantity": "5.000"},
        headers=headers,
    )
    assert consume.status_code == 201, consume.text
    returned = api_client.post(
        f"/api/projects/{project.id}/inventory/return",
        json={"item_id": str(item.id), "quantity": "3.000"},
        headers=headers,
    )
    assert returned.status_code == 201, returned.text
    before = _balance_snapshot(db_session, item, project)
    assert before["consumed"] == Decimal("2.000")

    response = api_client.post(
        f"/api/projects/{project.id}/inventory/movements/{consume.json()['id']}/reverse",
        json={},
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert "consumido" in response.json()["detail"].lower()
    assert _balance_snapshot(db_session, item, project) == before


def test_reverse_checks_physical_balance_after_dependent_consumption(db_session, api_client):
    item = _item(db_session, "REVERSAL-BALANCE-PHYSICAL-DEPENDENT")
    first_project = _own_project(db_session)
    second_project = _other_project(db_session)
    _seed_stock(api_client, item, quantity="5.000")
    pm_headers = _headers("pm.um.sintetico@example.invalid")
    reserve_first = api_client.post(
        f"/api/projects/{first_project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "5.000"},
        headers=pm_headers,
    )
    assert reserve_first.status_code == 201, reserve_first.text
    consume_first = api_client.post(
        f"/api/projects/{first_project.id}/inventory/consume",
        json={"item_id": str(item.id), "quantity": "5.000"},
        headers=pm_headers,
    )
    assert consume_first.status_code == 201, consume_first.text
    returned = api_client.post(
        f"/api/projects/{first_project.id}/inventory/return",
        json={"item_id": str(item.id), "quantity": "5.000"},
        headers=pm_headers,
    )
    assert returned.status_code == 201, returned.text
    reserve_second = api_client.post(
        f"/api/projects/{second_project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "5.000"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert reserve_second.status_code == 201, reserve_second.text
    consume_second = api_client.post(
        f"/api/projects/{second_project.id}/inventory/consume",
        json={"item_id": str(item.id), "quantity": "5.000"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert consume_second.status_code == 201, consume_second.text
    before = _balance_snapshot(db_session, item, first_project)
    assert before["physical"] == Decimal("0.000")

    response = api_client.post(
        f"/api/projects/{first_project.id}/inventory/movements/{returned.json()['id']}/reverse",
        json={},
        headers=_headers("chefe.sintetico@example.invalid"),
    )

    assert response.status_code == 400, response.text
    assert "físico" in response.json()["detail"].lower()
    assert _balance_snapshot(db_session, item, first_project) == before


def test_reverse_checks_on_site_balance_after_dependent_collection(db_session, api_client):
    item = _item(db_session, "REVERSAL-BALANCE-SITE-DEPENDENT")
    project = _own_project(db_session)
    _seed_stock(api_client, item, quantity="5.000")
    headers = _headers("pm.um.sintetico@example.invalid")
    delivered = api_client.post(
        f"/api/projects/{project.id}/inventory/deliver",
        json={"item_id": str(item.id), "quantity": "2.500"},
        headers=headers,
    )
    assert delivered.status_code == 201, delivered.text
    collected = api_client.post(
        f"/api/projects/{project.id}/inventory/collect",
        json={"item_id": str(item.id), "quantity": "2.500"},
        headers=headers,
    )
    assert collected.status_code == 201, collected.text
    before = _balance_snapshot(db_session, item, project)
    assert before["on_site"] == Decimal("0.000")

    response = api_client.post(
        f"/api/projects/{project.id}/inventory/movements/{delivered.json()['id']}/reverse",
        json={},
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert "local" in response.json()["detail"].lower()
    assert _balance_snapshot(db_session, item, project) == before


@pytest.mark.parametrize(
    "payload",
    [
        {"reason": None},
        {"reason": 123},
        {"reason": "x" * 221},
        [],
    ],
)
def test_reverse_endpoint_rejects_invalid_body_reason_semantics(db_session, api_client, payload):
    item = _item(db_session, f"REVERSAL-BODY-INVALID-{len(str(payload))}")
    project = _own_project(db_session)
    _seed_stock(api_client, item)
    reserve = api_client.post(
        f"/api/projects/{project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "1.000"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert reserve.status_code == 201, reserve.text

    response = api_client.post(
        f"/api/projects/{project.id}/inventory/movements/{reserve.json()['id']}/reverse",
        json=payload,
        headers=_headers("pm.um.sintetico@example.invalid"),
    )

    assert response.status_code == 422, response.text
    assert db_session.query(InventoryMovement).filter(
        InventoryMovement.reversal_of_movement_id == reserve.json()["id"]
    ).count() == 0


def test_reverse_endpoint_preserves_auth_scope_and_not_found_statuses(db_session, api_client):
    item = _item(db_session, "REVERSAL-ENDPOINT-STATUSES")
    own_project = _own_project(db_session)
    other_project = _other_project(db_session)
    _seed_stock(api_client, item)
    own_reserve = api_client.post(
        f"/api/projects/{own_project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "1.000"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert own_reserve.status_code == 201, own_reserve.text
    own_path = f"/api/projects/{own_project.id}/inventory/movements/{own_reserve.json()['id']}/reverse"

    unauthenticated = api_client.post(own_path, json={})
    assert unauthenticated.status_code == 401, unauthenticated.text
    read_only = api_client.post(
        own_path,
        json={},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert read_only.status_code == 403, read_only.text
    missing_movement = api_client.post(
        f"/api/projects/{own_project.id}/inventory/movements/{uuid.uuid4()}/reverse",
        json={},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert missing_movement.status_code == 404, missing_movement.text

    other_reserve = api_client.post(
        f"/api/projects/{other_project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "1.000"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert other_reserve.status_code == 201, other_reserve.text
    outside_scope = api_client.post(
        f"/api/projects/{other_project.id}/inventory/movements/{other_reserve.json()['id']}/reverse",
        json={},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert outside_scope.status_code == 404, outside_scope.text
