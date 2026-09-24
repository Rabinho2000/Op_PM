"""Fornecedores (D-070): permissões, validação, tipos de material, pesquisa e
filtros, desativação, e o carregamento inicial idempotente."""
from __future__ import annotations

import json

import pytest

from app.cli.load_suppliers import load_suppliers, main as load_main
from app.models.supplier import Supplier, SupplierMaterialType
from app.services.suppliers import get_or_create_material_types, normalize_key

CHEFE = "chefe.sintetico@example.invalid"
PM_UM = "pm.um.sintetico@example.invalid"
COMERCIAL = "comercial.sintetico@example.invalid"


def _h(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _create(api_client, **overrides):
    body = {"name": "Fornecedor de Teste", **overrides}
    return api_client.post("/api/suppliers", json=body, headers=_h(CHEFE))


# --- normalização -----------------------------------------------------------


def test_type_names_are_normalized_without_case_accents_or_extra_spaces():
    assert normalize_key("  Estruturas  de Fixação ") == "estruturas de fixacao"
    assert normalize_key("INVERSORES") == normalize_key("inversores")


def test_get_or_create_material_types_deduplicates(db_session):
    types = get_or_create_material_types(db_session, ["Inversores", " inversores ", "Baterias", "", "  "])
    assert [t.name for t in types] == ["Inversores", "Baterias"]
    again = get_or_create_material_types(db_session, ["INVERSORES"])
    assert again[0].id == types[0].id
    assert db_session.query(SupplierMaterialType).filter(SupplierMaterialType.name_key == "inversores").count() == 1


# --- permissões ---------------------------------------------------------------


def test_who_can_see_and_who_can_manage(api_client):
    for email in (CHEFE, PM_UM):
        assert api_client.get("/api/suppliers", headers=_h(email)).status_code == 200
    # Comercial/Financeiro já viam a lista pelo mapa: mantém-se (compatibilidade).
    assert api_client.get("/api/suppliers", headers=_h(COMERCIAL)).status_code == 200

    assert _create(api_client).status_code == 201
    pm = api_client.post("/api/suppliers", json={"name": "Outro"}, headers=_h(PM_UM))
    assert pm.status_code == 403
    comercial = api_client.post("/api/suppliers", json={"name": "Outro"}, headers=_h(COMERCIAL))
    assert comercial.status_code == 403


def test_pm_cannot_edit_a_supplier(api_client):
    created = _create(api_client).json()
    resp = api_client.patch(f"/api/suppliers/{created['id']}", json={"phone": "210000000"}, headers=_h(PM_UM))
    assert resp.status_code == 403


# --- criação e validação --------------------------------------------------------


def test_create_supplier_with_several_material_types_and_all_fields(api_client):
    resp = _create(
        api_client,
        name="  Solar   Exemplo,  Lda ",
        phone="+351 253 145 794",
        email="info@exemplo.pt",
        address="Rua de Exemplo 1, 4755-488 Rio Covo",
        website="www.exemplo.pt",
        contact="Ana Exemplo",
        notes="Também: +351 210 000 000",
        material_types=["Painéis fotovoltaicos", "inversores", "Inversores", "Baterias"],
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Solar Exemplo, Lda"  # espaços colapsados
    assert body["phone"] == "+351 253 145 794"
    assert body["website"] == "https://www.exemplo.pt"  # esquema acrescentado
    assert body["material_types"] == ["Baterias", "inversores", "Painéis fotovoltaicos"]  # sem duplicados, por ordem alfabética
    assert body["is_active"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("email", "isto-nao-e-um-email"),
        ("email", "a@b"),
        ("phone", "abc"),
        ("phone", "123"),
        ("phone", "1234567890123456789"),
        ("website", "sem espacos nem ponto"),
        ("lat", 123.0),
        ("lon", -300.0),
        ("lead_time_days", -1),
    ],
)
def test_invalid_values_are_rejected(api_client, field, value):
    assert _create(api_client, **{field: value}).status_code == 422


def test_blank_optional_fields_become_null(api_client):
    body = _create(api_client, phone="  ", email="", address="", website=" ").json()
    assert (body["phone"], body["email"], body["address"], body["website"]) == (None, None, None, None)


def test_empty_name_is_rejected(api_client):
    assert api_client.post("/api/suppliers", json={"name": "   "}, headers=_h(CHEFE)).status_code == 422


def test_duplicate_name_is_rejected_ignoring_case_and_accents(api_client):
    assert _create(api_client, name="Eficácia Solar").status_code == 201
    dup = _create(api_client, name="  EFICACIA   solar ")
    assert dup.status_code == 409


def test_unknown_fields_are_rejected(api_client):
    assert _create(api_client, cor_favorita="azul").status_code == 422


# --- edição e desativação ---------------------------------------------------------


def test_update_replaces_material_types_and_keeps_other_fields(api_client):
    created = _create(api_client, phone="210000000", material_types=["Cabos", "Inversores"]).json()
    resp = api_client.patch(
        f"/api/suppliers/{created['id']}", json={"material_types": ["Baterias"]}, headers=_h(CHEFE)
    )
    assert resp.status_code == 200
    assert resp.json()["material_types"] == ["Baterias"]
    assert resp.json()["phone"] == "210000000"


def test_update_can_clear_optional_field_but_not_required_ones(api_client):
    created = _create(api_client, phone="210000000").json()
    ok = api_client.patch(f"/api/suppliers/{created['id']}", json={"phone": None}, headers=_h(CHEFE))
    assert ok.status_code == 200 and ok.json()["phone"] is None
    for field in ("name", "is_active", "notes"):
        bad = api_client.patch(f"/api/suppliers/{created['id']}", json={field: None}, headers=_h(CHEFE))
        assert bad.status_code == 422, field


def test_rename_to_an_existing_name_is_rejected(api_client):
    _create(api_client, name="Alfa")
    beta = _create(api_client, name="Beta").json()
    resp = api_client.patch(f"/api/suppliers/{beta['id']}", json={"name": "alfa"}, headers=_h(CHEFE))
    assert resp.status_code == 409
    same = api_client.patch(f"/api/suppliers/{beta['id']}", json={"name": "Beta"}, headers=_h(CHEFE))
    assert same.status_code == 200  # o próprio nome não conta como duplicado


def test_deactivate_keeps_the_supplier_and_hides_it_from_active_filter(api_client):
    created = _create(api_client, name="Para desativar").json()
    resp = api_client.patch(f"/api/suppliers/{created['id']}", json={"is_active": False}, headers=_h(CHEFE))
    assert resp.status_code == 200 and resp.json()["is_active"] is False

    active = {s["name"] for s in api_client.get("/api/suppliers?is_active=true", headers=_h(CHEFE)).json()}
    inactive = {s["name"] for s in api_client.get("/api/suppliers?is_active=false", headers=_h(CHEFE)).json()}
    assert "Para desativar" not in active and "Para desativar" in inactive
    assert api_client.get(f"/api/suppliers/{created['id']}", headers=_h(CHEFE)).status_code == 200


def test_unknown_supplier_is_404(api_client):
    missing = "00000000-0000-0000-0000-000000000000"
    assert api_client.get(f"/api/suppliers/{missing}", headers=_h(CHEFE)).status_code == 404
    assert api_client.patch(f"/api/suppliers/{missing}", json={"phone": None}, headers=_h(CHEFE)).status_code == 404


# --- pesquisa e filtros --------------------------------------------------------------


def _names(api_client, query: str) -> set[str]:
    resp = api_client.get(f"/api/suppliers?{query}", headers=_h(CHEFE))
    assert resp.status_code == 200
    return {s["name"] for s in resp.json()}


def test_search_and_filters(api_client):
    _create(api_client, name="Alfa Estruturas", address="Porto", material_types=["Estruturas de fixação"])
    _create(api_client, name="Beta Elétrica", email="vendas@beta.pt", materials="quadros e disjuntores", material_types=["Material elétrico"])
    _create(api_client, name="Gama Mista", address="Aveiro", material_types=["Estruturas de fixação", "Material elétrico"])

    assert {"Alfa Estruturas", "Gama Mista"} <= _names(api_client, "material_type=estruturas%20de%20fixacao")
    assert "Beta Elétrica" not in _names(api_client, "material_type=Estruturas%20de%20Fixa%C3%A7%C3%A3o")
    assert "Beta Elétrica" in _names(api_client, "material_type=material%20el%C3%A9trico")

    assert _names(api_client, "q=aveiro") >= {"Gama Mista"}
    assert "Alfa Estruturas" not in _names(api_client, "q=aveiro")
    assert "Beta Elétrica" in _names(api_client, "q=disjuntores")  # no texto de materiais
    assert "Beta Elétrica" in _names(api_client, "q=beta.pt")  # no email
    assert {"Alfa Estruturas", "Gama Mista"} <= _names(api_client, "q=ESTRUTURAS")  # pelo tipo, sem distinguir maiúsculas
    assert "Beta Elétrica" not in _names(api_client, "q=ESTRUTURAS&material_type=estruturas%20de%20fixacao")


def test_text_search_ignores_case_and_accents(api_client):
    _create(api_client, name="Pré-Fabricados do Oeste", address="Torres Vedras", material_types=["Betão e pré-fabricados"])
    assert "Pré-Fabricados do Oeste" in _names(api_client, "q=BETAO")
    assert "Pré-Fabricados do Oeste" in _names(api_client, "q=pre-fabricados")
    assert "Pré-Fabricados do Oeste" in _names(api_client, "q=torres%20vedras")
    assert "Pré-Fabricados do Oeste" not in _names(api_client, "q=inexistente")


def test_list_is_sorted_by_name_ignoring_case(api_client):
    _create(api_client, name="zeta")
    _create(api_client, name="Alfa")
    names = [s["name"] for s in api_client.get("/api/suppliers", headers=_h(CHEFE)).json()]
    assert names == sorted(names, key=str.lower)


def test_material_types_endpoint_counts_only_active_suppliers(api_client):
    a = _create(api_client, name="Um", material_types=["Tipo Exclusivo"]).json()
    _create(api_client, name="Dois", material_types=["Tipo Exclusivo"])
    api_client.patch(f"/api/suppliers/{a['id']}", json={"is_active": False}, headers=_h(CHEFE))
    types = {t["name"]: t["active_suppliers"] for t in api_client.get("/api/suppliers/material-types", headers=_h(CHEFE)).json()}
    assert types["Tipo Exclusivo"] == 1
    assert api_client.get("/api/suppliers/material-types", headers=_h(PM_UM)).status_code == 200


def test_seed_suppliers_have_phone_and_material_types(api_client):
    seeded = [s for s in api_client.get("/api/suppliers", headers=_h(CHEFE)).json() if "Sintético" in s["name"]]
    assert seeded and all(s["phone"] and s["material_types"] for s in seeded)


def test_map_data_still_lists_suppliers_with_the_new_fields(api_client):
    resp = api_client.get("/api/map/data", headers=_h(CHEFE))
    assert resp.status_code == 200
    supplier = resp.json()["suppliers"][0]
    assert "phone" in supplier and "material_types" in supplier


# --- carregamento inicial ---------------------------------------------------------------


ENTRIES = [
    {"name": "Loja Um", "phone": "252 181 739", "email": "geral@lojaum.pt", "material_types": ["Contadores e medição"], "website": "https://lojaum.pt/"},
    {"name": "Loja Dois", "material_types": ["Inversores", "Baterias"], "notes": "duas moradas"},
    {"name": "Loja Inválida", "email": "não-é-email"},
    {"name": "Loja Sem Contactos", "phone": None, "email": None, "address": None, "material_types": []},
]


def test_loader_creates_validates_and_is_idempotent(db_session):
    summary = load_suppliers(db_session, ENTRIES)
    assert (summary["created"], summary["updated"], summary["unchanged"]) == (3, 0, 0)
    assert len(summary["invalid"]) == 1 and "Loja Inválida" in summary["invalid"][0]

    um = db_session.query(Supplier).filter(Supplier.name == "Loja Um").one()
    assert um.phone == "252 181 739" and [t.name for t in um.material_types] == ["Contadores e medição"]

    again = load_suppliers(db_session, ENTRIES)
    assert (again["created"], again["updated"], again["unchanged"]) == (0, 0, 3)
    assert db_session.query(Supplier).filter(Supplier.name.like("Loja %")).count() == 3


def test_loader_never_overwrites_manual_edits_or_reactivates(db_session):
    load_suppliers(db_session, ENTRIES)
    um = db_session.query(Supplier).filter(Supplier.name == "Loja Um").one()
    um.phone = "210999999"  # alguém editou na app
    um.address = None
    um.is_active = False
    db_session.flush()

    changed = [{**ENTRIES[0], "phone": "252 181 739", "address": "Rua Nova 1, Famalicão", "material_types": ["Contadores e medição", "Modems"]}]
    summary = load_suppliers(db_session, changed)
    assert summary["updated"] == 1
    db_session.refresh(um)
    assert um.phone == "210999999"  # não sobrescreve
    assert um.address == "Rua Nova 1, Famalicão"  # preenche o que estava vazio
    assert {t.name for t in um.material_types} == {"Contadores e medição", "Modems"}
    assert um.is_active is False  # não reativa


def test_loader_matches_names_ignoring_case_and_accents(db_session):
    load_suppliers(db_session, [{"name": "Eficácia Solar"}])
    summary = load_suppliers(db_session, [{"name": "EFICACIA solar", "phone": "210000000"}])
    assert summary["created"] == 0 and summary["updated"] == 1
    assert db_session.query(Supplier).filter(Supplier.name.ilike("%efic%")).count() == 1


def test_loader_cli_refuses_a_file_git_would_track(tmp_path, monkeypatch, capsys):
    """Um ficheiro dentro do repositório e não ignorado é recusado (é informação
    comercial). Fora do repositório passa a validação."""
    from pathlib import Path

    inside = Path(__file__).resolve().parent / "_fornecedores_tmp.json"
    inside.write_text(json.dumps({"suppliers": []}), encoding="utf-8")
    try:
        assert load_main(["--file", str(inside), "--dry-run"]) == 1
        assert "Git" in capsys.readouterr().err
    finally:
        inside.unlink()

    outside = tmp_path / "fornecedores.json"
    outside.write_text(json.dumps({"suppliers": "não é uma lista"}), encoding="utf-8")
    assert load_main(["--file", str(outside), "--dry-run"]) == 1  # passa o Git, falha o formato
    assert "suppliers" in capsys.readouterr().err


def test_list_query_count_does_not_grow_with_the_number_of_suppliers(api_client):
    from sqlalchemy import event

    from app.db import engine

    def count() -> int:
        counter = {"n": 0}

        def _on(*_a, **_k):
            counter["n"] += 1

        event.listen(engine, "before_cursor_execute", _on)
        try:
            assert api_client.get("/api/suppliers?q=a", headers=_h(CHEFE)).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", _on)
        return counter["n"]

    _create(api_client, name="Base", material_types=["Tipo A", "Tipo B"])
    few = count()
    for i in range(15):
        _create(api_client, name=f"Fornecedor extra {i}", material_types=["Tipo A", "Tipo C"])
    assert count() <= few + 1, "queries a crescer com o nº de fornecedores — provável N+1"
