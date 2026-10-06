"""Fluxo do catálogo de inventário — testes verticais escritos antes do código."""
from __future__ import annotations

from app.models.identity import User
from app.models.inventory import InventoryItem
from app.models.supplier import Supplier


def _headers(email: str = "chefe.sintetico@example.invalid") -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def test_chefe_can_create_item_with_catalog_permission_without_admin_users(db_session, api_client):
    chefe = db_session.query(User).filter_by(email="chefe.sintetico@example.invalid").one()
    from app.security.permissions import load_auth_context

    context = load_auth_context(db_session, chefe)
    assert "inventory.manage_catalog" in context.permission_codes
    assert "admin.manage_users" not in context.permission_codes

    response = api_client.post(
        "/api/inventory/items",
        json={
            "sku": "CAT-001",
            "name": "Artigo de catálogo",
            "unit": "un",
            "min_stock": "2.000",
        },
        headers=_headers(),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["sku"] == "CAT-001"
    assert body["name"] == "Artigo de catálogo"
    assert body["is_active"] is True


def test_chefe_can_edit_and_deactivate_item_with_append_only_history(db_session, api_client):
    create = api_client.post(
        "/api/inventory/items",
        json={"sku": "CAT-EDIT", "name": "Nome inicial", "unit": "un"},
        headers=_headers(),
    )
    assert create.status_code == 201, create.text
    item_id = create.json()["id"]

    update = api_client.patch(
        f"/api/inventory/items/{item_id}",
        json={"name": "Nome atualizado", "min_stock": "3.500"},
        headers=_headers(),
    )
    assert update.status_code == 200, update.text
    assert update.json()["name"] == "Nome atualizado"

    deactivate = api_client.post(
        f"/api/inventory/items/{item_id}/deactivate",
        headers=_headers(),
    )
    assert deactivate.status_code == 200, deactivate.text
    assert deactivate.json()["is_active"] is False

    history = api_client.get(
        f"/api/inventory/catalog-history?entity_id={item_id}",
        headers=_headers(),
    )
    assert history.status_code == 200, history.text
    assert [entry["action"] for entry in history.json()] == ["deactivate", "edit", "create"]


def test_catalog_patch_rejects_malformed_field_types(api_client):
    created = api_client.post(
        "/api/inventory/items",
        json={"sku": "CAT-TYPES", "name": "Tipos", "unit": "un"},
        headers=_headers(),
    )
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]
    for field, value in (("sku", 123), ("unit", []), ("name", {})):
        response = api_client.patch(
            f"/api/inventory/items/{item_id}",
            json={field: value},
            headers=_headers(),
        )
        assert response.status_code == 422, response.text


def test_catalog_audit_uses_real_previous_value_after_orm_refresh(db_session, api_client):
    created = api_client.post(
        "/api/inventory/items",
        json={"sku": "CAT-AUDIT", "name": "Valor anterior", "unit": "un"},
        headers=_headers(),
    )
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]
    stale = db_session.get(InventoryItem, item_id)
    assert stale.name == "Valor anterior"
    updated = api_client.patch(
        f"/api/inventory/items/{item_id}",
        json={"name": "Valor novo"},
        headers=_headers(),
    )
    assert updated.status_code == 200, updated.text
    history = api_client.get(
        f"/api/inventory/catalog-history?entity_id={item_id}",
        headers=_headers(),
    )
    edit = next(entry for entry in history.json() if entry["action"] == "edit")
    assert edit["changes"]["name"] == {"old": "Valor anterior", "new": "Valor novo"}


