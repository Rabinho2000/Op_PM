"""Endpoints de inventário: permissões por perfil (central vs. projeto) e
necessidades de material. Ver app/api/routes_inventory.py.
"""
from __future__ import annotations

from app.models.inventory import InventoryItem
from app.models.project import Project


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _own_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


def _other_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()


def _make_item(db, sku="TEST-SKU-API"):
    item = InventoryItem(sku=sku, name="Item de teste", unit="un")
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def test_unauthenticated_request_is_rejected(api_client):
    resp = api_client.get("/api/inventory/summary")
    assert resp.status_code == 401


def test_comercial_has_no_inventory_access(db_session, api_client):
    """Matriz de permissões original (docs/ARCHITECTURE_PROPOSAL.md secção
    6): Comercial/Financeiro não têm acesso a inventário, nem para
    consulta — mantido sem alteração nesta fase."""
    item = _make_item(db_session)
    resp_view = api_client.get("/api/inventory/summary", headers=_headers("comercial.sintetico@example.invalid"))
    assert resp_view.status_code == 403

    resp_write = api_client.post(
        "/api/inventory/movements",
        json={"item_id": str(item.id), "movement_type": "entrada", "quantity": "5"},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert resp_write.status_code == 403


def test_pm_cannot_manage_central_inventory(db_session, api_client):
    """Decisão assumida em docs/PLAN_OPERATIONS_MVP.md secção 11: PM não
    recebe inventory.manage_central."""
    item = _make_item(db_session)
    resp = api_client.post(
        "/api/inventory/movements",
        json={"item_id": str(item.id), "movement_type": "entrada", "quantity": "5"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 403


def test_chefe_can_enter_and_adjust_central_stock(db_session, api_client):
    item = _make_item(db_session)
    resp_entry = api_client.post(
        "/api/inventory/movements",
        json={"item_id": str(item.id), "movement_type": "entrada", "quantity": "50"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp_entry.status_code == 201

    resp_adjust = api_client.post(
        "/api/inventory/movements",
        json={"item_id": str(item.id), "movement_type": "ajuste", "quantity": "-5"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp_adjust.status_code == 201

    summary = api_client.get("/api/inventory/items", headers=_headers("chefe.sintetico@example.invalid"))
    body = next(i for i in summary.json() if i["id"] == str(item.id))
    assert body["physical_stock"] == "45.000"


def test_pm_can_reserve_consume_release_on_own_project(db_session, api_client):
    db = db_session
    item = _make_item(db_session)
    project = _own_project(db)
    api_client.post(
        "/api/inventory/movements",
        json={"item_id": str(item.id), "movement_type": "entrada", "quantity": "20"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )

    resp_reserve = api_client.post(
        f"/api/projects/{project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "10"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_reserve.status_code == 201

    resp_consume = api_client.post(
        f"/api/projects/{project.id}/inventory/consume",
        json={"item_id": str(item.id), "quantity": "4"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_consume.status_code == 201

    resp_release = api_client.post(
        f"/api/projects/{project.id}/inventory/release",
        json={"item_id": str(item.id), "quantity": "6"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_release.status_code == 201


def test_pm_cannot_reserve_on_project_they_do_not_manage(db_session, api_client):
    item = _make_item(db_session)
    other = _other_project(db_session)
    assert other.pm_person_id is None

    resp = api_client.post(
        f"/api/projects/{other.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "1"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code in (403, 404)


def test_reserve_more_than_available_returns_400(db_session, api_client):
    item = _make_item(db_session)
    project = _own_project(db_session)
    resp = api_client.post(
        f"/api/projects/{project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "999"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 400


def test_create_and_view_material_requirement(db_session, api_client):
    item = _make_item(db_session)
    project = _own_project(db_session)

    resp_create = api_client.post(
        f"/api/projects/{project.id}/inventory/requirements",
        json={"item_id": str(item.id), "quantity_required": "15", "notes": "Necessidade de teste"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_create.status_code == 201
    requirement_id = resp_create.json()["id"]
    assert resp_create.json()["missing"] == "15.000"

    resp_summary = api_client.get(
        f"/api/projects/{project.id}/inventory", headers=_headers("pm.um.sintetico@example.invalid")
    )
    assert resp_summary.status_code == 200
    ids = {r["id"] for r in resp_summary.json()["requirements"]}
    assert requirement_id in ids

    resp_update = api_client.patch(
        f"/api/projects/{project.id}/inventory/requirements/{requirement_id}",
        json={"quantity_required": "20"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_update.status_code == 200
    assert resp_update.json()["quantity_required"] == "20.000"


def test_comercial_cannot_create_material_requirement(db_session, api_client):
    item = _make_item(db_session)
    project = _own_project(db_session)
    resp = api_client.post(
        f"/api/projects/{project.id}/inventory/requirements",
        json={"item_id": str(item.id), "quantity_required": "1"},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert resp.status_code == 403
