"""Contactos de fornecedores e ligação ao mapa (D-079): vários contactos por
fornecedor, substituição da lista, validação, pesquisa e permissões."""
from __future__ import annotations

CHEFE = "chefe.sintetico@example.invalid"
PM_UM = "pm.um.sintetico@example.invalid"


def _h(email: str) -> dict:
    return {"X-Dev-User-Email": email}


CONTACTS = [
    {"name": "Contacto Sintético Um", "department": "Backoffice", "phone": "+351 910 000 001", "email": "um@example.invalid"},
    {"name": "Geral", "phone": "21 931 8046"},
]


def _create(api_client, **extra):
    return api_client.post("/api/suppliers", json={"name": "Fornecedor Sintético", **extra}, headers=_h(CHEFE))


def test_create_with_contacts_and_maps_url_keeps_order(api_client):
    res = _create(api_client, contacts=CONTACTS, maps_url="https://maps.example.invalid/abc")
    assert res.status_code == 201
    body = res.json()
    assert body["maps_url"] == "https://maps.example.invalid/abc"
    assert [c["name"] for c in body["contacts"]] == ["Contacto Sintético Um", "Geral"]
    assert body["contacts"][0]["department"] == "Backoffice"
    assert body["contacts"][1]["email"] is None
    got = api_client.get(f"/api/suppliers/{body['id']}", headers=_h(PM_UM)).json()
    assert len(got["contacts"]) == 2


def test_patch_replaces_contacts_only_when_sent(api_client):
    sid = _create(api_client, contacts=CONTACTS).json()["id"]

    untouched = api_client.patch(f"/api/suppliers/{sid}", json={"notes": "x"}, headers=_h(CHEFE)).json()
    assert len(untouched["contacts"]) == 2

    replaced = api_client.patch(
        f"/api/suppliers/{sid}", json={"contacts": [{"name": "Só Este"}]}, headers=_h(CHEFE)
    ).json()
    assert [c["name"] for c in replaced["contacts"]] == ["Só Este"]

    cleared = api_client.patch(f"/api/suppliers/{sid}", json={"contacts": []}, headers=_h(CHEFE)).json()
    assert cleared["contacts"] == []


def test_contact_and_maps_validation(api_client):
    bad_email = _create(api_client, contacts=[{"name": "A", "email": "sem-arroba"}])
    assert bad_email.status_code == 422
    bad_phone = _create(api_client, contacts=[{"name": "A", "phone": "abc"}])
    assert bad_phone.status_code == 422
    no_name = _create(api_client, contacts=[{"name": "  "}])
    assert no_name.status_code == 422
    bad_map = _create(api_client, maps_url="javascript:alert(1)")
    assert bad_map.status_code == 422


def test_search_finds_a_supplier_by_contact_name(api_client):
    _create(api_client, contacts=[{"name": "Pessoa Procurável", "department": "Comercial"}])
    found = api_client.get("/api/suppliers", params={"q": "procuravel"}, headers=_h(CHEFE)).json()
    assert [s["name"] for s in found] == ["Fornecedor Sintético"]


def test_pm_cannot_change_contacts(api_client):
    sid = _create(api_client, contacts=CONTACTS).json()["id"]
    res = api_client.patch(f"/api/suppliers/{sid}", json={"contacts": []}, headers=_h(PM_UM))
    assert res.status_code == 403
