"""Endpoints de projeto: permissões reais aplicadas no servidor, e
histórico gerado em toda a escrita. Usa `api_client` (mecanismo de
desenvolvimento — X-Dev-User-Email, só local/test) para simular cada
perfil, tal como pedido explicitamente para a Fase 1.
"""
from __future__ import annotations

from app.models.project import Project, ProjectHistory


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def test_pm_can_edit_only_own_project(db_session, api_client):
    db = db_session
    own = db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()
    other = db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()
    assert other.pm_person_id is None  # não é do PM Um

    resp_own = api_client.patch(
        f"/api/projects/{own.id}",
        json={"notes": "Nota sintética editada pelo PM dono."},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_own.status_code == 200
    assert resp_own.json()["notes"] == "Nota sintética editada pelo PM dono."

    resp_other = api_client.patch(
        f"/api/projects/{other.id}",
        json={"notes": "Tentativa indevida."},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_other.status_code == 403


def test_chefe_operacoes_can_edit_any_authorized_project(db_session, api_client):
    db = db_session
    other = db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()

    resp = api_client.patch(
        f"/api/projects/{other.id}",
        json={"notes": "Editado pelo Chefe de Operações."},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "Editado pelo Chefe de Operações."


def test_comercial_is_read_only(db_session, api_client):
    db = db_session
    project = db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()

    resp_get = api_client.get(f"/api/projects/{project.id}", headers=_headers("comercial.sintetico@example.invalid"))
    assert resp_get.status_code == 200

    resp_list = api_client.get("/api/projects", headers=_headers("comercial.sintetico@example.invalid"))
    assert resp_list.status_code == 200
    assert len(resp_list.json()) >= 1  # project.view_all

    resp_patch = api_client.patch(
        f"/api/projects/{project.id}",
        json={"notes": "Tentativa indevida do comercial."},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert resp_patch.status_code == 403


def test_pm_list_only_sees_own_projects(api_client):
    resp = api_client.get("/api/projects", headers=_headers("pm.um.sintetico@example.invalid"))
    assert resp.status_code == 200
    names = {p["name"] for p in resp.json()}
    assert "Instalação Sintética de Demonstração" in names
    assert "Instalação Sintética Incompleta" not in names


def test_history_entry_created_for_every_field_changed(db_session, api_client):
    db = db_session
    project = db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()
    history_before = db.query(ProjectHistory).filter(ProjectHistory.project_id == project.id).count()

    resp = api_client.patch(
        f"/api/projects/{project.id}",
        json={"client_contact": "Contacto Sintético Novo", "role": "supervisor"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 200

    history_after = db.query(ProjectHistory).filter(ProjectHistory.project_id == project.id).count()
    assert history_after == history_before + 2  # um por campo alterado

    latest = (
        db.query(ProjectHistory)
        .filter(ProjectHistory.project_id == project.id)
        .order_by(ProjectHistory.changed_at.desc())
        .limit(2)
        .all()
    )
    assert {h.field_name for h in latest} == {"client_contact", "role"}
    assert all(h.source == "ui" for h in latest)
    assert all(h.changed_by_person_id is not None for h in latest)


def test_history_entry_not_created_when_value_unchanged(db_session, api_client):
    db = db_session
    project = db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()
    history_before = db.query(ProjectHistory).filter(ProjectHistory.project_id == project.id).count()

    resp = api_client.patch(
        f"/api/projects/{project.id}",
        json={"notes": project.notes},  # mesmo valor
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 200
    history_after = db.query(ProjectHistory).filter(ProjectHistory.project_id == project.id).count()
    assert history_after == history_before


def test_no_endpoint_allows_editing_history_directly(api_client):
    """Não existe nenhum endpoint de escrita para project_history — só
    leitura. Confirma que os métodos de escrita comuns não têm rota."""
    resp_post = api_client.post(
        "/api/projects/00000000-0000-0000-0000-000000000000/history",
        json={},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp_post.status_code in (404, 405)


def test_unauthenticated_request_is_rejected(api_client):
    resp = api_client.get("/api/projects")
    assert resp.status_code == 401
