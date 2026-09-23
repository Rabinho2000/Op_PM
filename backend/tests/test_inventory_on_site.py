"""Entrega e recolha de material numa instalação — saldo "no local" (D-064).

`no_local = Σ entrega − Σ recolha − Σ from_site_quantity(consumo)`, independente
da reserva e do stock físico central. Ver app/services/inventory.py e
docs/INVENTORY_RULES.md.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.models.inventory import InventoryItem
from app.models.project import Project
from app.services.inventory import (
    InsufficientReservationError,
    InventoryError,
    available_stock,
    collect_from_project,
    consume_from_project,
    deliver_to_project,
    enter_stock,
    on_site_balances_by_project,
    on_site_for_project,
    physical_stock_central,
    reserve_for_project,
    reserved_for_project,
)

D = Decimal


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


@pytest.fixture()
def item(db_session):
    it = InventoryItem(sku=f"SITE-{uuid.uuid4().hex[:8]}", name="Painel de teste", unit="un")
    db_session.add(it)
    db_session.commit()
    db_session.refresh(it)
    return it


@pytest.fixture()
def project(db_session):
    return db_session.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


def _deliver(db, item, project, qty):
    return deliver_to_project(db, item=item, project_id=project.id, quantity=D(qty), created_by_person_id=None)


def _collect(db, item, project, qty):
    return collect_from_project(db, item=item, project_id=project.id, quantity=D(qty), created_by_person_id=None)


# --- Saldo no local ---


def test_delivery_increases_and_collection_decreases_on_site(db_session, item, project):
    _deliver(db_session, item, project, "10")
    assert on_site_for_project(db_session, item.id, project.id) == D("10")
    _collect(db_session, item, project, "4")
    assert on_site_for_project(db_session, item.id, project.id) == D("6")


def test_delivery_may_exceed_the_reservation(db_session, item, project):
    """Excedente da transportadora ou reforço propositado (ex. painéis de
    reserva): o material no local não está limitado pelo que foi reservado."""
    enter_stock(db_session, item=item, quantity=D("50"), created_by_person_id=None)
    reserve_for_project(db_session, item=item, project_id=project.id, quantity=D("10"), created_by_person_id=None)
    _deliver(db_session, item, project, "13")  # 3 a mais do que o reservado
    assert on_site_for_project(db_session, item.id, project.id) == D("13")
    assert reserved_for_project(db_session, item.id, project.id) == D("10")


def test_delivery_and_collection_never_touch_central_stock_or_reservation(db_session, item, project):
    enter_stock(db_session, item=item, quantity=D("50"), created_by_person_id=None)
    reserve_for_project(db_session, item=item, project_id=project.id, quantity=D("10"), created_by_person_id=None)
    physical, available, reserved = (
        physical_stock_central(db_session, item.id),
        available_stock(db_session, item.id),
        reserved_for_project(db_session, item.id, project.id),
    )
    _deliver(db_session, item, project, "8")
    _collect(db_session, item, project, "3")
    assert physical_stock_central(db_session, item.id) == physical
    assert available_stock(db_session, item.id) == available
    assert reserved_for_project(db_session, item.id, project.id) == reserved  # recolha NÃO liberta a reserva


def test_cannot_collect_more_than_is_on_site(db_session, item, project):
    _deliver(db_session, item, project, "5")
    with pytest.raises(InventoryError):
        _collect(db_session, item, project, "6")
    assert on_site_for_project(db_session, item.id, project.id) == D("5")  # nada foi gravado


def test_cannot_collect_from_a_project_with_nothing_on_site(db_session, item, project):
    with pytest.raises(InventoryError):
        _collect(db_session, item, project, "1")


@pytest.mark.parametrize("qty", ["0", "-1"])
def test_quantities_must_be_positive(db_session, item, project, qty):
    with pytest.raises(InventoryError):
        _deliver(db_session, item, project, qty)
    with pytest.raises(InventoryError):
        _collect(db_session, item, project, qty)


def test_balance_is_per_project_and_per_item(db_session, item, project):
    other_item = InventoryItem(sku=f"SITE-{uuid.uuid4().hex[:8]}", name="Conector de teste", unit="un")
    other_project = Project(name="Outra instalação (no local)", is_active=True)
    db_session.add_all([other_item, other_project])
    db_session.commit()

    _deliver(db_session, item, project, "5")
    deliver_to_project(db_session, item=other_item, project_id=project.id, quantity=D("2"), created_by_person_id=None)
    deliver_to_project(db_session, item=item, project_id=other_project.id, quantity=D("9"), created_by_person_id=None)

    assert on_site_for_project(db_session, item.id, project.id) == D("5")
    assert on_site_for_project(db_session, other_item.id, project.id) == D("2")
    assert on_site_for_project(db_session, item.id, other_project.id) == D("9")


def test_two_items_never_cancel_each_other_out(db_session, item, project):
    other_item = InventoryItem(sku=f"SITE-{uuid.uuid4().hex[:8]}", name="Conector de teste", unit="un")
    db_session.add(other_item)
    db_session.commit()
    _deliver(db_session, item, project, "10")
    deliver_to_project(db_session, item=other_item, project_id=project.id, quantity=D("10"), created_by_person_id=None)
    _collect(db_session, item, project, "10")  # esvazia um item, o outro continua no local
    balances = on_site_balances_by_project(db_session, [project.id])[project.id]
    # (o projeto de demonstração já tem material no local vindo do seed — só
    # interessam os dois itens deste teste)
    assert item.id not in balances  # saldo 0 nunca aparece
    assert balances[other_item.id] == D("10")


def test_idempotency_key_never_duplicates_a_delivery(db_session, item, project):
    kwargs = dict(item=item, project_id=project.id, quantity=D("4"), created_by_person_id=None, idempotency_key="k-1")
    first = deliver_to_project(db_session, **kwargs)
    second = deliver_to_project(db_session, **kwargs)
    assert first.id == second.id
    assert on_site_for_project(db_session, item.id, project.id) == D("4")


# --- Consumo abate primeiro ao que está no local ---


def test_consumption_takes_from_site_first(db_session, item, project):
    """Reservou 10, entregou 6, consumiu 4 -> ficam 2 no local (exemplo do pedido)."""
    enter_stock(db_session, item=item, quantity=D("50"), created_by_person_id=None)
    reserve_for_project(db_session, item=item, project_id=project.id, quantity=D("10"), created_by_person_id=None)
    _deliver(db_session, item, project, "6")
    movement = consume_from_project(
        db_session, item=item, project_id=project.id, quantity=D("4"), created_by_person_id=None
    )
    assert movement.from_site_quantity == D("4")
    assert on_site_for_project(db_session, item.id, project.id) == D("2")


def test_consumption_beyond_what_is_on_site_only_takes_what_is_there(db_session, item, project):
    enter_stock(db_session, item=item, quantity=D("50"), created_by_person_id=None)
    reserve_for_project(db_session, item=item, project_id=project.id, quantity=D("10"), created_by_person_id=None)
    _deliver(db_session, item, project, "3")
    movement = consume_from_project(
        db_session, item=item, project_id=project.id, quantity=D("8"), created_by_person_id=None
    )
    assert movement.from_site_quantity == D("3")  # só havia 3 no local
    assert on_site_for_project(db_session, item.id, project.id) == D("0")


def test_consumption_without_anything_on_site_leaves_on_site_untouched(db_session, item, project):
    """Consumo direto do armazém (comportamento anterior a D-064): não mexe no local."""
    enter_stock(db_session, item=item, quantity=D("50"), created_by_person_id=None)
    reserve_for_project(db_session, item=item, project_id=project.id, quantity=D("10"), created_by_person_id=None)
    movement = consume_from_project(
        db_session, item=item, project_id=project.id, quantity=D("5"), created_by_person_id=None
    )
    assert movement.from_site_quantity == D("0")
    assert on_site_for_project(db_session, item.id, project.id) == D("0")
    # ...e uma entrega posterior não é "comida" pelo consumo anterior (independente da ordem).
    _deliver(db_session, item, project, "3")
    assert on_site_for_project(db_session, item.id, project.id) == D("3")


def test_consumption_still_requires_a_reservation(db_session, item, project):
    _deliver(db_session, item, project, "10")  # estar no local NÃO substitui a reserva
    with pytest.raises(InsufficientReservationError):
        consume_from_project(db_session, item=item, project_id=project.id, quantity=D("1"), created_by_person_id=None)


def test_legacy_consumption_rows_without_from_site_quantity_count_as_zero(db_session, item, project):
    """Movimentos anteriores à coluna têm from_site_quantity NULL — tratado como 0."""
    from app.models.inventory import MOVEMENT_CONSUMO, InventoryMovement

    db_session.add(
        InventoryMovement(item_id=item.id, movement_type=MOVEMENT_CONSUMO, quantity=D("5"), project_id=project.id)
    )
    db_session.commit()
    _deliver(db_session, item, project, "4")
    assert on_site_for_project(db_session, item.id, project.id) == D("4")


# --- API e permissões ---


def test_api_deliver_and_collect_roundtrip_for_own_project(db_session, api_client, item, project):
    headers = _headers("pm.um.sintetico@example.invalid")
    resp = api_client.post(
        f"/api/projects/{project.id}/inventory/deliver",
        json={"item_id": str(item.id), "quantity": "6", "reference": "Transportadora"},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["movement_type"] == "entrega"

    resp = api_client.post(
        f"/api/projects/{project.id}/inventory/collect",
        json={"item_id": str(item.id), "quantity": "2"},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["movement_type"] == "recolha"
    assert on_site_for_project(db_session, item.id, project.id) == D("4")


def test_api_collect_more_than_on_site_is_a_400(api_client, item, project):
    resp = api_client.post(
        f"/api/projects/{project.id}/inventory/collect",
        json={"item_id": str(item.id), "quantity": "1"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 400
    assert "no local" in resp.json()["detail"]


def test_pm_cannot_deliver_or_collect_on_a_project_that_is_not_theirs(db_session, api_client, item):
    other = Project(name="Projeto sem PM (entrega)", is_active=True)
    db_session.add(other)
    db_session.commit()
    for action in ("deliver", "collect"):
        resp = api_client.post(
            f"/api/projects/{other.id}/inventory/{action}",
            json={"item_id": str(item.id), "quantity": "1"},
            headers=_headers("pm.um.sintetico@example.invalid"),
        )
        assert resp.status_code in (403, 404)  # 404: nem sequer vê o projeto


@pytest.mark.parametrize("email", ["comercial.sintetico@example.invalid", "financeiro.sintetico@example.invalid"])
@pytest.mark.parametrize("action", ["deliver", "collect"])
def test_roles_without_the_permission_are_refused(api_client, item, project, email, action):
    resp = api_client.post(
        f"/api/projects/{project.id}/inventory/{action}",
        json={"item_id": str(item.id), "quantity": "1"},
        headers=_headers(email),
    )
    assert resp.status_code == 403


# --- Mapa ---


def test_map_material_on_site_follows_deliveries_not_reservations(db_session, api_client, item):
    project = Project(name="Mapa — no local", client_name="Cliente", lat=6.0, lon=6.0, is_active=True)
    db_session.add(project)
    db_session.commit()
    enter_stock(db_session, item=item, quantity=D("50"), created_by_person_id=None)

    def entry():
        body = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid")).json()
        return next(p for p in body["projects"] if p["id"] == str(project.id))

    # Reservado mas ainda não entregue: NÃO é material no local (D-058 tratava-o como tal).
    reserve_for_project(db_session, item=item, project_id=project.id, quantity=D("10"), created_by_person_id=None)
    assert entry()["has_material_on_site"] is False
    assert entry()["attention"] == "green"

    _deliver(db_session, item, project, "10")
    assert entry()["has_material_on_site"] is True
    assert entry()["material_sku_count"] == 1
    assert entry()["attention"] == "yellow"  # há material por recolher/consumir

    _collect(db_session, item, project, "10")
    assert entry()["has_material_on_site"] is False
    assert entry()["attention"] == "green"


def test_completed_project_with_material_still_on_site_is_yellow(db_session, api_client, item):
    """Exemplo do pedido original: estado do projeto concluído, mas ainda há
    material por recolher -> attention amarelo."""
    from app.models.task import STATUS_DONE
    from app.services.tasks import ensure_default_tasks_for_project

    project = Project(name="Mapa — concluído com material", client_name="C", lat=7.0, lon=7.0, is_active=True)
    db_session.add(project)
    db_session.flush()
    for task in ensure_default_tasks_for_project(db_session, project):
        task.status = STATUS_DONE
    db_session.commit()
    _deliver(db_session, item, project, "2")

    body = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid")).json()
    entry = next(p for p in body["projects"] if p["id"] == str(project.id))
    assert entry["status"] == "concluido"
    assert entry["attention"] == "yellow"


def test_project_summary_lists_on_site_material_even_without_a_requirement(db_session, api_client, item, project):
    """Excedente sem "necessidade" associada também aparece — é o que há a recolher."""
    _deliver(db_session, item, project, "3")
    body = api_client.get(
        f"/api/projects/{project.id}/inventory", headers=_headers("chefe.sintetico@example.invalid")
    ).json()
    entry = next(o for o in body["on_site"] if o["item_id"] == str(item.id))
    assert entry["item_name"] == "Painel de teste"
    assert D(entry["quantity"]) == D("3")
    assert not any(r["item_id"] == str(item.id) for r in body["requirements"])
