from __future__ import annotations

import datetime as dt
import uuid

from app.models.identity import Role, User, UserRole
from app.models.installer import Installer, InstallerTeam
from app.models.installer_access import InstallerAccessMembership
from app.models.people import Person
from app.models.project import Project, ProjectTeamAssignment
from app.models.time_bank import TimeBankEntry
from app.models.works_preferences import UserWorksPreference
from app.models.works_saved_views import WorksCalendarSavedView
from app.security.catalog import ROLE_INSTALLER_COLLABORATOR

EXTERNAL_EMAIL = "auxiliar.privacidade.instalador@example.invalid"


def _headers(email: str = EXTERNAL_EMAIL) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _setup_external_scope(db_session, *, active_membership: bool = True) -> dict[str, object]:
    alpha = db_session.query(Installer).filter(Installer.name == "Instalador Sintético Alfa").one()
    beta = db_session.query(Installer).filter(Installer.name == "Instalador Sintético Beta").one()
    alpha_team = (
        db_session.query(InstallerTeam)
        .filter(InstallerTeam.installer_id == alpha.id, InstallerTeam.name == "Equipa 1")
        .one()
    )
    beta_team = InstallerTeam(
        installer_id=beta.id,
        name="Equipa Auxiliar Beta",
        name_key="equipa auxiliar beta",
        leader_name="Lider Estrangeiro Sintético",
        leader_phone="+351 210 000 099",
    )
    db_session.add(beta_team)
    db_session.flush()

    project = (
        db_session.query(Project)
        .filter(Project.name == "Instalação Sintética de Demonstração")
        .one()
    )
    foreign_pm = db_session.query(Person).filter(Person.display_name == "Chefe Sintético").one()
    db_session.add(
        ProjectTeamAssignment(
            project_id=project.id,
            installer_id=beta.id,
            team_id=beta_team.id,
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 12, 31),
            note="Nota privada da equipa estrangeira",
            created_by_person_id=foreign_pm.id,
        )
    )

    person = Person(
        display_name="Colaborador Auxiliar Sintético",
        email=EXTERNAL_EMAIL,
        is_active=True,
    )
    db_session.add(person)
    db_session.flush()
    user = User(person_id=person.id, email=EXTERNAL_EMAIL, is_active=True)
    db_session.add(user)
    db_session.flush()
    role = db_session.query(Role).filter(Role.code == ROLE_INSTALLER_COLLABORATOR).one()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    membership = InstallerAccessMembership(
        person_id=person.id,
        installer_id=alpha.id,
        is_active=active_membership,
    )
    db_session.add(membership)
    db_session.flush()
    return {
        "alpha": alpha,
        "alpha_team": alpha_team,
        "beta": beta,
        "beta_team": beta_team,
        "foreign_pm": foreign_pm,
        "person": person,
        "project": project,
        "user": user,
        "membership": membership,
    }


def test_external_auxiliary_routes_are_denied_or_self_only(db_session, api_client):
    scope = _setup_external_scope(db_session)
    project = scope["project"]
    person = scope["person"]
    assert isinstance(project, Project)
    assert isinstance(person, Person)
    headers = _headers()

    planning_requests = [
        ("/api/planning/process-events", {"project_id": str(project.id)}),
        ("/api/planning/process-events", {"project_id": str(uuid.uuid4())}),
        (f"/api/planning/process-options/{project.id}", None),
        (f"/api/planning/process-options/{uuid.uuid4()}", None),
        ("/api/planning/events", {"project_id": str(project.id)}),
        ("/api/planning/events", {"project_id": str(uuid.uuid4())}),
        ("/api/planning/calendar", {"project_id": str(project.id)}),
        ("/api/planning/event-categories", None),
        ("/api/me/planning-preferences", None),
    ]
    for path, params in planning_requests:
        response = api_client.get(path, params=params, headers=headers)
        assert response.status_code == 403, (path, response.text)

    dashboard = api_client.get("/api/dashboard/summary", headers=headers)
    assert dashboard.status_code == 403, dashboard.text

    people = api_client.get("/api/people", headers=headers)
    assert people.status_code == 200, people.text
    assert people.json() == [
        {
            "id": str(person.id),
            "display_name": "Colaborador Auxiliar Sintético",
            "email": None,
            "is_active": True,
        }
    ]
    db_session.refresh(scope["person"])
    assert scope["person"].email == EXTERNAL_EMAIL