def test_catalog_locations_preserve_one_active_central_and_are_audited(db_session, api_client):
    locations = api_client.get("/api/inventory/locations", headers=_headers())
    assert locations.status_code == 200, locations.text
    central = next(location for location in locations.json() if location["location_type"] == "central")

    second_central = api_client.post(
        "/api/inventory/locations",
        json={"code": "CENTRAL-2", "name": "Segundo central", "location_type": "central"},
        headers=_headers(),
    )
    assert second_central.status_code == 409, second_central.text

    change_central_type = api_client.patch(
        f"/api/inventory/locations/{central['id']}",
        json={"location_type": "vehicle"},
        headers=_headers(),
    )
    assert change_central_type.status_code == 409, change_central_type.text

    vehicle = api_client.post(
        "/api/inventory/locations",
        json={"code": "VEICULO-1", "name": "Viatura sintética", "location_type": "vehicle"},
        headers=_headers(),
    )
    assert vehicle.status_code == 201, vehicle.text
    vehicle_id = vehicle.json()["id"]

    renamed = api_client.patch(
        f"/api/inventory/locations/{central['id']}",
        json={"name": "Armazém central atualizado"},
        headers=_headers(),
    )
    assert renamed.status_code == 200, renamed.text

    deactivate_vehicle = api_client.post(
        f"/api/inventory/locations/{vehicle_id}/deactivate",
        headers=_headers(),
    )
    assert deactivate_vehicle.status_code == 200, deactivate_vehicle.text
    assert deactivate_vehicle.json()["is_active"] is False

    vehicle_patch = api_client.post(
        "/api/inventory/locations",
        json={"code": "VEICULO-PATCH", "name": "Viatura por patch", "location_type": "vehicle"},
        headers=_headers(),
    )
    assert vehicle_patch.status_code == 201, vehicle_patch.text
    patched_deactivate = api_client.patch(
        f"/api/inventory/locations/{vehicle_patch.json()['id']}",
        json={"is_active": False},
        headers=_headers(),
    )
    assert patched_deactivate.status_code == 200, patched_deactivate.text
    patched_history = api_client.get(
        f"/api/inventory/catalog-history?entity_id={vehicle_patch.json()['id']}",
        headers=_headers(),
    )
    assert [entry["action"] for entry in patched_history.json()] == ["deactivate", "create"]

    deactivate_central = api_client.post(
        f"/api/inventory/locations/{central['id']}/deactivate",
        headers=_headers(),
    )
    assert deactivate_central.status_code == 409, deactivate_central.text

    history = api_client.get(
        f"/api/inventory/catalog-history?entity_id={central['id']}",
        headers=_headers(),
    )
    assert history.status_code == 200, history.text
    assert [entry["action"] for entry in history.json()] == ["edit"]


def test_opening_stock_is_append_only_central_actor_reference_and_idempotent(db_session, api_client):
    item = api_client.post(
        "/api/inventory/items",
        json={"sku": "CAT-STOCK", "name": "Artigo com stock inicial", "unit": "un"},
        headers=_headers(),
    )
    assert item.status_code == 201, item.text
    item_id = item.json()["id"]
    central = next(
        location
        for location in api_client.get("/api/inventory/locations", headers=_headers()).json()
        if location["location_type"] == "central" and location["is_active"]
    )

    payload = {
        "item_id": item_id,
        "quantity": "12.500",
        "reference": "Inventário inicial sintético",
        "idempotency_key": "opening-cat-stock-1",
    }
    first = api_client.post("/api/inventory/opening-stock", json=payload, headers=_headers())
    assert first.status_code == 201, first.text
    assert first.json()["movement_type"] == "entrada"
    assert first.json()["location_id"] == central["id"]
    assert first.json()["reference"] == payload["reference"]
    assert first.json()["created_by_person_id"] == str(
        db_session.query(User).filter_by(email="chefe.sintetico@example.invalid").one().person_id
    )

    retry = api_client.post("/api/inventory/opening-stock", json=payload, headers=_headers())
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] == first.json()["id"]
    assert (
        db_session.query(__import__("app.models.inventory", fromlist=["InventoryMovement"]).InventoryMovement)
        .filter_by(item_id=item_id, movement_type="entrada")
        .count()
        == 1
    )


