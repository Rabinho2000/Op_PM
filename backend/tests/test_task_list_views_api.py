"""API contract for personal Task-list preferences and saved views."""
from __future__ import annotations

import copy
import uuid

from sqlalchemy import text

from app.models.identity import Role, User, UserRole
from app.models.installer import Installer
from app.models.installer_access import InstallerAccessMembership
from app.models.people import Person
from app.models.project import Project
from app.models.task import Task
from app.models.task_list_views import TaskListView, UserTaskListPreference
from app.models.workflow import SupportDelegation

DEFAULT_CONFIG = {
    "columns": ["task", "project", "assignee", "priority", "due_date", "status"],
    "sort_by": "default",
    "sort_direction": "asc",
    "view": "lista",
    "filters": {
        "project_id": "",
        "assigned_to_person_id": "",
        "priority": "",
        "status": "",
        "overdue_only": False,
    },
}

CHEFE = "chefe.sintetico@example.invalid"
PM_UM = "pm.um.sintetico@example.invalid"


def _headers(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _config(**changes: object) -> dict[str, object]:
    value = copy.deepcopy(DEFAULT_CONFIG)
    for key, replacement in changes.items():
        if key == "filters":
            value["filters"].update(replacement)  # type: ignore[union-attr]
        else:
            value[key] = replacement
    return value


def test_task_list_preferences_get_defaults_without_creating_a_row(db_session, api_client):
    response = api_client.get("/api/me/task-list-preferences", headers=_headers(PM_UM))

    assert response.status_code == 200, response.text
    assert response.json() == {"config": DEFAULT_CONFIG}
    assert db_session.execute(
        text("SELECT COUNT(*) FROM task_list_preferences")
    ).scalar_one() == 0


def test_task_list_preferences_put_is_account_owned_upsert_and_replays(db_session, api_client):
    first_config = _config(
        columns=["task", "category", "created_at"],
        sort_by="created_at",
        sort_direction="desc",
        view="kanban",
        filters={"priority": "urgent", "overdue_only": True},
    )
    first = api_client.put(
        "/api/me/task-list-preferences",
        json={"config": first_config},
        headers=_headers(PM_UM),
    )
    assert first.status_code == 200, first.text
    assert first.json() == {"config": first_config}

    second_config = _config(filters={"status": "done"})
    second = api_client.put(
        "/api/me/task-list-preferences",
        json={"config": second_config},
        headers=_headers(PM_UM),
    )
    assert second.status_code == 200, second.text
    assert second.json() == {"config": second_config}

    replay = api_client.get("/api/me/task-list-preferences", headers=_headers(PM_UM))
    assert replay.status_code == 200
    assert replay.json() == {"config": second_config}
    assert db_session.execute(
        text("SELECT COUNT(*) FROM task_list_preferences")
    ).scalar_one() == 1


def test_task_list_preferences_keep_visible_project_without_tasks_for_pm_and_chief(
    db_session, api_client
):
    pm_user = db_session.query(User).filter(User.email == PM_UM).one()
    project = Project(
        name="Task Views Visible Project Without Tasks",
        pm_person_id=pm_user.person_id,
        is_active=True,
    )
    db_session.add(project)
    db_session.flush()
    assert db_session.query(Task).filter(Task.project_id == project.id).count() == 0

    config = _config(
        columns=["task", "project", "priority", "status"],
        sort_by="priority",
        sort_direction="desc",
        view="kanban",
        filters={
            "project_id": str(project.id),
            "priority": "urgent",
            "status": "done",
            "overdue_only": True,
        },
    )
    for email in (PM_UM, CHEFE):
        projects = api_client.get(
            "/api/projects", headers=_headers(email), params={"is_active": "true"}
        )
        assert projects.status_code == 200, projects.text
        assert any(item["id"] == str(project.id) for item in projects.json())

        saved = api_client.put(
            "/api/me/task-list-preferences",
            json={"config": config},
            headers=_headers(email),
        )
        assert saved.status_code == 200, saved.text
        assert saved.json() == {"config": config}

        replay = api_client.get("/api/me/task-list-preferences", headers=_headers(email))
        assert replay.status_code == 200, replay.text
        assert replay.json() == {"config": config}


def test_task_list_preferences_keep_active_own_person_without_assigned_tasks(
    db_session, api_client
):
    email = "task-views-empty-own-person@example.invalid"
    person = Person(
        display_name="Task Views Empty Own Person",
        email=email,
        is_active=True,
    )
    db_session.add(person)
    db_session.flush()
    user = User(person_id=person.id, email=email, is_active=True)
    db_session.add(user)
    db_session.flush()
    role = db_session.query(Role).filter(Role.code == "project_manager").one()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    project = Project(
        name="Task Views Empty Own Person Project",
        pm_person_id=person.id,
        is_active=True,
    )
    db_session.add(project)
    db_session.flush()
    assert db_session.query(Task).filter(Task.assigned_to_person_id == person.id).count() == 0

    people = api_client.get("/api/people", headers=_headers(email))
    assert people.status_code == 200, people.text
    assert any(item["id"] == str(person.id) for item in people.json())

    config = _config(
        columns=["task", "assignee", "status"],
        sort_by="created_at",
        sort_direction="asc",
        filters={"assigned_to_person_id": str(person.id)},
    )
    saved = api_client.put(
        "/api/me/task-list-preferences",
        json={"config": config},
        headers=_headers(email),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"config": config}

    replay = api_client.get("/api/me/task-list-preferences", headers=_headers(email))
    assert replay.status_code == 200, replay.text
    assert replay.json() == {"config": config}


def test_task_list_preferences_reject_strict_invalid_config_without_mutation(api_client):
    before = _config()
    created = api_client.put(
        "/api/me/task-list-preferences",
        json={"config": before},
        headers=_headers(PM_UM),
    )
    assert created.status_code == 200, created.text

    invalid_configs = [
        None,
        {**before, "unexpected": True},
        {**before, "columns": None},
        {**before, "columns": ["task", "task"]},
        {**before, "columns": ["project", "task"]},
        {**before, "columns": ["task", "unknown"]},
        {**before, "columns": ["task", None]},
        {**before, "sort_by": "unknown"},
        {**before, "sort_by": None},
        {**before, "sort_direction": None},
        {**before, "sort_direction": "sideways"},
        {**before, "view": None},
        {**before, "view": "grid"},
        {**before, "filters": None},
        {**before, "filters": {**before["filters"], "unexpected": True}},
        {**before, "filters": {**before["filters"], "project_id": None}},
        {**before, "filters": {**before["filters"], "project_id": "not-a-uuid"}},
        {**before, "filters": {**before["filters"], "assigned_to_person_id": 4}},
        {**before, "filters": {**before["filters"], "priority": None}},
        {**before, "filters": {**before["filters"], "priority": "critical"}},
        {**before, "filters": {**before["filters"], "status": None}},
        {**before, "filters": {**before["filters"], "status": "unknown"}},
        {**before, "filters": {**before["filters"], "overdue_only": None}},
        {**before, "filters": {**before["filters"], "overdue_only": 1}},
        {**before, "filters": {**before["filters"], "overdue_only": "true"}},
    ]
    for invalid in invalid_configs:
        response = api_client.put(
            "/api/me/task-list-preferences",
            json={"config": invalid},
            headers=_headers(PM_UM),
        )
        assert response.status_code == 422, (invalid, response.text)

    replay = api_client.get("/api/me/task-list-preferences", headers=_headers(PM_UM))
    assert replay.status_code == 200
    assert replay.json() == {"config": before}


def _delegated_support(db_session) -> tuple[str, User, Project, Person, Project]:
    """Create a synthetic support account scoped to a legacy PM project."""
    legacy_pm = db_session.query(Person).filter(
        Person.display_name == "PM Sintético Legado Dois"
    ).one()
    visible_project = db_session.query(Project).filter(
        Project.name == "Instalação Sintética F — PM Legado"
    ).one()
    hidden_project = db_session.query(Project).filter(
        Project.name == "Instalação Sintética de Demonstração"
    ).one()
    person = Person(
        display_name="Task Views Support Sintético",
        email="task.views.support@example.invalid",
        is_active=True,
    )
    db_session.add(person)
    db_session.flush()
    user = User(person_id=person.id, email=person.email, is_active=True)
    db_session.add(user)
    db_session.flush()
    role = db_session.query(Role).filter(Role.code == "suporte_operacoes").one()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.add(
        SupportDelegation(pm_person_id=legacy_pm.id, support_person_id=person.id)
    )
    # Make the assignee reference reachable through the same task query.
    db_session.add(
        Task(
            project_id=visible_project.id,
            title="Tarefa sintética delegada",
            assigned_to_person_id=legacy_pm.id,
        )
    )
    db_session.flush()
    return person.email, user, visible_project, legacy_pm, hidden_project


def test_task_filter_references_are_scoped_and_get_redacts_without_mutating_orm(
    db_session, api_client
):
    email, user, visible_project, visible_person, hidden_project = _delegated_support(db_session)
    valid = _config(
        filters={
            "project_id": str(visible_project.id),
            "assigned_to_person_id": str(visible_person.id),
        }
    )
    assert api_client.put(
        "/api/me/task-list-preferences", json={"config": valid}, headers=_headers(email)
    ).status_code == 200

    foreign_project = _config(filters={"project_id": str(hidden_project.id)})
    invalid_project = api_client.put(
        "/api/me/task-list-preferences",
        json={"config": foreign_project},
        headers=_headers(email),
    )
    assert invalid_project.status_code == 422

    foreign_assignee = _config(filters={"assigned_to_person_id": str(db_session.query(Person).filter(
        Person.display_name == "PM Sintético Um"
    ).one().id)})
    invalid_assignee = api_client.put(
        "/api/me/task-list-preferences",
        json={"config": foreign_assignee},
        headers=_headers(email),
    )
    assert invalid_assignee.status_code == 422

    persisted = _config(
        filters={
            "project_id": str(hidden_project.id),
            "assigned_to_person_id": str(foreign_assignee["filters"]["assigned_to_person_id"]),
        }
    )
    row = db_session.query(UserTaskListPreference).filter(
        UserTaskListPreference.user_id == user.id
    ).one()
    row.config = persisted
    db_session.flush()

    read = api_client.get("/api/me/task-list-preferences", headers=_headers(email))
    assert read.status_code == 200, read.text
    assert read.json()["config"]["filters"]["project_id"] == ""
    assert read.json()["config"]["filters"]["assigned_to_person_id"] == ""
    assert row.config == persisted


def test_task_list_views_are_personal_trimmed_sorted_and_foreign_ids_are_404(api_client):
    later = api_client.post(
        "/api/me/task-list-views",
        json={"name": "  Vista Z  ", "config": _config()},
        headers=_headers(PM_UM),
    )
    assert later.status_code == 201, later.text
    later_body = later.json()
    assert later_body["name"] == "Vista Z"
    assert later_body["config"] == DEFAULT_CONFIG
    assert later_body["id"]
    assert later_body["created_at"]
    assert later_body["updated_at"]

    earlier = api_client.post(
        "/api/me/task-list-views",
        json={"name": "Vista A", "config": _config()},
        headers=_headers(PM_UM),
    )
    assert earlier.status_code == 201, earlier.text

    listed = api_client.get("/api/me/task-list-views", headers=_headers(PM_UM))
    assert listed.status_code == 200, listed.text
    assert [item["name"] for item in listed.json()] == ["Vista A", "Vista Z"]

    other_list = api_client.get("/api/me/task-list-views", headers=_headers(CHEFE))
    assert other_list.status_code == 200
    assert other_list.json() == []

    foreign_path = f"/api/me/task-list-views/{later_body['id']}"
    assert api_client.patch(
        foreign_path,
        json={"name": "Tentativa"},
        headers=_headers(CHEFE),
    ).status_code == 404
    assert api_client.delete(foreign_path, headers=_headers(CHEFE)).status_code == 404


def test_task_list_views_patch_replaces_config_duplicate_is_409_and_delete_is_soft(
    db_session, api_client
):
    created = api_client.post(
        "/api/me/task-list-views",
        json={"name": "  Vista Editável  ", "config": _config()},
        headers=_headers(PM_UM),
    )
    assert created.status_code == 201, created.text
    view = created.json()

    duplicate = api_client.post(
        "/api/me/task-list-views",
        json={"name": "Vista Editável", "config": _config()},
        headers=_headers(PM_UM),
    )
    assert duplicate.status_code == 409, duplicate.text

    replacement = _config(
        columns=["task", "category", "created_at"],
        sort_by="project_name",
        sort_direction="desc",
        view="kanban",
        filters={"status": "blocked"},
    )
    changed = api_client.patch(
        f"/api/me/task-list-views/{view['id']}",
        json={"name": "Vista Atualizada", "config": replacement},
        headers=_headers(PM_UM),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["name"] == "Vista Atualizada"
    assert changed.json()["config"] == replacement

    invalid_null_config = api_client.patch(
        f"/api/me/task-list-views/{view['id']}",
        json={"config": None},
        headers=_headers(PM_UM),
    )
    assert invalid_null_config.status_code == 422
    invalid_null_name = api_client.patch(
        f"/api/me/task-list-views/{view['id']}",
        json={"name": None},
        headers=_headers(PM_UM),
    )
    assert invalid_null_name.status_code == 422
    invalid_empty = api_client.patch(
        f"/api/me/task-list-views/{view['id']}",
        json={},
        headers=_headers(PM_UM),
    )
    assert invalid_empty.status_code == 422

    deleted = api_client.delete(
        f"/api/me/task-list-views/{view['id']}", headers=_headers(PM_UM)
    )
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert api_client.get(
        "/api/me/task-list-views", headers=_headers(PM_UM)
    ).json() == []
    assert api_client.delete(
        f"/api/me/task-list-views/{view['id']}", headers=_headers(PM_UM)
    ).status_code == 404

    db_row = db_session.query(TaskListView).filter(TaskListView.id == view["id"]).one()
    assert db_row.is_active is False
    reused = api_client.post(
        "/api/me/task-list-views",
        json={"name": "Vista Atualizada", "config": _config()},
        headers=_headers(PM_UM),
    )
    assert reused.status_code == 201, reused.text
    assert db_session.query(TaskListView).filter(
        TaskListView.name == "Vista Atualizada"
    ).count() == 2


def test_task_list_views_reject_invalid_names_and_configs_without_rows(db_session, api_client):
    invalid_bodies = [
        {"name": "   ", "config": _config()},
        {"name": "x" * 121, "config": _config()},
        {"name": None, "config": _config()},
        {"name": 5, "config": _config()},
        {"name": "Valid", "config": None},
        {"name": "Valid", "config": {**_config(), "unknown": True}},
        {"name": "Valid", "config": _config(columns=["task", "task"])},
        {"name": "Valid", "config": _config(filters={"status": "not-a-status"})},
    ]
    for body in invalid_bodies:
        response = api_client.post(
            "/api/me/task-list-views", json=body, headers=_headers(PM_UM)
        )
        assert response.status_code == 422, (body, response.text)

    assert db_session.query(TaskListView).filter(TaskListView.is_active.is_(True)).count() == 0


def test_pure_installer_scope_is_denied_but_combined_role_remains_additive(
    db_session, api_client
):
    email = "task-views-external@example.invalid"
    person = Person(display_name="Task Views External Sintético", email=email, is_active=True)
    db_session.add(person)
    db_session.flush()
    user = User(person_id=person.id, email=email, is_active=True)
    db_session.add(user)
    db_session.flush()
    role = db_session.query(Role).filter(Role.code == "instalador_colaborador").one()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    installer = db_session.query(Installer).filter(
        Installer.name == "Instalador Sintético Alfa"
    ).one()
    db_session.add(
        InstallerAccessMembership(person_id=person.id, installer_id=installer.id, is_active=True)
    )
    db_session.flush()
    headers = _headers(email)

    assert api_client.get("/api/me/task-list-preferences", headers=headers).status_code == 403
    assert api_client.put(
        "/api/me/task-list-preferences", json={"config": _config()}, headers=headers
    ).status_code == 403
    assert api_client.get("/api/me/task-list-views", headers=headers).status_code == 403
    assert api_client.post(
        "/api/me/task-list-views", json={"name": "Nope", "config": _config()}, headers=headers
    ).status_code == 403

    broad_role = db_session.query(Role).filter(Role.code == "chefe_operacoes").one()
    db_session.add(UserRole(user_id=user.id, role_id=broad_role.id))
    db_session.flush()
    assert api_client.get("/api/me/task-list-preferences", headers=headers).status_code == 200
    combined = api_client.post(
        "/api/me/task-list-views",
        json={"name": "Vista Combinada", "config": _config()},
        headers=headers,
    )
    assert combined.status_code == 201, combined.text


def test_invalid_uuid_path_is_422_and_unknown_uuid_is_404(api_client):
    assert api_client.patch(
        "/api/me/task-list-views/not-a-uuid",
        json={"name": "Atualizada"},
        headers=_headers(PM_UM),
    ).status_code == 422
    unknown = uuid.uuid4()
    assert api_client.patch(
        f"/api/me/task-list-views/{unknown}",
        json={"name": "Atualizada"},
        headers=_headers(PM_UM),
    ).status_code == 404
    assert api_client.delete(
        f"/api/me/task-list-views/{unknown}", headers=_headers(PM_UM)
    ).status_code == 404
