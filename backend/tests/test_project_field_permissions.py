"""Restrição de campo por permissão em `Project` (D-028): um PM
(`project.edit_own_progress`) nunca pode alterar campos administrativos,
mesmo no seu próprio projeto — só `project.edit_all` (Chefe de Operações,
Administrador) pode. Verificado sempre no servidor, nunca confiando no
frontend.
"""
from __future__ import annotations

import pytest

from app.models.project import Project, ProjectHistory
from app.schemas.projects import ProjectUpdate
from app.security.project_fields import ADMIN_ONLY_PROJECT_FIELDS, PM_EDITABLE_PROJECT_FIELDS


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


# --------------------------------------------------------------------------
# Consistência das listas em si — nenhum campo esquecido/ambíguo.
# --------------------------------------------------------------------------


def test_pm_editable_and_admin_only_fields_are_disjoint():
    assert PM_EDITABLE_PROJECT_FIELDS.isdisjoint(ADMIN_ONLY_PROJECT_FIELDS)


def test_pm_editable_and_admin_only_fields_cover_every_project_update_field():
    all_fields = set(ProjectUpdate.model_fields.keys())
    covered = PM_EDITABLE_PROJECT_FIELDS | ADMIN_ONLY_PROJECT_FIELDS
    missing = all_fields - covered
    assert not missing, f"campos de ProjectUpdate sem classificação PM/admin: {missing}"


def test_required_admin_only_fields_from_the_original_request_are_present():
    """Confirma explicitamente os campos citados no pedido original."""
    for field_name in ("name", "client_email", "client_contact", "pm_person_id", "is_active"):
        assert field_name in ADMIN_ONLY_PROJECT_FIELDS


# --------------------------------------------------------------------------
# Comportamento via API — bloqueio no servidor, nunca parcial/silencioso.
# --------------------------------------------------------------------------


def test_pm_can_edit_an_allowed_field_on_own_project(db_session, api_client):
    db = db_session
    project = db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()

    resp = api_client.patch(
        f"/api/projects/{project.id}",
        json={"notes": "Nota de progresso sintética."},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "Nota de progresso sintética."


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("name", "Nome Alterado Indevidamente"),
        ("client_email", "outro@example.invalid"),
        ("client_contact", "Outro Contacto"),
        ("is_active", False),
    ],
)
def test_pm_cannot_edit_admin_only_field_on_own_project(db_session, api_client, field_name, value):
    db = db_session
    project = db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()
    original_value = getattr(project, field_name)

    resp = api_client.patch(
        f"/api/projects/{project.id}",
        json={field_name: value},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 403
    assert field_name in resp.json()["detail"]

    db.refresh(project)
    assert getattr(project, field_name) == original_value  # nada foi alterado


def test_pm_cannot_reassign_pm_person_id_on_own_project(db_session, api_client):
    db = db_session
    project = db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()
    from app.models.identity import User

    other_user = db.query(User).filter(User.email == "chefe.sintetico@example.invalid").one()

    resp = api_client.patch(
        f"/api/projects/{project.id}",
        json={"pm_person_id": str(other_user.person_id)},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 403


def test_mixed_request_with_one_admin_field_is_rejected_atomically(db_session, api_client):
    """Um pedido com um campo permitido + um campo administrativo é
    recusado por inteiro — nunca aplica só o campo permitido em silêncio."""
    db = db_session
    project = db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()
    history_before = db.query(ProjectHistory).filter(ProjectHistory.project_id == project.id).count()
    original_notes = project.notes

    resp = api_client.patch(
        f"/api/projects/{project.id}",
        json={"notes": "Nota que não devia ficar guardada.", "name": "Nome que não devia mudar."},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 403

    db.refresh(project)
    assert project.notes == original_notes  # o campo permitido também não foi aplicado
    history_after = db.query(ProjectHistory).filter(ProjectHistory.project_id == project.id).count()
    assert history_after == history_before  # nenhuma entrada de histórico gerada


def test_chefe_operacoes_can_edit_admin_only_fields(db_session, api_client):
    db = db_session
    project = db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()

    resp = api_client.patch(
        f"/api/projects/{project.id}",
        json={"client_email": "novo.email.sintetico@example.invalid", "is_active": False},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["client_email"] == "novo.email.sintetico@example.invalid"
    assert body["is_active"] is False


def test_pm_cannot_edit_a_project_that_is_not_their_own_even_for_allowed_fields(db_session, api_client):
    db = db_session
    other_project = db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()

    resp = api_client.patch(
        f"/api/projects/{other_project.id}",
        json={"notes": "Tentativa num projeto que não é do PM."},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 403
