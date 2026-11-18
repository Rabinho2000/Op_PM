"""Contratos de venda de excedente (CRUD, remoção lógica, histórico, 422 sem
eco, isolamento) e campos SIM da comunicação.
"""

from __future__ import annotations

from app.models.project import Project
from app.models.project_data import ProjectDataHistory, ProjectSurplusContract

CHEFE = "chefe.sintetico@example.invalid"
PM = "pm.um.sintetico@example.invalid"
COMERCIAL = "comercial.sintetico@example.invalid"


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _own_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


def _other_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()


def test_surplus_crud_by_chefe(db_session, api_client):
    project = _own_project(db_session)
    base = f"/api/projects/{project.id}/surplus-contracts"
    created = api_client.post(
        base,
        json={"commercializer": "Comerc. A", "duration_months": 24, "status": "enviado", "notes": "inicial"},
        headers=_headers(CHEFE),
    )
    assert created.status_code == 201, created.text
    contract_id = created.json()["id"]
    assert created.json()["duration_months"] == 24

    listed = api_client.get(base, headers=_headers(CHEFE))
    assert listed.status_code == 200
    assert [c["id"] for c in listed.json()] == [contract_id]

    patched = api_client.patch(
        f"{base}/{contract_id}", json={"status": "assinado", "notes": None}, headers=_headers(CHEFE)
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "assinado"
    assert patched.json()["notes"] == ""

    deleted = api_client.delete(f"{base}/{contract_id}", headers=_headers(CHEFE))
    assert deleted.status_code == 204
    assert api_client.get(base, headers=_headers(CHEFE)).json() == []
    row = db_session.get(ProjectSurplusContract, contract_id)
    assert row is not None and row.deleted_at is not None


def test_surplus_history_is_per_record_and_logged(db_session, api_client):
    project = _own_project(db_session)
    base = f"/api/projects/{project.id}/surplus-contracts"
    contract_id = api_client.post(base, json={"commercializer": "X"}, headers=_headers(CHEFE)).json()["id"]
    api_client.patch(f"{base}/{contract_id}", json={"commercializer": "Y"}, headers=_headers(CHEFE))
    api_client.delete(f"{base}/{contract_id}", headers=_headers(CHEFE))
    rows = (
        db_session.query(ProjectDataHistory)
        .filter(
            ProjectDataHistory.project_id == project.id,
            ProjectDataHistory.entity_type == "surplus",
            ProjectDataHistory.record_id == contract_id,
        )
        .order_by(ProjectDataHistory.id)
        .all()
    )
    fields = [r.field_name for r in rows]
    assert "created" in fields and "commercializer" in fields and "deleted" in fields
    history = api_client.get(
        f"/api/projects/{project.id}/data-history?entity_type=surplus", headers=_headers(CHEFE)
    )
    assert history.status_code == 200
    assert any(h["record_id"] == contract_id for h in history.json())


def test_surplus_comercial_cannot_edit(db_session, api_client):
    project = _own_project(db_session)
    resp = api_client.post(
        f"/api/projects/{project.id}/surplus-contracts",
        json={"commercializer": "X"},
        headers=_headers(COMERCIAL),
    )
    assert resp.status_code == 403


def test_surplus_pm_without_access_gets_404(db_session, api_client):
    other = _other_project(db_session)
    resp = api_client.get(f"/api/projects/{other.id}/surplus-contracts", headers=_headers(PM))
    assert resp.status_code == 404


def test_surplus_422_does_not_echo_body(db_session, api_client):
    project = _own_project(db_session)
    marker = "Nota-Sensivel-Excedente-99"
    resp = api_client.post(
        f"/api/projects/{project.id}/surplus-contracts",
        json={"duration_months": -5, "notes": marker},
        headers=_headers(CHEFE),
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Corpo inválido."}
    assert marker not in resp.text


def test_communication_sim_fields_crud(db_session, api_client):
    project = _own_project(db_session)
    headers = _headers(PM)
    resp = api_client.patch(
        f"/api/projects/{project.id}/communication-data",
        json={"whereversim_login": "login-sim-01"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["whereversim_login"] == "login-sim-01"
    got = api_client.get(f"/api/projects/{project.id}/communication-data", headers=headers).json()
    assert got["whereversim_login"] == "login-sim-01"
    # Verificação no portal é por cartão SIM (lista), não no projeto.
    created = api_client.post(
        f"/api/projects/{project.id}/sim-cards",
        json={"purpose": "comunicacoes", "verified_on_portal": True, "verified_date": "2026-05-05"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["verified_on_portal"] is True
    assert created.json()["verified_date"] == "2026-05-05"

