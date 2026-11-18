from __future__ import annotations

import datetime as dt
import uuid

from app.models.installer import Installer, InstallerTeam
from app.models.project import Project

CHEFE = "chefe.sintetico@example.invalid"
PM_UM = "pm.um.sintetico@example.invalid"


def _headers(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _installers(db_session):
    alfa = db_session.query(Installer).filter(Installer.name == "Instalador Sintético Alfa").one()
    beta = db_session.query(Installer).filter(Installer.name == "Instalador Sintético Beta").one()
    team = db_session.query(InstallerTeam).filter(
        InstallerTeam.installer_id == alfa.id,
        InstallerTeam.name == "Equipa 1",
    ).one()
    return alfa, beta, team


def test_calendar_accepts_repeated_legacy_installer_id_and_installer_ids_csv(db_session, api_client):
    alfa, beta, _team = _installers(db_session)
    response = api_client.get(
        "/api/works/calendar",
        params=[("from", (dt.date.today() - dt.timedelta(days=200)).isoformat()),
                ("to", (dt.date.today() + dt.timedelta(days=200)).isoformat()),
                ("installer_id", str(alfa.id)), ("installer_id", str(beta.id))],
        headers=_headers(CHEFE),
    )
    assert response.status_code == 200, response.text
    selected_ids = {row["installer_id"] for row in response.json()["works"]}
    assert str(alfa.id) in selected_ids and str(beta.id) in selected_ids

    csv_response = api_client.get(
        "/api/works/calendar",
        params={"from": (dt.date.today() - dt.timedelta(days=200)).isoformat(),
                "to": (dt.date.today() + dt.timedelta(days=200)).isoformat(),
                "installer_ids": f"{alfa.id},{beta.id}"},
        headers=_headers(CHEFE),
    )
    assert csv_response.status_code == 200, csv_response.text
    assert {row["project_id"] for row in csv_response.json()["works"]} == {
        row["project_id"] for row in response.json()["works"]
    }

    legacy = api_client.get(
        "/api/works/calendar",
        params={"from": (dt.date.today() - dt.timedelta(days=200)).isoformat(),
                "to": (dt.date.today() + dt.timedelta(days=200)).isoformat(),
                "installer_id": str(alfa.id)},
        headers=_headers(CHEFE),
    )
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["works"]
    assert {row["installer_id"] for row in legacy.json()["works"]} == {str(alfa.id)}


def test_preferences_store_multiple_installers_and_keep_legacy_single_read(db_session, api_client):
    alfa, beta, team = _installers(db_session)
    response = api_client.patch(
        "/api/me/works-preferences",
        json={"installer_ids": [str(alfa.id), str(beta.id)], "team_id": str(team.id)},
        headers=_headers(CHEFE),
    )
    assert response.status_code == 200, response.text
    assert response.json()["installer_ids"] == [str(alfa.id), str(beta.id)]
    assert response.json()["installer_id"] is None
    assert response.json()["team_id"] == str(team.id)

    invalid = api_client.patch(
        "/api/me/works-preferences",
        json={"installer_ids": [str(alfa.id), str(uuid.uuid4())]},
        headers=_headers(CHEFE),
    )
    assert invalid.status_code == 422
    assert api_client.get("/api/me/works-preferences", headers=_headers(CHEFE)).json()["installer_ids"] == [
        str(alfa.id), str(beta.id)
    ]

    legacy = api_client.patch(
        "/api/me/works-preferences", json={"installer_id": str(alfa.id)}, headers=_headers(PM_UM)
    )
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["installer_id"] == str(alfa.id)
    assert legacy.json()["installer_ids"] == [str(alfa.id)]


def test_saved_view_stores_applies_multiple_installers_and_rejects_incompatible_team(db_session, api_client):
    alfa, beta, team = _installers(db_session)
    created = api_client.post(
        "/api/me/works-saved-views",
        json={"name": "Vista multi sintética", "installer_ids": [str(alfa.id), str(beta.id)], "team_id": str(team.id)},
        headers=_headers(CHEFE),
    )
    assert created.status_code == 201, created.text
    assert created.json()["installer_ids"] == [str(alfa.id), str(beta.id)]
    assert created.json()["installer_id"] is None

    applied = api_client.post(
        f"/api/me/works-saved-views/{created.json()['id']}/apply", headers=_headers(CHEFE)
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["installer_ids"] == [str(alfa.id), str(beta.id)]
    assert applied.json()["installer_id"] is None

    beta_team = db_session.query(InstallerTeam).filter(
        InstallerTeam.installer_id == beta.id,
        InstallerTeam.is_active.is_(True),
    ).first()
    if beta_team is None:
        beta_team = InstallerTeam(installer_id=beta.id, name="Equipa Beta Sintética", name_key=f"equipa beta {uuid.uuid4()}")
        db_session.add(beta_team)
        db_session.flush()
    incompatible = api_client.post(
        "/api/me/works-saved-views",
        json={"name": "Vista equipa incompatível", "installer_ids": [str(alfa.id)], "team_id": str(beta_team.id)},
        headers=_headers(CHEFE),
    )
    assert incompatible.status_code == 422


def test_calendar_installer_ids_also_filters_unscheduled_projects(db_session, api_client):
    alfa, beta, _team = _installers(db_session)
    project_a = Project(name="Sem datas multi Alfa", is_active=True, lifecycle_status="preparacao", installer_id=alfa.id)
    project_b = Project(name="Sem datas multi Beta", is_active=True, lifecycle_status="preparacao", installer_id=beta.id)
    project_other = Project(name="Sem datas multi sem filtro", is_active=True, lifecycle_status="preparacao")
    db_session.add_all([project_a, project_b, project_other])
    db_session.flush()

    response = api_client.get(
        "/api/works/calendar",
        params={"from": "2035-01-01", "to": "2035-01-31", "installer_ids": f"{alfa.id},{beta.id}"},
        headers=_headers(CHEFE),
    )
    assert response.status_code == 200, response.text
    names = {item["name"] for item in response.json()["unscheduled"]}
    assert {project_a.name, project_b.name} <= names
    assert project_other.name not in names


def test_preferences_and_saved_views_fall_back_to_legacy_installer_id(db_session, api_client):
    from app.models.identity import User
    from app.models.works_preferences import UserWorksPreference
    from app.models.works_saved_views import WorksCalendarSavedView

    alfa, _beta, _team = _installers(db_session)
    user = db_session.query(User).filter(User.email == PM_UM).one()
    db_session.add_all(
        [
            UserWorksPreference(
                user_id=user.id,
                zoom="weeks",
                lifecycle_status=[],
                installer_id=alfa.id,
                installer_ids=None,
                show_idle=False,
            ),
            WorksCalendarSavedView(
                user_id=user.id,
                name="Vista legado multi",
                zoom="weeks",
                lifecycle_status=[],
                installer_id=alfa.id,
                installer_ids=None,
                show_idle=False,
            ),
        ]
    )
    db_session.flush()

    preference = api_client.get("/api/me/works-preferences", headers=_headers(PM_UM))
    assert preference.status_code == 200, preference.text
    assert preference.json()["installer_id"] == str(alfa.id)
    assert preference.json()["installer_ids"] == [str(alfa.id)]

    views = api_client.get("/api/me/works-saved-views", headers=_headers(PM_UM))
    assert views.status_code == 200, views.text
    assert len(views.json()) == 1
    assert views.json()[0]["installer_id"] == str(alfa.id)
    assert views.json()[0]["installer_ids"] == [str(alfa.id)]


def test_foreign_installer_ids_do_not_expand_scoped_calendar_or_leak_saved_references(
    db_session, api_client
):
    import datetime as dt

    from app.models.identity import Role, User, UserRole
    from app.models.installer_access import InstallerAccessMembership
    from app.models.people import Person
    from app.models.works_preferences import UserWorksPreference
    from app.models.works_saved_views import WorksCalendarSavedView
    from app.security.catalog import ROLE_INSTALLER_COLLABORATOR

    alfa, beta, _alfa_team = _installers(db_session)
    beta_team = db_session.query(InstallerTeam).filter(
        InstallerTeam.installer_id == beta.id,
        InstallerTeam.is_active.is_(True),
    ).first()
    if beta_team is None:
        beta_team = InstallerTeam(
            installer_id=beta.id,
            name="Equipa Beta multi privada",
            name_key=f"equipa beta multi privada {uuid.uuid4()}",
        )
        db_session.add(beta_team)
        db_session.flush()

    email = "multi.installer.scope.synthetic@example.invalid"
    person = Person(display_name="Multi Installer Scoped User", email=email, is_active=True)
    db_session.add(person)
    db_session.flush()
    user = User(person_id=person.id, email=email, is_active=True)
    db_session.add(user)
    db_session.flush()
    role = db_session.query(Role).filter(Role.code == ROLE_INSTALLER_COLLABORATOR).one()
    db_session.add_all(
        [
            UserRole(user_id=user.id, role_id=role.id),
            InstallerAccessMembership(
                person_id=person.id, installer_id=alfa.id, is_active=True
            ),
        ]
    )
    db_session.flush()

    own_scheduled = Project(
        name="Scoped own scheduled multi installer",
        is_active=True,
        lifecycle_status="preparacao",
        installer_id=alfa.id,
        work_start_date=dt.date(2041, 2, 1),
        work_end_date=dt.date(2041, 2, 5),
    )
    foreign_scheduled = Project(
        name="FOREIGN_SCOPED_SCHEDULED_PRIVATE_SENTINEL",
        is_active=True,
        lifecycle_status="preparacao",
        installer_id=beta.id,
        work_start_date=dt.date(2041, 2, 1),
        work_end_date=dt.date(2041, 2, 5),
    )
    own_unscheduled = Project(
        name="Scoped own unscheduled multi installer",
        is_active=True,
        lifecycle_status="preparacao",
        installer_id=alfa.id,
    )
    foreign_unscheduled = Project(
        name="FOREIGN_SCOPED_UNSCHEDULED_PRIVATE_SENTINEL",
        is_active=True,
        lifecycle_status="preparacao",
        installer_id=beta.id,
    )
    db_session.add_all(
        [own_scheduled, foreign_scheduled, own_unscheduled, foreign_unscheduled]
    )
    db_session.flush()

    headers = _headers(email)
    calendar = api_client.get(
        "/api/works/calendar",
        params={
            "from": "2041-02-01",
            "to": "2041-02-10",
            "installer_ids": f"{alfa.id},{beta.id}",
        },
        headers=headers,
    )
    assert calendar.status_code == 200, calendar.text
    assert own_scheduled.name in {row["name"] for row in calendar.json()["works"]}
    assert foreign_scheduled.name not in calendar.text
    assert own_unscheduled.name in {row["name"] for row in calendar.json()["unscheduled"]}
    assert foreign_unscheduled.name not in calendar.text

    foreign_only = api_client.get(
        "/api/works/calendar",
        params={
            "from": "2041-02-01",
            "to": "2041-02-10",
            "installer_ids": str(beta.id),
        },
        headers=headers,
    )
    assert foreign_only.status_code == 200, foreign_only.text
    assert foreign_scheduled.name not in foreign_only.text
    assert foreign_unscheduled.name not in foreign_only.text
    assert foreign_only.json()["works"] == []
    assert foreign_only.json()["unscheduled"] == []

    teams = api_client.get(
        "/api/works/teams",
        params={
            "date": "2041-02-01",
            "days": 10,
            "installer_ids": f"{alfa.id},{beta.id}",
        },
        headers=headers,
    )
    assert teams.status_code == 200, teams.text
    assert {item["id"] for item in teams.json()["installers"]} == {str(alfa.id)}
    assert str(beta.id) not in teams.text

    # Simulate an old/corrupt persisted selection: read projection must redact
    # the foreign installer/team without rewriting the stored row.
    preference = UserWorksPreference(
        user_id=user.id,
        zoom="weeks",
        lifecycle_status=[],
        installer_ids=[str(alfa.id), str(beta.id)],
        installer_id=None,
        team_id=_alfa_team.id,
        show_idle=False,
    )
    saved_view = WorksCalendarSavedView(
        user_id=user.id,
        name="Scoped multi saved view",
        zoom="weeks",
        lifecycle_status=[],
        installer_ids=[str(alfa.id), str(beta.id)],
        installer_id=None,
        team_id=_alfa_team.id,
        show_idle=False,
    )
    db_session.add_all([preference, saved_view])
    db_session.flush()

    preference_response = api_client.get("/api/me/works-preferences", headers=headers)
    assert preference_response.status_code == 200, preference_response.text
    assert preference_response.json()["installer_ids"] == [str(alfa.id)]
    assert preference_response.json()["installer_id"] == str(alfa.id)
    assert preference_response.json()["team_id"] == str(_alfa_team.id)
    assert str(beta.id) not in preference_response.text
    assert str(beta_team.id) not in preference_response.text

    views_response = api_client.get("/api/me/works-saved-views", headers=headers)
    assert views_response.status_code == 200, views_response.text
    assert len(views_response.json()) == 1
    assert views_response.json()[0]["installer_ids"] == [str(alfa.id)]
    assert views_response.json()[0]["installer_id"] == str(alfa.id)
    assert views_response.json()[0]["team_id"] == str(_alfa_team.id)
    assert str(beta.id) not in views_response.text
    assert str(beta_team.id) not in views_response.text

    db_session.refresh(preference)
    db_session.refresh(saved_view)
    assert preference.installer_ids == [str(alfa.id), str(beta.id)]
    assert preference.team_id == _alfa_team.id
    assert saved_view.installer_ids == [str(alfa.id), str(beta.id)]
    assert saved_view.team_id == _alfa_team.id


def test_teams_idle_endpoint_accepts_multiple_installer_filters(db_session, api_client):
    alfa, beta, _team = _installers(db_session)
    unrelated = Installer(
        name="Instalador Sintético Gama multi",
        name_key="instalador sintetico gama multi",
        is_active=True,
    )
    db_session.add(unrelated)
    db_session.flush()
    common = {"date": "2041-02-01", "days": 10}
    headers = _headers(CHEFE)

    csv_response = api_client.get(
        "/api/works/teams",
        params={**common, "installer_ids": f"{alfa.id},{beta.id}"},
        headers=headers,
    )
    assert csv_response.status_code == 200, csv_response.text
    csv_ids = {item["id"] for item in csv_response.json()["installers"]}
    assert csv_ids == {str(alfa.id), str(beta.id)}

    repeated_response = api_client.get(
        "/api/works/teams",
        params=[("date", common["date"]), ("days", common["days"]),
                ("installer_ids", str(alfa.id)), ("installer_ids", str(beta.id))],
        headers=headers,
    )
    assert repeated_response.status_code == 200, repeated_response.text
    assert {item["id"] for item in repeated_response.json()["installers"]} == csv_ids

    legacy_response = api_client.get(
        "/api/works/teams",
        params={**common, "installer_id": str(alfa.id)},
        headers=headers,
    )
    assert legacy_response.status_code == 200, legacy_response.text
    assert {item["id"] for item in legacy_response.json()["installers"]} == {str(alfa.id)}
