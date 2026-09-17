"""Endpoints de dados satélite do projeto: instalação, licenciamento,
comunicação/M2M — permissões, criação na primeira edição, e histórico por
campo. Ver app/api/routes_project_data.py.
"""
from __future__ import annotations

from app.models.project import Project
from app.models.project_data import ProjectDataHistory


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _own_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


def _other_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()


def test_unauthenticated_request_is_rejected(api_client):
    project_id = "00000000-0000-0000-0000-000000000000"
    resp = api_client.get(f"/api/projects/{project_id}/installation-data")
    assert resp.status_code == 401


def test_get_installation_data_returns_empty_shell_when_not_created_yet(db_session, api_client):
    other = _other_project(db_session)
    resp = api_client.get(
        f"/api/projects/{other.id}/installation-data", headers=_headers("chefe.sintetico@example.invalid")
    )
    assert resp.status_code == 200
    assert resp.json()["project_id"] == str(other.id)
    assert resp.json()["client_nif"] is None


def test_pm_can_edit_installation_data_of_own_project(db_session, api_client):
    project = _own_project(db_session)
    resp = api_client.patch(
        f"/api/projects/{project.id}/installation-data",
        json={"client_nif": "999888777", "panel_count": 30},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["client_nif"] == "999888777"
    assert body["panel_count"] == 30

    # A segunda edição atualiza o registo já existente, não cria um segundo.
    resp2 = api_client.patch(
        f"/api/projects/{project.id}/installation-data",
        json={"panel_count": 32},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp2.status_code == 200
    assert resp2.json()["client_nif"] == "999888777"
    assert resp2.json()["panel_count"] == 32


def test_pm_cannot_edit_installation_data_of_other_project(db_session, api_client):
    """O projeto "Instalação Sintética Incompleta" não tem PM atribuído —
    um PM sem project.view_own sobre ele nem sequer o vê (404), consistente
    com o comportamento já existente noutros endpoints de projeto."""
    other = _other_project(db_session)
    resp = api_client.patch(
        f"/api/projects/{other.id}/installation-data",
        json={"client_nif": "111222333"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 404


def test_comercial_can_view_but_not_edit(db_session, api_client):
    project = _own_project(db_session)
    resp_view = api_client.get(
        f"/api/projects/{project.id}/licensing-data", headers=_headers("comercial.sintetico@example.invalid")
    )
    assert resp_view.status_code == 200

    resp_edit = api_client.patch(
        f"/api/projects/{project.id}/licensing-data",
        json={"upac_number": "UPAC-000"},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert resp_edit.status_code == 403


def test_comercial_has_no_access_to_communication_data(db_session, api_client):
    """Dados de comunicação/M2M têm permissão dedicada — Comercial/
    Financeiro não a recebem (ver docs/PLAN_OPERATIONS_MVP.md secção 2.1
    e app/security/catalog.py)."""
    project = _own_project(db_session)
    resp = api_client.get(
        f"/api/projects/{project.id}/communication-data", headers=_headers("comercial.sintetico@example.invalid")
    )
    assert resp.status_code == 403


def test_pm_can_view_and_edit_communication_data_of_own_project(db_session, api_client):
    project = _own_project(db_session)
    resp = api_client.patch(
        f"/api/projects/{project.id}/communication-data",
        json={"operator": "Operador Teste", "gsm_m2m_number": "911111111"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 200
    assert resp.json()["operator"] == "Operador Teste"


def test_editing_field_generates_history_entry(db_session, api_client):
    project = _own_project(db_session)
    api_client.patch(
        f"/api/projects/{project.id}/installation-data",
        json={"client_nif": "555444333"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    history = (
        db_session.query(ProjectDataHistory)
        .filter(ProjectDataHistory.project_id == project.id, ProjectDataHistory.field_name == "client_nif")
        .all()
    )
    assert len(history) == 1
    assert history[0].entity_type == "installation"
    assert history[0].new_value == "555444333"

    resp_history = api_client.get(
        f"/api/projects/{project.id}/data-history?entity_type=installation",
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp_history.status_code == 200
    assert any(h["field_name"] == "client_nif" for h in resp_history.json())


def test_repeating_same_value_does_not_duplicate_history(db_session, api_client):
    project = _own_project(db_session)
    api_client.patch(
        f"/api/projects/{project.id}/installation-data",
        json={"client_nif": "123123123"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    api_client.patch(
        f"/api/projects/{project.id}/installation-data",
        json={"client_nif": "123123123"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    history = (
        db_session.query(ProjectDataHistory)
        .filter(ProjectDataHistory.project_id == project.id, ProjectDataHistory.field_name == "client_nif")
        .all()
    )
    assert len(history) == 1
