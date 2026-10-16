"""API contract for personal saved views in the works calendar."""
from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy.exc import OperationalError

from app.models.identity import User
from app.models.installer import Installer, InstallerTeam
from app.models.people import Person
from app.models.project import Project
from app.security.permissions import AuthContext

CHEFE = "chefe.sintetico@example.invalid"
PM_UM = "pm.um.sintetico@example.invalid"


def _headers(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def test_saved_views_create_trims_name_and_list_is_deterministically_sorted(api_client):
    created_late = api_client.post(
        "/api/me/works-saved-views",
        json={
            "name": "  Vista Sintética Z  ",
            "zoom": "weeks",
            "lifecycle_status": ["construcao"],
            "show_idle": True,
        },
        headers=_headers(PM_UM),
    )
    assert created_late.status_code == 201, created_late.text
    late_body = created_late.json()
    assert late_body["name"] == "Vista Sintética Z"
    assert late_body["zoom"] == "weeks"
    assert late_body["lifecycle_status"] == ["construcao"]
    assert late_body["pm_person_id"] is None
    assert late_body["installer_id"] is None
    assert late_body["team_id"] is None
    assert late_body["show_idle"] is True
    assert late_body["id"]
    assert late_body["created_at"]
    assert late_body["updated_at"]

    created_first = api_client.post(
        "/api/me/works-saved-views",
        json={"name": "Vista Sintética A"},
        headers=_headers(PM_UM),
    )
    assert created_first.status_code == 201, created_first.text
    assert created_first.json()["zoom"] == "month_days"
    assert created_first.json()["lifecycle_status"] == []
    assert created_first.json()["show_idle"] is False

    listed = api_client.get(
        "/api/me/works-saved-views", headers=_headers(PM_UM)
    )
    assert listed.status_code == 200, listed.text
    assert [item["name"] for item in listed.json()] == [
        "Vista Sintética A",
        "Vista Sintética Z",
    ]
    assert all("from" not in item and "to" not in item for item in listed.json())


def test_saved_views_require_authentication(api_client):
    assert api_client.get("/api/me/works-saved-views").status_code == 401
    assert api_client.post(
        "/api/me/works-saved-views", json={"name": "Vista Sintética"}
    ).status_code == 401


def _seed_filter_ids(db_session):
    pm = db_session.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    installer = db_session.query(Installer).filter(
        Installer.name == "Instalador Sintético Alfa"
    ).one()
    team = db_session.query(InstallerTeam).filter(
        InstallerTeam.installer_id == installer.id,
        InstallerTeam.name == "Equipa 1",
    ).one()
    return pm, installer, team


def _full_filters(db_session):
    pm, installer, team = _seed_filter_ids(db_session)
    return {
        "zoom": "weeks",
        "lifecycle_status": ["construcao", "construcao", "preparacao"],
        "pm_person_id": str(pm.id),
        "installer_id": str(installer.id),
        "team_id": str(team.id),
        "show_idle": True,
    }


def _create_view(api_client, email=PM_UM, **payload):
    body = {"name": payload.pop("name", "Vista Sintética"), **payload}
    response = api_client.post(
        "/api/me/works-saved-views", json=body, headers=_headers(email)
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_saved_views_are_isolated_per_user_and_foreign_ids_are_not_leaked(api_client):
    created = _create_view(api_client, name="Vista Pessoal Sintética")

    other_list = api_client.get(
        "/api/me/works-saved-views", headers=_headers(CHEFE)
    )
    assert other_list.status_code == 200, other_list.text
    assert other_list.json() == []

    foreign_path = f"/api/me/works-saved-views/{created['id']}"
    for method in ("patch", "delete"):
        if method == "patch":
            response = api_client.patch(
                foreign_path,
                json={"name": "Tentativa Sintética"},
                headers=_headers(CHEFE),
            )
        else:
            response = api_client.delete(
                foreign_path, headers=_headers(CHEFE)
            )
        assert response.status_code == 404, (method, response.text)
    applied = api_client.post(f"{foreign_path}/apply", headers=_headers(CHEFE))
    assert applied.status_code == 404, applied.text

    same_name_other_user = _create_view(
        api_client, CHEFE, name="Vista Pessoal Sintética"
    )
    assert same_name_other_user["name"] == created["name"]


def test_saved_view_duplicate_names_return_conflict_after_trim(api_client):
    _create_view(api_client, name="Vista Duplicada Sintética")
    duplicate = api_client.post(
        "/api/me/works-saved-views",
        json={"name": "  Vista Duplicada Sintética  "},
        headers=_headers(PM_UM),
    )
    assert duplicate.status_code == 409, duplicate.text


def test_saved_view_patch_renames_and_updates_filters_without_changing_active_preference(
    db_session, api_client
):
    original_active = api_client.get(
        "/api/me/works-preferences", headers=_headers(PM_UM)
    )
    assert original_active.status_code == 200, original_active.text

    created = _create_view(
        api_client,
        name="Vista Editável Sintética",
        **_full_filters(db_session),
    )
    active_after_create = api_client.get(
        "/api/me/works-preferences", headers=_headers(PM_UM)
    )
    assert active_after_create.status_code == 200
    assert active_after_create.json() == original_active.json()

    changed = api_client.patch(
        f"/api/me/works-saved-views/{created['id']}",
        json={"name": "Vista Renomeada Sintética", "show_idle": False},
        headers=_headers(PM_UM),
    )
    assert changed.status_code == 200, changed.text
    changed_body = changed.json()
    expected_body = {
        **created,
        "name": "Vista Renomeada Sintética",
        "show_idle": False,
    }
    assert {
        key: value for key, value in changed_body.items() if key != "updated_at"
    } == {
        key: value for key, value in expected_body.items() if key != "updated_at"
    }
    assert dt.datetime.fromisoformat(changed_body["updated_at"]) >= dt.datetime.fromisoformat(
        created["updated_at"]
    )

    invalid_pair = api_client.patch(
        f"/api/me/works-saved-views/{created['id']}",
        json={"installer_id": None},
        headers=_headers(PM_UM),
    )
    assert invalid_pair.status_code == 422, invalid_pair.text
    unchanged = api_client.get(
        "/api/me/works-saved-views", headers=_headers(PM_UM)
    )
    assert unchanged.status_code == 200
    unchanged_body = unchanged.json()
    assert unchanged_body == [changed_body]
    assert dt.datetime.fromisoformat(unchanged_body[0]["updated_at"]) >= dt.datetime.fromisoformat(
        changed_body["updated_at"]
    )


def test_saved_view_apply_copies_filters_to_active_preference_and_keeps_view(
    db_session, api_client
):
    created = _create_view(
        api_client,
        name="Vista Aplicável Sintética",
        **_full_filters(db_session),
    )
    applied = api_client.post(
        f"/api/me/works-saved-views/{created['id']}/apply",
        headers=_headers(PM_UM),
    )
    assert applied.status_code == 200, applied.text
    assert applied.json() == {
        "zoom": "weeks",
        "lifecycle_status": ["construcao", "preparacao"],
        "pm_person_id": created["pm_person_id"],
        "installer_id": created["installer_id"],
        "team_id": created["team_id"],
        "show_idle": True,
    }
    listed = api_client.get(
        "/api/me/works-saved-views", headers=_headers(PM_UM)
    )
    assert listed.status_code == 200
    assert listed.json() == [created]


def test_saved_view_delete_is_204_and_then_returns_404(api_client):
    created = _create_view(api_client, name="Vista Apagável Sintética")
    deleted = api_client.delete(
        f"/api/me/works-saved-views/{created['id']}", headers=_headers(PM_UM)
    )
    assert deleted.status_code == 204
    assert deleted.content == b""
    missing = api_client.delete(
        f"/api/me/works-saved-views/{created['id']}", headers=_headers(PM_UM)
    )
    assert missing.status_code == 404


def test_saved_view_invalid_names_filters_and_extra_fields_return_422(
    db_session, api_client
):
    invalid_payloads = [
        {"name": "   "},
        {"name": "x" * 121},
        {"name": "Vista Inválida Sintética", "lifecycle_status": ["inventado"]},
        {"name": "Vista Inválida Sintética", "pm_person_id": str(uuid.uuid4())},
        {"name": "Vista Inválida Sintética", "installer_id": str(uuid.uuid4())},
        {"name": "Vista Inválida Sintética", "team_id": str(uuid.uuid4())},
        {"name": "Vista Inválida Sintética", "unexpected": True},
    ]
    for payload in invalid_payloads:
        response = api_client.post(
            "/api/me/works-saved-views", json=payload, headers=_headers(PM_UM)
        )
        assert response.status_code == 422, (payload, response.text)

    _, installer, team = _seed_filter_ids(db_session)
    matching_pair = api_client.post(
        "/api/me/works-saved-views",
        json={
            "name": "Vista Compatível Sintética",
            "installer_id": str(installer.id),
            "team_id": str(team.id),
        },
        headers=_headers(PM_UM),
    )
    assert matching_pair.status_code == 201, matching_pair.text

    other_installer = db_session.query(Installer).filter(
        Installer.name == "Instalador Sintético Beta"
    ).one()
    incompatible = api_client.post(
        "/api/me/works-saved-views",
        json={
            "name": "Vista Incompatível Sintética",
            "installer_id": str(other_installer.id),
            "team_id": str(team.id),
        },
        headers=_headers(PM_UM),
    )
    assert incompatible.status_code == 422, incompatible.text

    missing_installer = api_client.post(
        "/api/me/works-saved-views",
        json={
            "name": "Vista Sem Instalador Sintética",
            "team_id": str(team.id),
        },
        headers=_headers(PM_UM),
    )
    assert missing_installer.status_code == 422, missing_installer.text


def test_saved_views_use_same_calendar_visibility_permission(db_session, api_client):
    person = Person(
        display_name="Pessoa Sintética Sem Vistas Guardadas",
        email="sem.vistas.sintetico@example.invalid",
        is_active=True,
    )
    db_session.add(person)
    db_session.flush()
    db_session.add(User(person_id=person.id, email=person.email, is_active=True))
    db_session.flush()

    headers = _headers(person.email)
    assert api_client.get("/api/me/works-saved-views", headers=headers).status_code == 403
    assert api_client.post(
        "/api/me/works-saved-views",
        json={"name": "Vista Sem Permissão Sintética"},
        headers=headers,
    ).status_code == 403


def test_saved_view_read_database_failure_is_503_without_rolling_back_callers_session(
    monkeypatch, db_session, api_client
):
    from app.api import routes_works_saved_views

    pending_project = db_session.query(Project).filter(
        Project.name == "Instalação Sintética de Demonstração"
    ).one()
    pending_project.name = "alteração pendente da vista guardada"
    rollback_calls: list[bool] = []
    monkeypatch.setattr(db_session, "rollback", lambda: rollback_calls.append(True))

    def fail_saved_views(*args, **kwargs):
        raise OperationalError(
            "SELECT ... FROM works_calendar_saved_views",
            {},
            RuntimeError("no such table: works_calendar_saved_views"),
        )

    monkeypatch.setattr(routes_works_saved_views, "list_saved_views", fail_saved_views)
    response = api_client.get(
        "/api/me/works-saved-views", headers=_headers(PM_UM)
    )
    assert response.status_code == 503
    assert "works_calendar_saved_views" not in response.text
    assert rollback_calls == []
    assert pending_project in db_session.dirty
    assert pending_project.name == "alteração pendente da vista guardada"


def test_saved_view_patch_duplicate_name_returns_conflict(api_client):
    first = _create_view(api_client, name="Vista Primeira Sintética")
    second = _create_view(api_client, name="Vista Segunda Sintética")
    duplicate = api_client.patch(
        f"/api/me/works-saved-views/{second['id']}",
        json={"name": first["name"]},
        headers=_headers(PM_UM),
    )
    assert duplicate.status_code == 409, duplicate.text

    listed = api_client.get(
        "/api/me/works-saved-views", headers=_headers(PM_UM)
    )
    assert listed.status_code == 200
    assert [view["name"] for view in listed.json()] == [
        "Vista Primeira Sintética",
        "Vista Segunda Sintética",
    ]


def test_saved_view_service_rechecks_calendar_permission(db_session):
    from app.services.works_saved_views import (
        SavedViewPermissionError,
        list_saved_views,
    )

    user = db_session.query(User).filter(User.email == PM_UM).one()
    ctx = AuthContext(
        user=user,
        person_id=user.person_id,
        role_codes=frozenset(),
        permission_codes=frozenset(),
    )
    with pytest.raises(SavedViewPermissionError):
        list_saved_views(db_session, ctx)

