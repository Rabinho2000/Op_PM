from __future__ import annotations

import datetime as dt
import uuid

import pytest

from app.models.identity import Role, User, UserRole
from app.models.installer import Installer, InstallerTeam
from app.models.installer_access import InstallerAccessMembership
from app.models.people import Person
from app.models.project import Project, ProjectTeamAssignment
from app.models.task import Task
from app.models.workflow import WorkflowStage, WorkflowSubtask
from app.security.catalog import ROLE_INSTALLER_COLLABORATOR


EMAIL = "f06.installer.a@example.invalid"


def _headers() -> dict[str, str]:
    return {"X-Dev-User-Email": EMAIL}


def _make_external_user(db_session, installer: Installer) -> Person:
    person = Person(
        display_name="F06 External Installer A",
        email=EMAIL,
        is_active=True,
    )
    db_session.add(person)
    db_session.flush()
    user = User(person_id=person.id, email=EMAIL, is_active=True)
    db_session.add(user)
    db_session.flush()
    role = db_session.query(Role).filter(Role.code == ROLE_INSTALLER_COLLABORATOR).one()
    db_session.add_all(
        [
            UserRole(user_id=user.id, role_id=role.id),
            InstallerAccessMembership(person_id=person.id, installer_id=installer.id, is_active=True),
        ]
    )
    db_session.flush()
    return person


def _mutation_fixture(db_session):
    alfa = db_session.query(Installer).filter(Installer.name == "Instalador Sintético Alfa").one()
    beta = db_session.query(Installer).filter(Installer.name == "Instalador Sintético Beta").one()
    alfa_team = (
        db_session.query(InstallerTeam)
        .filter(InstallerTeam.installer_id == alfa.id, InstallerTeam.name == "Equipa 1")
        .one()
    )
    beta_team = InstallerTeam(
        installer_id=beta.id,
        name=f"F06 Foreign Team {uuid.uuid4()}",
        name_key=f"f06-foreign-team-{uuid.uuid4()}",
    )
    db_session.add(beta_team)
    db_session.flush()
    actor = _make_external_user(db_session, alfa)

    joint = Project(
        name=f"F06 Joint Project {uuid.uuid4()}",
        installer_id=alfa.id,
        installer_team_id=alfa_team.id,
        is_active=True,
        lifecycle_status="construcao",
        work_start_date=dt.date(2042, 3, 1),
        work_end_date=dt.date(2042, 3, 10),
    )
    foreign = Project(
        name=f"F06 Foreign Project {uuid.uuid4()}",
        installer_id=beta.id,
        is_active=True,
        lifecycle_status="construcao",
        work_start_date=dt.date(2042, 3, 1),
        work_end_date=dt.date(2042, 3, 10),
    )
    db_session.add_all([joint, foreign])
    db_session.flush()
    foreign_assignment = ProjectTeamAssignment(
        project_id=joint.id,
        installer_id=beta.id,
        team_id=beta_team.id,
        start_date=dt.date(2042, 3, 1),
        end_date=dt.date(2042, 3, 5),
        note="F06 foreign assignment",
        created_by_person_id=actor.id,
    )
    task = Task(
        project_id=joint.id,
        title="F06 visible task",
        created_by_person_id=actor.id,
    )
    foreign_task = Task(
        project_id=foreign.id,
        title="F06 foreign task",
        created_by_person_id=actor.id,
    )
    db_session.add_all([foreign_assignment, task, foreign_task])
    db_session.flush()
    stage = db_session.query(WorkflowStage).order_by(WorkflowStage.id).first()
    subtask = db_session.query(WorkflowSubtask).order_by(WorkflowSubtask.id).first()
    assert stage is not None and subtask is not None
    return {
        "joint": joint,
        "foreign": foreign,
        "foreign_assignment": foreign_assignment,
        "task": task,
        "foreign_task": foreign_task,
        "alfa_team": alfa_team,
        "stage": stage,
        "subtask": subtask,
    }


