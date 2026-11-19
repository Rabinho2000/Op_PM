"""`ProjectUpdate` com os mesmos limites de `ProjectCreate` (M5).

Antes, a edição não tinha os limites da criação e aceitava `{"name": null}`,
o que rebentava na BD (NOT NULL) com um 500. Agora é sempre 422.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.project import Project
from app.schemas.projects import ProjectCreate, ProjectUpdate

CHEFE = {"X-Dev-User-Email": "chefe.sintetico@example.invalid"}


def _project(db_session) -> Project:
    return db_session.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


@pytest.mark.parametrize("field", ["name", "notes", "is_active"])
def test_null_in_required_field_is_422_not_500(db_session, api_client, field):
    project = _project(db_session)
    resp = api_client.patch(f"/api/projects/{project.id}", json={field: None}, headers=CHEFE)
    assert resp.status_code == 422, resp.text
    db_session.refresh(project)
    assert project.name and project.notes is not None and project.is_active is not None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lat", 90.5),
        ("lat", -91),
        ("lon", 180.1),
        ("lon", -181),
        ("power_kwp", -0.1),
        ("name", ""),
        ("name", "   "),
        ("name", "x" * 513),
        ("client_name", "x" * 257),
        ("client_email", "x" * 321),
        ("address", "x" * 513),
        ("power_raw", "x" * 65),
        ("role", "x" * 129),
        ("notes", "x" * 20_001),
        ("award_year_raw", "x" * 17),
        ("m2m_card", "x" * 129),
        ("upac_registration", "x" * 129),
        ("upac_connection_date_raw", "x" * 65),
    ],
)
def test_update_rejects_what_create_rejects(db_session, api_client, field, value):
    project = _project(db_session)
    resp = api_client.patch(f"/api/projects/{project.id}", json={field: value}, headers=CHEFE)
    assert resp.status_code == 422, resp.text


def test_update_rejects_non_finite_numbers_with_sanitized_422(db_session, api_client):
    project = _project(db_session)
    resp = api_client.patch(
        f"/api/projects/{project.id}",
        content='{"lat": 1e999}',
        headers={**CHEFE, "Content-Type": "application/json"},
    )
    assert resp.status_code == 422
    assert "999" not in resp.text


def test_update_still_accepts_valid_values_and_explicit_null_on_optional_fields(db_session, api_client):
    project = _project(db_session)
    resp = api_client.patch(
        f"/api/projects/{project.id}",
        json={"lat": 38.7, "lon": -9.1, "power_kwp": 12.5, "name": "  Nome novo  ", "client_contact": None},
        headers=CHEFE,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Nome novo"
    assert body["lat"] == 38.7 and body["client_contact"] is None


def test_create_and_update_share_the_same_limits():
    for field, bad in [("lat", 91), ("lon", -181), ("power_kwp", -1), ("name", "x" * 513)]:
        with pytest.raises(ValidationError):
            ProjectCreate(**{"name": "ok", field: bad})
        with pytest.raises(ValidationError):
            ProjectUpdate(**{field: bad})
    # omitido continua válido (só os campos presentes são alterados)
    assert ProjectUpdate().model_dump(exclude_unset=True) == {}
