"""Contrato da preferência pessoal do Calendário de obras.

A preferência não controla a autorização nem a janela temporal: guarda apenas
zoom/filtros persistentes por conta autenticada.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import OperationalError

from app.models.identity import User
from app.models.installer import Installer, InstallerTeam
from app.models.people import Person
from app.models.project import Project

CHEFE = "chefe.sintetico@example.invalid"
PM_UM = "pm.um.sintetico@example.invalid"


def _headers(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _seed_filter_ids(db):
    pm = db.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    installer = db.query(Installer).filter(Installer.name == "Instalador Sintético Alfa").one()
    team = db.query(InstallerTeam).filter(
        InstallerTeam.installer_id == installer.id,
        InstallerTeam.name == "Equipa 1",
    ).one()
    return pm, installer, team


def _full_patch(db):
    pm, installer, team = _seed_filter_ids(db)
    return {
        "zoom": "weeks",
        "lifecycle_status": ["construcao", "construcao", "preparacao"],
        "pm_person_id": str(pm.id),
        "installer_id": str(installer.id),
        "team_id": str(team.id),
        "show_idle": True,
    }


def test_defaults_are_per_user_and_work_preferences_do_not_change_planning_preferences(
    db_session, api_client
):
    from app.models.works_preferences import UserWorksPreference

    assert db_session.query(UserWorksPreference).count() == 0
    first = api_client.get("/api/me/works-preferences", headers=_headers(PM_UM))
    assert first.status_code == 200, first.text
    assert first.json() == {
        "zoom": "month_days",
        "lifecycle_status": [],
        "pm_person_id": None,
        "installer_id": None,
        "team_id": None,
        "show_idle": False,
    }
    # GET devolve os defaults sem criar uma linha.
    assert db_session.query(UserWorksPreference).count() == 0

    changed = api_client.patch(
        "/api/me/works-preferences",
        json=_full_patch(db_session),
        headers=_headers(PM_UM),
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert body["zoom"] == "weeks"
    assert body["lifecycle_status"] == ["construcao", "preparacao"]
    assert body["show_idle"] is True

    other_user = api_client.get("/api/me/works-preferences", headers=_headers(CHEFE))
    assert other_user.status_code == 200, other_user.text
    assert other_user.json() == {
        "zoom": "month_days",
        "lifecycle_status": [],
        "pm_person_id": None,
        "installer_id": None,
        "team_id": None,
        "show_idle": False,
    }

    # A tabela/endpoint novo não toca na preferência do Planeamento existente.
    planning_before = api_client.get("/api/me/planning-preferences", headers=_headers(PM_UM))
    assert planning_before.status_code == 200
    assert planning_before.json() == {"view": "month", "hide_weekends": False}
    planning_changed = api_client.patch(
        "/api/me/planning-preferences",
        json={"view": "week", "hide_weekends": True},
        headers=_headers(PM_UM),
    )
    assert planning_changed.status_code == 200
    works_after_planning = api_client.get(
        "/api/me/works-preferences", headers=_headers(PM_UM)
    )
    assert works_after_planning.status_code == 200
    assert works_after_planning.json() == body


def test_patch_omission_preserves_and_nullable_ids_can_be_cleared_atomically(db_session, api_client):
    created = api_client.patch(
        "/api/me/works-preferences",
        json=_full_patch(db_session),
        headers=_headers(PM_UM),
    )
    assert created.status_code == 200, created.text
    original = created.json()

    preserved = api_client.patch(
        "/api/me/works-preferences",
        json={"show_idle": False},
        headers=_headers(PM_UM),
    )
    assert preserved.status_code == 200, preserved.text
    assert preserved.json() == {**original, "show_idle": False}

    cleared = api_client.patch(
        "/api/me/works-preferences",
        json={"pm_person_id": None, "installer_id": None, "team_id": None},
        headers=_headers(PM_UM),
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json() == {
        "zoom": "weeks",
        "lifecycle_status": ["construcao", "preparacao"],
        "pm_person_id": None,
        "installer_id": None,
        "team_id": None,
        "show_idle": False,
    }


def test_invalid_zoom_null_non_nullable_and_unknown_fields_are_rejected_without_mutation(
    db_session, api_client
):
    created = api_client.patch(
        "/api/me/works-preferences",
        json=_full_patch(db_session),
        headers=_headers(PM_UM),
    )
    assert created.status_code == 200, created.text
    before = created.json()

    invalid_payloads = [
        {"zoom": "days"},
        {"zoom": None},
        {"lifecycle_status": None},
        {"show_idle": None},
        {"show_idle": "false"},
        {"unexpected": True},
    ]
    for payload in invalid_payloads:
        response = api_client.patch(
            "/api/me/works-preferences", json=payload, headers=_headers(PM_UM)
        )
        assert response.status_code == 422, (payload, response.text)

    readback = api_client.get("/api/me/works-preferences", headers=_headers(PM_UM))
    assert readback.status_code == 200
    assert readback.json() == before


def test_lifecycle_catalog_and_foreign_lookup_validation_are_safe_and_deduplicate(db_session, api_client):
    pm, installer, team = _seed_filter_ids(db_session)
    good = api_client.patch(
        "/api/me/works-preferences",
        json={"lifecycle_status": ["construcao", "construcao", "preparacao"]},
        headers=_headers(PM_UM),
    )
    assert good.status_code == 200, good.text
    assert good.json()["lifecycle_status"] == ["construcao", "preparacao"]

    unknown_status = api_client.patch(
        "/api/me/works-preferences",
        json={"lifecycle_status": ["inventado"]},
        headers=_headers(PM_UM),
    )
    assert unknown_status.status_code == 422

    unknown = str(uuid.uuid4())
    for field in ("pm_person_id", "installer_id", "team_id"):
        response = api_client.patch(
            "/api/me/works-preferences", json={field: unknown}, headers=_headers(PM_UM)
        )
        assert response.status_code == 422

    inactive_person = db_session.query(Person).filter(
        Person.display_name == "PM Sintético Legado Dois"
    ).one()
    inactive_person_response = api_client.patch(
        "/api/me/works-preferences",
        json={"pm_person_id": str(inactive_person.id)},
        headers=_headers(PM_UM),
    )
    assert inactive_person_response.status_code == 422

    inactive_installer = Installer(
        name="Instalador Sintético Inativo Preferências",
        name_key="instalador sintetico inativo preferencias",
        is_active=False,
    )
    db_session.add(inactive_installer)
    db_session.flush()
    inactive_team = InstallerTeam(
        installer_id=inactive_installer.id,
        name="Equipa Inativa Preferências",
        name_key="equipa inativa preferencias",
        is_active=False,
    )
    db_session.add(inactive_team)
    db_session.flush()
    for field, value in (
        ("installer_id", inactive_installer.id),
        ("team_id", inactive_team.id),
    ):
        response = api_client.patch(
            "/api/me/works-preferences",
            json={field: str(value)},
            headers=_headers(PM_UM),
        )
        assert response.status_code == 422

    other_pm = Person(display_name="PM Sintético Fora do Âmbito", is_active=True)
    db_session.add(other_pm)
    db_session.flush()
    out_of_scope = api_client.patch(
        "/api/me/works-preferences",
        json={"pm_person_id": str(other_pm.id)},
        headers=_headers(PM_UM),
    )
    # A resposta não distingue UUID inexistente, inativo ou presente fora do âmbito.
    assert out_of_scope.status_code == 422

    incompatible = api_client.patch(
        "/api/me/works-preferences",
        json={"installer_id": str(installer.id), "team_id": str(inactive_team.id)},
        headers=_headers(PM_UM),
    )
    assert incompatible.status_code == 422
    unchanged = api_client.get("/api/me/works-preferences", headers=_headers(PM_UM))
    assert unchanged.status_code == 200
    assert unchanged.json()["installer_id"] is None
    assert unchanged.json()["team_id"] is None


def test_preferences_require_authentication_and_works_calendar_visibility(db_session, api_client):
    assert api_client.get("/api/me/works-preferences").status_code == 401
    assert api_client.patch("/api/me/works-preferences", json={}).status_code == 401

    person = Person(
        display_name="Pessoa Sintética Sem Calendário",
        email="sem.calendario.sintetico@example.invalid",
        is_active=True,
    )
    db_session.add(person)
    db_session.flush()
    assert person.email is not None
    db_session.add(User(person_id=person.id, email=person.email, is_active=True))
    db_session.flush()
    forbidden = api_client.get(
        "/api/me/works-preferences", headers=_headers(person.email)
    )
    assert forbidden.status_code == 403


def test_read_database_failure_is_503_and_does_not_rollback_callers_session(
    monkeypatch, db_session, api_client
):
    from app.api import routes_works_preferences

    pending_project = db_session.query(Project).filter(
        Project.name == "Instalação Sintética de Demonstração"
    ).one()
    pending_project.name = "alteração pendente do chamador"
    rollback_calls: list[bool] = []
    monkeypatch.setattr(db_session, "rollback", lambda: rollback_calls.append(True))

    def fail_preferences(*args, **kwargs):
        raise OperationalError(
            "SELECT ... FROM works_calendar_preferences",
            {},
            RuntimeError("no such table: works_calendar_preferences"),
        )

    monkeypatch.setattr(routes_works_preferences, "get_works_preferences", fail_preferences)
    response = api_client.get(
        "/api/me/works-preferences", headers=_headers(PM_UM)
    )
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Não foi possível carregar as preferências do calendário de obras."
    }
    assert "works_calendar_preferences" not in response.text
    assert rollback_calls == []
    assert pending_project in db_session.dirty
    assert pending_project.name == "alteração pendente do chamador"


def test_failed_paired_update_does_not_partially_store_ids(db_session, api_client):
    _, installer, team = _seed_filter_ids(db_session)
    created = api_client.patch(
        "/api/me/works-preferences",
        json={"installer_id": str(installer.id), "team_id": str(team.id)},
        headers=_headers(PM_UM),
    )
    assert created.status_code == 200, created.text
    mismatch = api_client.patch(
        "/api/me/works-preferences",
        json={"installer_id": None},
        headers=_headers(PM_UM),
    )
    assert mismatch.status_code == 422
    readback = api_client.get("/api/me/works-preferences", headers=_headers(PM_UM))
    assert readback.status_code == 200
    assert readback.json()["installer_id"] == str(installer.id)
    assert readback.json()["team_id"] == str(team.id)