@pytest.mark.parametrize(
    ("method", "path_builder", "body_builder", "resource_key"),
    [
        (
            "PATCH",
            lambda data, resource_id: f"/api/projects/{resource_id}",
            lambda _data: {"notes": "F06 attempted project write"},
            "joint",
        ),
        (
            "PATCH",
            lambda data, resource_id: f"/api/projects/{resource_id}/status",
            lambda _data: {"lifecycle_status": "construcao", "note": "F06 attempted status write"},
            "joint",
        ),
        (
            "PATCH",
            lambda data, resource_id: f"/api/projects/{resource_id}/work-plan",
            lambda _data: {"work_start_date": "2042-03-02"},
            "joint",
        ),
        (
            "POST",
            lambda data, resource_id: f"/api/projects/{resource_id}/team-assignments",
            lambda data: {
                "team_id": str(data["alfa_team"].id),
                "start_date": "2042-03-06",
                "end_date": "2042-03-07",
                "note": "F06 attempted assignment write",
            },
            "joint",
        ),
        (
            "PATCH",
            lambda data, resource_id: f"/api/projects/{resource_id}/team-assignments/{data['foreign_assignment'].id}",
            lambda _data: {"end_date": "2042-03-08"},
            "joint",
        ),
        (
            "DELETE",
            lambda data, resource_id: f"/api/projects/{resource_id}/team-assignments/{data['foreign_assignment'].id}",
            lambda _data: None,
            "joint",
        ),
        (
            "PATCH",
            lambda data, resource_id: f"/api/projects/{resource_id}/process/subtasks/{data['subtask'].id}",
            lambda _data: {"done": True},
            "joint",
        ),
        (
            "PATCH",
            lambda data, resource_id: f"/api/projects/{resource_id}/process/stages/{data['stage'].id}/contact",
            lambda _data: {"done": True},
            "joint",
        ),
    ],
)
def test_installer_mutations_are_denied_before_project_or_assignment_lookup(
    db_session, api_client, method, path_builder, body_builder, resource_key
):
    data = _mutation_fixture(db_session)
    existing_path = path_builder(data, data[resource_key].id)
    missing_path = path_builder(data, uuid.uuid4())
    body = body_builder(data)

    existing = api_client.request(method, existing_path, json=body, headers=_headers())
    missing = api_client.request(method, missing_path, json=body, headers=_headers())
    assert existing.status_code == 403, existing.text
    assert missing.status_code == 403, missing.text


def test_installer_project_and_task_create_do_not_oracle_foreign_uuid_existence(db_session, api_client):
    data = _mutation_fixture(db_session)

    project_existing = api_client.patch(
        f"/api/projects/{data['foreign'].id}",
        json={"notes": "F06 foreign project write"},
        headers=_headers(),
    )
    project_missing = api_client.patch(
        f"/api/projects/{uuid.uuid4()}",
        json={"notes": "F06 missing project write"},
        headers=_headers(),
    )
    assert project_existing.status_code == 403, project_existing.text
    assert project_missing.status_code == 403, project_missing.text

    task_body = {
        "project_id": str(data["foreign"].id),
        "title": "F06 foreign task write",
        "task_type": "custom",
        "priority": "medium",
        "category": "other",
    }
    task_existing = api_client.post("/api/tasks", json=task_body, headers=_headers())
    task_body["project_id"] = str(uuid.uuid4())
    task_missing = api_client.post("/api/tasks", json=task_body, headers=_headers())
    assert task_existing.status_code == 403, task_existing.text
    assert task_missing.status_code == 403, task_missing.text


def test_installer_task_update_does_not_oracle_existing_task_uuid(db_session, api_client):
    data = _mutation_fixture(db_session)
    existing = api_client.patch(
        f"/api/tasks/{data['task'].id}",
        json={"title": "F06 attempted task write"},
        headers=_headers(),
    )
    missing = api_client.patch(
        f"/api/tasks/{uuid.uuid4()}",
        json={"title": "F06 attempted missing task write"},
        headers=_headers(),
    )
    assert existing.status_code == 403, existing.text
    assert missing.status_code == 403, missing.text
