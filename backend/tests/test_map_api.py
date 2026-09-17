"""Mapa operacional: payload combinado, fornecedores, pontos de recolha,
pendências de obra e conversão em tarefa. Ver app/api/routes_map.py.
"""
from __future__ import annotations

from app.models.map_ops import ProjectIssue
from app.models.project import Project


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _own_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


def test_unauthenticated_request_is_rejected(api_client):
    resp = api_client.get("/api/map/data")
    assert resp.status_code == 401


def test_map_data_includes_projects_suppliers_pickups_and_issues(api_client):
    resp = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid"))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["projects"]) >= 1
    assert len(body["suppliers"]) >= 2  # 2 fornecedores sintéticos do seed
    assert len(body["pickup_points"]) >= 1
    assert len(body["issues"]) >= 1
    assert "config" in body
    assert body["config"]["provider_enabled"] is False  # sem MAP_TILE_URL configurado por omissão


def test_project_without_coordinates_appears_in_separate_list(api_client):
    resp = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid"))
    body = resp.json()
    names_without = {p["name"] for p in body["projects_without_coordinates"]}
    assert "Instalação Sintética Incompleta" in names_without


def test_pm_only_sees_own_projects_on_map(api_client):
    resp = api_client.get("/api/map/data", headers=_headers("pm.um.sintetico@example.invalid"))
    assert resp.status_code == 200
    names = {p["name"] for p in resp.json()["projects"]}
    assert "Instalação Sintética de Demonstração" in names
    assert "Instalação Sintética G — Trabalho Urgente" in names
    # projeto sem PM não pode aparecer para este PM
    unrelated = {p["name"] for p in resp.json()["projects_without_coordinates"]}
    assert "Instalação Sintética Incompleta" not in unrelated


def test_only_supplier_manage_can_create_supplier(api_client):
    resp_pm = api_client.post(
        "/api/suppliers",
        json={"name": "Fornecedor Teste PM"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_pm.status_code == 403

    resp_chefe = api_client.post(
        "/api/suppliers",
        json={"name": "Fornecedor Teste Chefe", "materials": "Cabos"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp_chefe.status_code == 201
    assert resp_chefe.json()["name"] == "Fornecedor Teste Chefe"


def test_pm_can_create_and_manage_issue_on_own_project(db_session, api_client):
    project = _own_project(db_session)
    resp = api_client.post(
        f"/api/projects/{project.id}/issues",
        json={"description": "Material por recolher no local.", "category": "material", "priority": "high"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 201
    issue_id = resp.json()["id"]
    assert resp.json()["status"] == "aberta"

    resp_update = api_client.patch(
        f"/api/projects/{project.id}/issues/{issue_id}",
        json={"status": "resolvida"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_update.status_code == 200
    assert resp_update.json()["status"] == "resolvida"


def test_convert_issue_to_task_creates_linked_task(db_session, api_client):
    project = _own_project(db_session)
    issue = ProjectIssue(
        project_id=project.id, description="Pendência de teste para converter.", created_by_person_id=None
    )
    db_session.add(issue)
    db_session.commit()

    resp = api_client.post(
        f"/api/projects/{project.id}/issues/{issue.id}/convert-to-task",
        json={"title": "Resolver pendência de teste"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 200
    assert resp.json()["project_id"] == str(project.id)

    db_session.refresh(issue)
    assert issue.related_task_id is not None

    resp_again = api_client.post(
        f"/api/projects/{project.id}/issues/{issue.id}/convert-to-task",
        json={"title": "Tentativa duplicada"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_again.status_code == 400
