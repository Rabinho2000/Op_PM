from __future__ import annotations

import datetime as dt
import uuid

from app.models.identity import Role, User, UserRole
from app.models.installer import Installer, InstallerTeam
from app.models.installer_access import InstallerAccessMembership
from app.models.people import Person
from app.models.project import Project, ProjectTeamAssignment
from app.security.catalog import ROLE_INSTALLER_COLLABORATOR


EXTERNAL_EMAIL = "f02.installer.a@example.invalid"
FOREIGN_NOTE = "F02_FOREIGN_PRIVATE_NOTE_SENTINEL"
OWN_NOTE = "F02_OWN_PRIVATE_NOTE_SENTINEL"
FOREIGN_LEADER = "F02 Foreign Leader Sentinel"
FOREIGN_PHONE = "+351 299 999 999"


def _headers(email: str = EXTERNAL_EMAIL) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _external_user(db_session, installer: Installer) -> tuple[Person, User]:
    person = Person(
        display_name="F02 External Installer A",
        email=EXTERNAL_EMAIL,
        is_active=True,
    )
    db_session.add(person)
    db_session.flush()
    user = User(person_id=person.id, email=EXTERNAL_EMAIL, is_active=True)
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
    return person, user


def _joint_fixture(db_session):
    alfa = db_session.query(Installer).filter(Installer.name == "Instalador Sintético Alfa").one()
    beta = db_session.query(Installer).filter(Installer.name == "Instalador Sintético Beta").one()
    alfa_team = (
        db_session.query(InstallerTeam)
        .filter(InstallerTeam.installer_id == alfa.id, InstallerTeam.name == "Equipa 1")
        .one()
    )
    beta_team = InstallerTeam(
        installer_id=beta.id,
        name=f"F02 Foreign Team {uuid.uuid4()}",
        name_key=f"f02-foreign-team-{uuid.uuid4()}",
        leader_name=FOREIGN_LEADER,
        leader_phone=FOREIGN_PHONE,
    )
    foreign_creator = Person(
        display_name="F02 Foreign Assignment Creator",
        email=f"f02.creator.{uuid.uuid4()}@example.invalid",
        is_active=True,
    )
    db_session.add_all([beta_team, foreign_creator])
    db_session.flush()
    external_person, _ = _external_user(db_session, alfa)

    project = Project(
        name=f"F02 Joint Project {uuid.uuid4()}",
        client_name="F02 synthetic client",
        installer_id=alfa.id,
        installer_team_id=alfa_team.id,
        is_active=True,
        lifecycle_status="construcao",
        work_start_date=dt.date(2041, 2, 1),
        work_end_date=dt.date(2041, 2, 10),
    )
    db_session.add(project)
    db_session.flush()
    own_assignment = ProjectTeamAssignment(
        project_id=project.id,
        installer_id=alfa.id,
        team_id=alfa_team.id,
        start_date=dt.date(2041, 2, 1),
        end_date=dt.date(2041, 2, 5),
        note=OWN_NOTE,
        created_by_person_id=external_person.id,
    )
    foreign_assignment = ProjectTeamAssignment(
        project_id=project.id,
        installer_id=beta.id,
        team_id=beta_team.id,
        start_date=dt.date(2041, 2, 1),
        end_date=dt.date(2041, 2, 5),
        note=FOREIGN_NOTE,
        created_by_person_id=foreign_creator.id,
    )
    db_session.add_all([own_assignment, foreign_assignment])
    db_session.flush()
    return project, own_assignment, foreign_assignment, alfa, beta, alfa_team, beta_team, foreign_creator


def test_joint_project_reads_only_canonical_installer_rows_and_redacts_sensitive_fields(
    db_session, api_client
):
    (
        project,
        own_assignment,
        foreign_assignment,
        alfa,
        beta,
        alfa_team,
        beta_team,
        foreign_creator,
    ) = _joint_fixture(db_session)

    assignments_response = api_client.get(
        f"/api/projects/{project.id}/team-assignments", headers=_headers()
    )
    assert assignments_response.status_code == 200, assignments_response.text
    assignments = assignments_response.json()
    assert [row["id"] for row in assignments] == [str(own_assignment.id)]
    row = assignments[0]
    assert row["installer_id"] == str(alfa.id)
    assert row["team_id"] == str(alfa_team.id)
    assert row["installer_name"] == alfa.name
    assert row["team_name"] == alfa_team.name
    assert row["note"] == ""
    assert row["created_by_person_id"] is None
    assert row["team_leader_name"] is None
    assert row["team_leader_phone"] is None
    for sentinel in (FOREIGN_NOTE, OWN_NOTE, FOREIGN_LEADER, FOREIGN_PHONE, str(beta.id), str(beta_team.id), str(foreign_creator.id)):
        assert sentinel not in assignments_response.text

    calendar_response = api_client.get(
        "/api/works/calendar",
        params={"from": "2041-02-01", "to": "2041-02-10"},
        headers=_headers(),
    )
    assert calendar_response.status_code == 200, calendar_response.text
    calendar = calendar_response.json()
    assert [item["assignment_id"] for item in calendar["works"]] == [str(own_assignment.id)]
    calendar_row = calendar["works"][0]
    assert calendar_row["installer_id"] == str(alfa.id)
    assert calendar_row["team_id"] == str(alfa_team.id)
    assert calendar_row["team_name"] == alfa_team.name
    assert calendar_row["team_leader_name"] is None
    assert calendar_row["can_plan_work"] is False
    for sentinel in (FOREIGN_NOTE, OWN_NOTE, FOREIGN_LEADER, FOREIGN_PHONE, str(beta.id), str(beta_team.id), str(foreign_creator.id)):
        assert sentinel not in calendar_response.text

    # DTO redaction must not dirty or rewrite the source rows.
    db_session.expire_all()
    persisted = (
        db_session.query(ProjectTeamAssignment)
        .filter(ProjectTeamAssignment.project_id == project.id)
        .all()
    )
    by_installer = {item.installer_id: item for item in persisted}
    own_person_id = db_session.query(Person).filter(Person.email == EXTERNAL_EMAIL).one().id
    assert [(by_installer[alfa.id].note, by_installer[alfa.id].created_by_person_id),
            (by_installer[beta.id].note, by_installer[beta.id].created_by_person_id)] == [
        (OWN_NOTE, own_person_id),
        (FOREIGN_NOTE, foreign_creator.id),
    ]


