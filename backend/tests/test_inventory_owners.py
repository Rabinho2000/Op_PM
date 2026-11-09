"""Separação do stock por proprietário da localização (D-106)."""
from __future__ import annotations

from app.models.inventory import InventoryItem, InventoryLocation, InventoryMovement
from app.models.project import Project
from app.services.inventory import enter_stock
from app.services.inventory_catalog import create_inventory_location


def _headers(email: str = "chefe.sintetico@example.invalid") -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _make_item(db, sku: str = "OWNER-SKU") -> InventoryItem:
    item = InventoryItem(sku=sku, name="Artigo partilhado", unit="un")
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _central(db, owner: str) -> InventoryLocation:
    existing = (
        db.query(InventoryLocation)
        .filter(
            InventoryLocation.location_type == "central",
            InventoryLocation.owner == owner,
            InventoryLocation.is_active.is_(True),
        )
        .one_or_none()
    )
    if existing:
        return existing
    return create_inventory_location(
        db,
        data={
            "code": f"CENTRAL-{owner.upper()}",
            "name": f"Central {owner}",
            "location_type": "central",
            "project_id": None,
            "owner": owner,
        },
        actor_person_id=None,
    )


def _project(db) -> Project:
    return db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


def test_summary_and_movement_list_are_scoped_to_location_owner(db_session, api_client):
    item = _make_item(db_session)
    solcor = _central(db_session, "solcor")
    partner = _central(db_session, "verde_milenar")
    enter_stock(db_session, item=item, quantity=10, created_by_person_id=None, location_id=solcor.id)
    enter_stock(db_session, item=item, quantity=7, created_by_person_id=None, location_id=partner.id)

    solcor_items = api_client.get("/api/inventory/summary?owner=solcor", headers=_headers())
    partner_items = api_client.get("/api/inventory/summary?owner=verde_milenar", headers=_headers())
    assert solcor_items.status_code == partner_items.status_code == 200
    solcor_item = next(row for row in solcor_items.json() if row["id"] == str(item.id))
    partner_item = next(row for row in partner_items.json() if row["id"] == str(item.id))
    assert solcor_item["physical_stock"] == "10.000"
    assert partner_item["physical_stock"] == "7.000"
    assert solcor_item["location_stocks"] == [
        {"location_id": str(solcor.id), "location_name": solcor.name, "physical_stock": "10.000"}
    ]
    assert partner_item["location_stocks"] == [
        {"location_id": str(partner.id), "location_name": partner.name, "physical_stock": "7.000"}
    ]

    solcor_movements = api_client.get("/api/inventory/movements?owner=solcor", headers=_headers())
    partner_movements = api_client.get("/api/inventory/movements?owner=verde_milenar", headers=_headers())
    assert [movement["location_id"] for movement in solcor_movements.json()] == [str(solcor.id)]
    assert [movement["location_id"] for movement in partner_movements.json()] == [str(partner.id)]


def test_cross_owner_transfer_is_rejected_without_writing_a_movement(db_session, api_client):
    item = _make_item(db_session, sku="OWNER-TRANSFER")
    solcor = _central(db_session, "solcor")
    partner = _central(db_session, "verde_milenar")
    before = db_session.query(InventoryMovement).count()

    response = api_client.post(
        "/api/inventory/movements",
        headers=_headers(),
        json={
            "item_id": str(item.id),
            "movement_type": "transito_saida",
            "quantity": "1",
            "location_id": str(solcor.id),
            "destination_location_id": str(partner.id),
        },
    )

    assert response.status_code == 400
    assert "inventários diferentes" in response.json()["detail"]
    assert db_session.query(InventoryMovement).count() == before


def test_project_reservation_and_consumption_use_the_requested_owner(db_session, api_client):
    item = _make_item(db_session, sku="OWNER-PROJECT")
    project = _project(db_session)
    solcor = _central(db_session, "solcor")
    partner = _central(db_session, "verde_milenar")
    enter_stock(db_session, item=item, quantity=10, created_by_person_id=None, location_id=solcor.id)
    enter_stock(db_session, item=item, quantity=4, created_by_person_id=None, location_id=partner.id)
    headers = _headers("pm.um.sintetico@example.invalid")

    reservation = api_client.post(
        f"/api/projects/{project.id}/inventory/reserve",
        headers=headers,
        json={"item_id": str(item.id), "quantity": "2", "owner": "verde_milenar"},
    )
    consumption = api_client.post(
        f"/api/projects/{project.id}/inventory/consume",
        headers=headers,
        json={"item_id": str(item.id), "quantity": "1", "owner": "verde_milenar"},
    )
    assert reservation.status_code == consumption.status_code == 201
    assert reservation.json()["location_id"] == str(partner.id)
    assert consumption.json()["location_id"] == str(partner.id)

    solcor_item = next(
        row for row in api_client.get("/api/inventory/items?owner=solcor", headers=_headers()).json()
        if row["id"] == str(item.id)
    )
    partner_item = next(
        row for row in api_client.get("/api/inventory/items?owner=verde_milenar", headers=_headers()).json()
        if row["id"] == str(item.id)
    )
    assert (solcor_item["physical_stock"], solcor_item["total_reserved"]) == ("10.000", "0.000")
    assert (partner_item["physical_stock"], partner_item["total_reserved"]) == ("3.000", "1.000")

    partner_summary = api_client.get(
        f"/api/projects/{project.id}/inventory?owner=verde_milenar", headers=headers
    )
    assert partner_summary.status_code == 200
    assert {entry["movement_type"] for entry in partner_summary.json()["reservations"]} == {"reserva", "consumo"}
