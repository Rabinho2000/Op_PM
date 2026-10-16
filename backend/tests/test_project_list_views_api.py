"""Contrato backend da lista de Projetos: preferências e vistas pessoais."""
from __future__ import annotations

import uuid

from sqlalchemy import text

DEFAULT_CONFIG = {
    "columns": ["project", "pm", "lifecycle", "progress", "next_task", "overdue", "warnings"],
    "sort_by": "name",
    "sort_direction": "asc",
    "filters": {
        "search": "",
        "status": "",
        "lifecycle": ["on_hold_cliente", "preparacao", "construcao", "construido"],
        "pm": "",
        "active": "active",
        "startFrom": "",
        "startTo": "",
    },
}

CHEFE = "chefe.sintetico@example.invalid"
PM_UM = "pm.um.sintetico@example.invalid"


def _headers(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def test_project_list_preferences_gets_defaults_without_creating_a_row(db_session, api_client):
    response = api_client.get(
        "/api/me/project-list-preferences",
        headers=_headers(PM_UM),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"config": DEFAULT_CONFIG}

    # GET on an absent preference is read-only: the new table remains empty.
    assert db_session.execute(
        text("SELECT COUNT(*) FROM project_list_preferences")
    ).scalar_one() == 0


def _config(*, pm: str = "", start_from: str = "", start_to: str = "") -> dict:
    import copy

    config = copy.deepcopy(DEFAULT_CONFIG)
    config["filters"]["pm"] = pm
    config["filters"]["startFrom"] = start_from
    config["filters"]["startTo"] = start_to
    return config


def test_project_list_preferences_put_is_an_account_owned_upsert_and_replays(db_session, api_client):
    first_config = _config(start_from="2026-01-02", start_to="2026-03-04")
    first = api_client.put(
        "/api/me/project-list-preferences",
        json={"config": first_config},
        headers=_headers(PM_UM),
    )
    assert first.status_code == 200, first.text
    assert first.json() == {"config": first_config}

    second_config = _config()
    second_config["columns"] = ["project", "lifecycle", "pm"]
    second_config["sort_by"] = "created_at"
    second_config["sort_direction"] = "desc"
    second = api_client.put(
        "/api/me/project-list-preferences",
        json={"config": second_config},
        headers=_headers(PM_UM),
    )
    assert second.status_code == 200, second.text
    assert second.json() == {"config": second_config}

    replay = api_client.get(
        "/api/me/project-list-preferences", headers=_headers(PM_UM)
    )
    assert replay.status_code == 200
    assert replay.json() == {"config": second_config}
    assert db_session.execute(
        text("SELECT COUNT(*) FROM project_list_preferences")
    ).scalar_one() == 1


def test_project_list_preferences_reject_invalid_config_without_mutation(api_client):
    before = _config()
    created = api_client.put(
        "/api/me/project-list-preferences",
        json={"config": before},
        headers=_headers(PM_UM),
    )
    assert created.status_code == 200, created.text

    invalid_configs = [
        {**before, "unexpected": True},
        {**before, "columns": ["project", "project"]},
        {**before, "columns": ["pm", "project"]},
        {**before, "columns": ["project", "unknown"]},
        {**before, "sort_by": "unknown"},
        {**before, "sort_direction": None},
        {**before, "filters": {**before["filters"], "unexpected": True}},
        {**before, "filters": {**before["filters"], "lifecycle": ["construcao", "construcao"]}},
        {**before, "filters": {**before["filters"], "lifecycle": ["inventado"]}},
        {**before, "filters": {**before["filters"], "search": "x" * 201}},
        {**before, "filters": {**before["filters"], "pm": "not-a-uuid"}},
        {**before, "filters": {**before["filters"], "active": "sometimes"}},
        {**before, "filters": {**before["filters"], "startFrom": "2026-02-30"}},
        {**before, "filters": {**before["filters"], "startFrom": "2026-04-01", "startTo": "2026-03-01"}},
        {**before, "filters": {**before["filters"], "startTo": None}},
    ]
    for invalid in invalid_configs:
        response = api_client.put(
            "/api/me/project-list-preferences",
            json={"config": invalid},
            headers=_headers(PM_UM),
        )
        assert response.status_code == 422, (invalid, response.text)

    replay = api_client.get(
        "/api/me/project-list-preferences", headers=_headers(PM_UM)
    )
    assert replay.status_code == 200
    assert replay.json() == {"config": before}


def test_pm_filter_is_scope_checked_on_write_and_redacted_on_read_without_orm_mutation(
    db_session, api_client
):
    from app.models.people import Person
    from app.models.project_list_views import UserProjectListPreference
    from app.models.identity import User

    legacy = db_session.query(Person).filter(
        Person.display_name == "PM Sintético Legado Dois"
    ).one()
    foreign_pm_config = _config(pm=str(legacy.id))
    response = api_client.put(
        "/api/me/project-list-preferences",
        json={"config": foreign_pm_config},
        headers=_headers(PM_UM),
    )
    assert response.status_code == 422, response.text

    user = db_session.query(User).filter(User.email == PM_UM).one()
    row = UserProjectListPreference(user_id=user.id, config=foreign_pm_config)
    db_session.add(row)
    db_session.flush()

    read = api_client.get(
        "/api/me/project-list-preferences", headers=_headers(PM_UM)
    )
    assert read.status_code == 200, read.text
    assert read.json()["config"]["filters"]["pm"] == ""
    assert row.config["filters"]["pm"] == str(legacy.id)


def test_project_list_views_are_personal_trimmed_sorted_and_foreign_ids_are_404(api_client):
    later = api_client.post(
        "/api/me/project-list-views",
        json={"name": "  Vista Z  ", "config": _config()},
        headers=_headers(PM_UM),
    )
    assert later.status_code == 201, later.text
    later_body = later.json()
    assert later_body["name"] == "Vista Z"
    assert later_body["config"] == _config()
    assert later_body["id"]
    assert later_body["created_at"]
    assert later_body["updated_at"]

    earlier = api_client.post(
        "/api/me/project-list-views",
        json={"name": "Vista A", "config": _config()},
        headers=_headers(PM_UM),
    )
    assert earlier.status_code == 201, earlier.text

    listed = api_client.get(
        "/api/me/project-list-views", headers=_headers(PM_UM)
    )
    assert listed.status_code == 200, listed.text
    assert [item["name"] for item in listed.json()] == ["Vista A", "Vista Z"]

    other_list = api_client.get(
        "/api/me/project-list-views", headers=_headers(CHEFE)
    )
    assert other_list.status_code == 200
    assert other_list.json() == []

    foreign_path = f"/api/me/project-list-views/{later_body['id']}"
    assert api_client.patch(
        foreign_path,
        json={"name": "Tentativa"},
        headers=_headers(CHEFE),
    ).status_code == 404
    assert api_client.delete(foreign_path, headers=_headers(CHEFE)).status_code == 404


def test_project_list_views_patch_replaces_config_duplicate_is_409_and_delete_is_soft(
    db_session, api_client
):
    from app.models.project import Project
    from app.models.project_list_views import ProjectListView

    project_count_before = db_session.query(Project).count()
    created = api_client.post(
        "/api/me/project-list-views",
        json={"name": "  Vista Editável  ", "config": _config()},
        headers=_headers(PM_UM),
    )
    assert created.status_code == 201, created.text
    view = created.json()

    duplicate = api_client.post(
        "/api/me/project-list-views",
        json={"name": "Vista Editável", "config": _config()},
        headers=_headers(PM_UM),
    )
    assert duplicate.status_code == 409, duplicate.text

    replacement = _config(start_from="2027-01-01", start_to="2027-12-31")
    replacement["columns"] = ["project", "installer", "start_date"]
    changed = api_client.patch(
        f"/api/me/project-list-views/{view['id']}",
        json={"name": "Vista Atualizada", "config": replacement},
        headers=_headers(PM_UM),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["name"] == "Vista Atualizada"
    assert changed.json()["config"] == replacement

    invalid_null = api_client.patch(
        f"/api/me/project-list-views/{view['id']}",
        json={"config": None},
        headers=_headers(PM_UM),
    )
    assert invalid_null.status_code == 422

    deleted = api_client.delete(
        f"/api/me/project-list-views/{view['id']}", headers=_headers(PM_UM)
    )
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert db_session.query(Project).count() == project_count_before
    assert api_client.get(
        "/api/me/project-list-views", headers=_headers(PM_UM)
    ).json() == []
    assert api_client.delete(
        f"/api/me/project-list-views/{view['id']}", headers=_headers(PM_UM)
    ).status_code == 404

    db_row = db_session.query(ProjectListView).filter(ProjectListView.id == view["id"]).one()
    assert db_row.is_active is False
    reused = api_client.post(
        "/api/me/project-list-views",
        json={"name": "Vista Atualizada", "config": _config()},
        headers=_headers(PM_UM),
    )
    assert reused.status_code == 201, reused.text
    assert db_session.query(ProjectListView).filter(ProjectListView.name == "Vista Atualizada").count() == 2


def test_installer_readonly_scope_cannot_use_new_project_list_settings_surface(db_session, api_client):
    from app.models.identity import Role, User, UserRole
    from app.models.installer import Installer
    from app.models.installer_access import InstallerAccessMembership
    from app.models.people import Person
    from app.models.project_list_views import ProjectListView
    from app.security.catalog import ROLE_INSTALLER_COLLABORATOR

    email = "project-list-external@example.invalid"
    person = Person(display_name="Project List External", email=email, is_active=True)
    db_session.add(person)
    db_session.flush()
    user = User(person_id=person.id, email=email, is_active=True)
    db_session.add(user)
    db_session.flush()
    role = db_session.query(Role).filter(Role.code == ROLE_INSTALLER_COLLABORATOR).one()
    installer = db_session.query(Installer).filter(
        Installer.name == "Instalador Sintético Alfa"
    ).one()
    db_session.add_all([
        UserRole(user_id=user.id, role_id=role.id),
        InstallerAccessMembership(person_id=person.id, installer_id=installer.id, is_active=True),
    ])
    db_session.flush()
    headers = _headers(email)

    assert api_client.get("/api/me/project-list-preferences", headers=headers).status_code == 403
    assert api_client.put(
        "/api/me/project-list-preferences", json={"config": _config()}, headers=headers
    ).status_code == 403
    assert api_client.get("/api/me/project-list-views", headers=headers).status_code == 403
    assert api_client.post(
        "/api/me/project-list-views", json={"name": "Nope", "config": _config()}, headers=headers
    ).status_code == 403
    assert db_session.query(ProjectListView).filter(ProjectListView.user_id == user.id).count() == 0

    broad_role = db_session.query(Role).filter(Role.code == "chefe_operacoes").one()
    db_session.add(UserRole(user_id=user.id, role_id=broad_role.id))
    db_session.flush()
    assert api_client.get(
        "/api/me/project-list-preferences", headers=headers
    ).status_code == 200
    combined = api_client.post(
        "/api/me/project-list-views",
        json={"name": "Vista Combinada", "config": _config()},
        headers=headers,
    )
    assert combined.status_code == 201, combined.text


def test_project_list_views_reject_invalid_names_and_configs_without_creating_rows(db_session, api_client):
    from app.models.project_list_views import ProjectListView

    invalid_bodies = [
        {"name": "   ", "config": _config()},
        {"name": "x" * 121, "config": _config()},
        {"name": None, "config": _config()},
        {"name": "Valid", "config": None},
        {"name": "Valid", "config": {**_config(), "unknown": True}},
        {"name": "Valid", "config": {**_config(), "filters": {**_config()["filters"], "pm": str(uuid.uuid4())}}},
        {"name": "Valid", "config": _config(start_from="not-a-date")},
        {"name": "Valid", "config": {**_config(), "filters": {**_config()["filters"], "lifecycle": ["construcao", "construcao"]}}},
    ]
    for body in invalid_bodies:
        response = api_client.post(
            "/api/me/project-list-views", json=body, headers=_headers(PM_UM)
        )
        assert response.status_code == 422, (body, response.text)

    assert db_session.query(ProjectListView).count() == 0


def test_project_list_view_pm_filter_is_scoped_and_redacted_in_list_without_mutation(db_session, api_client):
    from app.models.identity import User
    from app.models.people import Person
    from app.models.project_list_views import ProjectListView

    legacy = db_session.query(Person).filter(
        Person.display_name == "PM Sintético Legado Dois"
    ).one()
    foreign_config = _config(pm=str(legacy.id))
    invalid = api_client.post(
        "/api/me/project-list-views",
        json={"name": "Vista Fora do Âmbito", "config": foreign_config},
        headers=_headers(PM_UM),
    )
    assert invalid.status_code == 422, invalid.text

    user = db_session.query(User).filter(User.email == PM_UM).one()
    row = ProjectListView(
        user_id=user.id,
        name="Vista Persistida Fora do Âmbito",
        config=foreign_config,
        is_active=True,
    )
    db_session.add(row)
    db_session.flush()
    listed = api_client.get(
        "/api/me/project-list-views", headers=_headers(PM_UM)
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["config"]["filters"]["pm"] == ""
    assert row.config["filters"]["pm"] == str(legacy.id)