def test_scoped_works_teams_returns_redacted_own_rows_and_empty_after_revocation(
    db_session, api_client
):
    (
        project,
        own_assignment,
        foreign_assignment,
        alfa,
        beta,
        alfa_team,
        beta_team,
        foreign_creator,
    ) = _joint_fixture(db_session)
    own_assignment.start_date = foreign_assignment.start_date = dt.date(2044, 2, 1)
    own_assignment.end_date = foreign_assignment.end_date = dt.date(2044, 2, 5)
    db_session.flush()

    response = api_client.get(
        "/api/works/teams",
        params={"date": "2044-02-01", "days": 10},
        headers=_headers(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["date"] == "2044-02-01"
    assert body["days"] == 10
    assert [installer["id"] for installer in body["installers"]] == [str(alfa.id)]
    installer = body["installers"][0]
    # The legacy owner bar remains visible even though the project also has a
    # foreign assignment that must not leak into the scoped response.
    team = next(item for item in installer["teams"] if item["id"] == str(alfa_team.id))
    assert team["status"] == "ocupada"
    assert team["free"] is False
    assert [row["id"] for row in team["assignments"]] == [str(own_assignment.id)]
    row = team["assignments"][0]
    assert row["project_id"] == str(project.id)
    assert row["note"] == ""
    assert row["pm_person_id"] is None
    assert row["pm_display_name"] is None
    for sentinel in (
        FOREIGN_NOTE,
        OWN_NOTE,
        FOREIGN_LEADER,
        FOREIGN_PHONE,
        str(beta.id),
        str(beta_team.id),
        str(foreign_assignment.id),
        str(foreign_creator.id),
    ):
        assert sentinel not in response.text

    staff_response = api_client.get(
        "/api/works/teams",
        params={"date": "2044-02-01", "days": 10},
        headers={"X-Dev-User-Email": "chefe.sintetico@example.invalid"},
    )
    assert staff_response.status_code == 200, staff_response.text
    staff_rows = {
        row["id"]: row
        for installer_item in staff_response.json()["installers"]
        for team_item in installer_item["teams"]
        for row in team_item["assignments"]
    }
    assert staff_rows[str(own_assignment.id)]["note"] == OWN_NOTE
    assert staff_rows[str(own_assignment.id)]["pm_person_id"] == project.pm_person_id

    membership = (
        db_session.query(InstallerAccessMembership)
        .join(Person, Person.id == InstallerAccessMembership.person_id)
        .filter(Person.email == EXTERNAL_EMAIL, InstallerAccessMembership.installer_id == alfa.id)
        .one()
    )
    membership.is_active = False
    db_session.flush()
    revoked_response = api_client.get(
        "/api/works/teams",
        params={"date": "2044-02-01", "days": 10},
        headers=_headers(),
    )
    assert revoked_response.status_code == 200, revoked_response.text
    assert revoked_response.json()["installers"] == []


def test_scoped_calendar_keeps_owner_legacy_bar_without_foreign_team(db_session, api_client):
    (
        project,
        own_assignment,
        foreign_assignment,
        alfa,
        beta,
        alfa_team,
        beta_team,
        foreign_creator,
    ) = _joint_fixture(db_session)
    db_session.delete(own_assignment)
    db_session.flush()
    db_session.expire(project)

    response = api_client.get(
        "/api/works/calendar",
        params={"from": "2041-02-01", "to": "2041-02-10"},
        headers=_headers(),
    )
    assert response.status_code == 200, response.text
    works = response.json()["works"]
    assert len(works) == 1
    assert works[0]["project_id"] == str(project.id)
    assert works[0]["assignment_id"] is None
    assert works[0]["installer_id"] == str(alfa.id)
    assert works[0]["team_id"] is None
    assert works[0]["team_name"] is None
    assert works[0]["team_leader_name"] is None
    assert works[0]["can_plan_work"] is False
    for sentinel in (str(foreign_assignment.id), str(beta.id), str(beta_team.id), str(foreign_creator.id)):
        assert sentinel not in response.text


def test_installer_access_team_catalog_remains_membership_scoped(db_session, api_client):
    _project, _own, _foreign, alfa, beta, _alfa_team, beta_team, _creator = _joint_fixture(db_session)

    response = api_client.get("/api/installer-access/teams", headers=_headers())
    assert response.status_code == 200, response.text
    body = response.json()
    assert [installer["id"] for installer in body] == [str(alfa.id)]
    assert str(beta.id) not in response.text
    assert beta_team.name not in response.text
