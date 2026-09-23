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


def test_pm_can_manage_central_inventory(db_session, api_client):
    """Decisão de negócio confirmada (docs/PLAN_OPERATIONS_MVP.md secção
    4): Administrador, Chefe de Operações e PM podem todos gerir o
    inventário central (entrada/ajuste) — não é um recurso por projeto."""
    item = _make_item(db_session)
    resp_entry = api_client.post(
        "/api/inventory/movements",
        json={"item_id": str(item.id), "movement_type": "entrada", "quantity": "5"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_entry.status_code == 201

    resp_adjust = api_client.post(
        "/api/inventory/movements",
        json={"item_id": str(item.id), "movement_type": "ajuste", "quantity": "-2"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_adjust.status_code == 201


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


def test_pm_can_do_every_inventory_operation_end_to_end(db_session, api_client):
    """Prova as seis operações pedidas explicitamente para o PM: entrada,
    ajuste, reserva, consumo, libertação, e consulta de movimentos —
    tudo no mesmo item/projeto, na mesma sequência do exemplo de negócio."""
    item = _make_item(db_session, sku="TEST-SKU-PM-FULL")
    project = _own_project(db_session)
    pm_headers = _headers("pm.um.sintetico@example.invalid")

    resp_entry = api_client.post(
        "/api/inventory/movements",
        json={"item_id": str(item.id), "movement_type": "entrada", "quantity": "100"},
        headers=pm_headers,
    )
    assert resp_entry.status_code == 201, resp_entry.text

    resp_adjust = api_client.post(
        "/api/inventory/movements",
        json={"item_id": str(item.id), "movement_type": "ajuste", "quantity": "5"},
        headers=pm_headers,
    )
    assert resp_adjust.status_code == 201, resp_adjust.text

    resp_reserve = api_client.post(
        f"/api/projects/{project.id}/inventory/reserve",
        json={"item_id": str(item.id), "quantity": "20"},
        headers=pm_headers,
    )
    assert resp_reserve.status_code == 201, resp_reserve.text

    resp_consume = api_client.post(
        f"/api/projects/{project.id}/inventory/consume",
        json={"item_id": str(item.id), "quantity": "5"},
        headers=pm_headers,
    )
    assert resp_consume.status_code == 201, resp_consume.text

    resp_release = api_client.post(
        f"/api/projects/{project.id}/inventory/release",
        json={"item_id": str(item.id), "quantity": "10"},
        headers=pm_headers,
    )
    assert resp_release.status_code == 201, resp_release.text

    resp_movements = api_client.get(
        f"/api/inventory/movements?item_id={item.id}", headers=pm_headers
    )
    assert resp_movements.status_code == 200
    types_seen = {m["movement_type"] for m in resp_movements.json()}
    assert types_seen == {"entrada", "ajuste", "reserva", "consumo", "liberta_reserva"}

    summary = api_client.get("/api/inventory/items", headers=pm_headers)
    body = next(i for i in summary.json() if i["id"] == str(item.id))
    # físico: 100 + 5 (ajuste) - 5 (consumo) = 100; reservado: 20 - 5 (consumo) - 10 (liberta) = 5
    assert body["physical_stock"] == "100.000"
    assert body["total_reserved"] == "5.000"
    assert body["available_stock"] == "95.000"


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


def test_pm_cannot_consume_or_release_on_project_they_do_not_manage(db_session, api_client):
    """Mantém a restrição de projeto mesmo com inventory.manage_central
    concedido: consumo/libertação continuam limitados aos projetos que o
    PM gere (docs/PLAN_OPERATIONS_MVP.md secção 4)."""
    item = _make_item(db_session)
    other = _other_project(db_session)
    assert other.pm_person_id is None

    resp_consume = api_client.post(
        f"/api/projects/{other.id}/inventory/consume",
        json={"item_id": str(item.id), "quantity": "1"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_consume.status_code in (403, 404)

    resp_release = api_client.post(
        f"/api/projects/{other.id}/inventory/release",
        json={"item_id": str(item.id), "quantity": "1"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_release.status_code in (403, 404)


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