def test_new_movements_reject_inactive_items_and_locations(db_session, api_client):
    item = api_client.post(
        "/api/inventory/items",
        json={"sku": "CAT-INACTIVE", "name": "Artigo a desativar", "unit": "un"},
        headers=_headers(),
    )
    assert item.status_code == 201, item.text
    item_id = item.json()["id"]
    location = api_client.post(
        "/api/inventory/locations",
        json={"code": "VEICULO-INATIVO", "name": "Viatura inativa", "location_type": "vehicle"},
        headers=_headers(),
    )
    assert location.status_code == 201, location.text
    location_id = location.json()["id"]
    assert api_client.post(f"/api/inventory/locations/{location_id}/deactivate", headers=_headers()).status_code == 200

    inactive_location_movement = api_client.post(
        "/api/inventory/movements",
        json={"item_id": item_id, "movement_type": "entrada", "quantity": "1", "location_id": location_id},
        headers=_headers(),
    )
    assert inactive_location_movement.status_code == 409, inactive_location_movement.text

    assert api_client.post(f"/api/inventory/items/{item_id}/deactivate", headers=_headers()).status_code == 200
    inactive_item_movement = api_client.post(
        "/api/inventory/opening-stock",
        json={
            "item_id": item_id,
            "quantity": "1",
            "reference": "Não deve entrar",
            "idempotency_key": "inactive-item-opening",
        },
        headers=_headers(),
    )
    assert inactive_item_movement.status_code == 409, inactive_item_movement.text


def test_catalog_validates_unique_identifiers_quantities_units_and_active_references(db_session, api_client):
    first = api_client.post(
        "/api/inventory/items",
        json={"sku": "CAT-UNIQUE", "name": "Artigo único", "unit": "un"},
        headers=_headers(),
    )
    assert first.status_code == 201, first.text

    duplicate = api_client.post(
        "/api/inventory/items",
        json={"sku": " cat-unique ", "name": "Outro nome", "unit": "un"},
        headers=_headers(),
    )
    assert duplicate.status_code == 409, duplicate.text

    negative_minimum = api_client.post(
        "/api/inventory/items",
        json={"sku": "CAT-NEG", "name": "Mínimo inválido", "unit": "un", "min_stock": "-1"},
        headers=_headers(),
    )
    assert negative_minimum.status_code == 422, negative_minimum.text

    blank_unit = api_client.post(
        "/api/inventory/items",
        json={"sku": "CAT-UNIT", "name": "Unidade inválida", "unit": "   "},
        headers=_headers(),
    )
    assert blank_unit.status_code == 422, blank_unit.text

    inactive_supplier = Supplier(name="Fornecedor inativo sintético", is_active=False)
    db_session.add(inactive_supplier)
    db_session.commit()
    inactive_reference = api_client.post(
        "/api/inventory/items",
        json={
            "sku": "CAT-SUPPLIER",
            "name": "Fornecedor inválido",
            "unit": "un",
            "preferred_supplier_id": str(inactive_supplier.id),
        },
        headers=_headers(),
    )
    assert inactive_reference.status_code == 422, inactive_reference.text

    duplicate_location = api_client.post(
        "/api/inventory/locations",
        json={"code": "VEICULO-DUP", "name": "Viatura 1", "location_type": "vehicle"},
        headers=_headers(),
    )
    assert duplicate_location.status_code == 201, duplicate_location.text
    duplicate_location_again = api_client.post(
        "/api/inventory/locations",
        json={"code": "veiculo-dup", "name": "Viatura 2", "location_type": "vehicle"},
        headers=_headers(),
    )
    assert duplicate_location_again.status_code == 409, duplicate_location_again.text

    project_without_reference = api_client.post(
        "/api/inventory/locations",
        json={"code": "PROJECT-SEM-ID", "name": "Projeto sem referência", "location_type": "project"},
        headers=_headers(),
    )
    assert project_without_reference.status_code == 422, project_without_reference.text