def test_external_filter_reads_redact_foreign_ids_without_mutating_private_rows(
    db_session, api_client
):
    scope = _setup_external_scope(db_session)
    user = scope["user"]
    foreign_pm = scope["foreign_pm"]
    beta = scope["beta"]
    beta_team = scope["beta_team"]
    alpha = scope["alpha"]
    alpha_team = scope["alpha_team"]
    assert isinstance(user, User)
    assert isinstance(foreign_pm, Person)
    assert isinstance(beta, Installer)
    assert isinstance(beta_team, InstallerTeam)
    assert isinstance(alpha, Installer)
    assert isinstance(alpha_team, InstallerTeam)

    preference = UserWorksPreference(
        user_id=user.id,
        zoom="weeks",
        lifecycle_status=["construcao"],
        pm_person_id=foreign_pm.id,
        installer_id=beta.id,
        team_id=beta_team.id,
        show_idle=True,
    )
    foreign_view = WorksCalendarSavedView(
        user_id=user.id,
        name="Vista estrangeira sintética",
        zoom="weeks",
        lifecycle_status=["construcao"],
        pm_person_id=foreign_pm.id,
        installer_id=beta.id,
        team_id=beta_team.id,
        show_idle=True,
    )
    own_installer_view = WorksCalendarSavedView(
        user_id=user.id,
        name="Vista instalador próprio sintética",
        zoom="weeks",
        lifecycle_status=["construcao"],
        pm_person_id=foreign_pm.id,
        installer_id=alpha.id,
        team_id=alpha_team.id,
        show_idle=False,
    )
    db_session.add_all([preference, foreign_view, own_installer_view])
    db_session.flush()
    original_preference_ids = (
        preference.pm_person_id,
        preference.installer_id,
        preference.team_id,
    )
    original_foreign_view_ids = (
        foreign_view.pm_person_id,
        foreign_view.installer_id,
        foreign_view.team_id,
    )

    preferences = api_client.get("/api/me/works-preferences", headers=_headers())
    assert preferences.status_code == 200, preferences.text
    assert preferences.json()["pm_person_id"] is None
    assert preferences.json()["installer_id"] is None
    assert preferences.json()["team_id"] is None

    views = api_client.get("/api/me/works-saved-views", headers=_headers())
    assert views.status_code == 200, views.text
    by_name = {view["name"]: view for view in views.json()}
    assert by_name["Vista estrangeira sintética"]["pm_person_id"] is None
    assert by_name["Vista estrangeira sintética"]["installer_id"] is None
    assert by_name["Vista estrangeira sintética"]["team_id"] is None
    assert by_name["Vista instalador próprio sintética"]["pm_person_id"] is None
    assert by_name["Vista instalador próprio sintética"]["installer_id"] == str(alpha.id)
    assert by_name["Vista instalador próprio sintética"]["team_id"] == str(alpha_team.id)

    db_session.expire_all()
    stored_preference = db_session.get(UserWorksPreference, preference.id)
    stored_foreign_view = db_session.get(WorksCalendarSavedView, foreign_view.id)
    assert stored_preference is not None
    assert stored_foreign_view is not None
    assert (
        stored_preference.pm_person_id,
        stored_preference.installer_id,
        stored_preference.team_id,
    ) == original_preference_ids
    assert (
        stored_foreign_view.pm_person_id,
        stored_foreign_view.installer_id,
        stored_foreign_view.team_id,
    ) == original_foreign_view_ids


def test_own_time_bank_does_not_depend_on_active_installer_membership(db_session, api_client):
    scope = _setup_external_scope(db_session, active_membership=False)
    person = scope["person"]
    user = scope["user"]
    foreign_pm = scope["foreign_pm"]
    assert isinstance(person, Person)
    assert isinstance(user, User)
    assert isinstance(foreign_pm, Person)
    db_session.add(
        TimeBankEntry(
            person_id=person.id,
            work_date=dt.date(2026, 10, 15),
            start_minute=540,
            end_minute=840,
            lunch_taken=False,
            balance_seconds=3600,
            calculated_seconds=3600,
            calculation_mode="standard",
            needs_review=False,
            review_flags={},
            provenance={"source": "synthetic-auxiliary-privacy"},
            source_key="auxiliary-privacy-own-bank",
            created_by_user_id=user.id,
        )
    )
    db_session.flush()

    projects = api_client.get("/api/projects", headers=_headers())
    assert projects.status_code == 200, projects.text
    assert projects.json() == []

    entries = api_client.get("/api/time-bank/entries", headers=_headers())
    assert entries.status_code == 200, entries.text
    assert entries.json()["total"] == 1
    assert entries.json()["items"][0]["person_id"] == str(person.id)

    people = api_client.get("/api/time-bank/people", headers=_headers())
    assert people.status_code == 200, people.text
    assert [row["id"] for row in people.json()] == [str(person.id)]

    foreign_entries = api_client.get(
        f"/api/time-bank/entries?person_id={foreign_pm.id}", headers=_headers()
    )
    assert foreign_entries.status_code == 403, foreign_entries.text
