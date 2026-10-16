"""Vista operacional das equipas e calendário baseado em atribuições (D-080)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import event

from app.models.installer import Installer, InstallerTeam
from app.models.project import Project, ProjectTeamAssignment
from app.db import engine

CHEFE = "chefe.sintetico@example.invalid"
PM_UM = "pm.um.sintetico@example.invalid"
ALFA = "Instalador Sintético Alfa"
BETA = "Instalador Sintético Beta"
OWN = "Instalação Sintética de Demonstração"
OTHER = "Instalação Sintética Incompleta"
LEGACY_PM = "Instalação Sintética F — PM Legado"


def _h(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _team(db, installer_name: str, team_name: str) -> InstallerTeam:
    installer = db.query(Installer).filter(Installer.name == installer_name).one()
    return next(team for team in installer.teams if team.name == team_name)


def _project(db, name: str) -> Project:
    return db.query(Project).filter(Project.name == name).one()


def _assignment(db, project: Project, team: InstallerTeam, start: dt.date, end: dt.date) -> ProjectTeamAssignment:
    project.installer_id = team.installer_id
    assignment = ProjectTeamAssignment(
        project_id=project.id,
        installer_id=team.installer_id,
        team_id=team.id,
        start_date=start,
        end_date=end,
    )
    db.add(assignment)
    db.flush()
    return assignment


def _teams(api_client, email: str, date: dt.date, days: int = 1, **params):
    query = {"date": date.isoformat(), "days": days, **params}
    return api_client.get("/api/works/teams", params=query, headers=_h(email))


def _team_json(response, name: str) -> dict:
    assert response.status_code == 200, response.text
    for installer in response.json()["installers"]:
        for team in installer["teams"]:
            if team["name"] == name:
                return team
    raise AssertionError(f"Equipa não encontrada: {name}")


def test_calendar_emits_one_row_per_assignment_and_compatibility_without_assignment(api_client, db_session):
    project = _project(db_session, OTHER)
    team_one = _team(db_session, ALFA, "Equipa 1")
    team_two = _team(db_session, ALFA, "Equipa 2")
    project.lifecycle_status = "construcao"
    first = _assignment(db_session, project, team_one, dt.date(2040, 1, 10), dt.date(2040, 1, 12))
    second = _assignment(db_session, project, team_two, dt.date(2040, 1, 20), dt.date(2040, 1, 22))

    response = api_client.get(
        "/api/works/calendar",
        params={"from": "2040-01-01", "to": "2040-01-31"},
        headers=_h(CHEFE),
    )
    assert response.status_code == 200, response.text
    rows = [row for row in response.json()["works"] if row["project_id"] == str(project.id)]
    assert {row["assignment_id"] for row in rows} == {str(first.id), str(second.id)}
    assert {(row["team_name"], row["work_start_date"], row["work_end_date"]) for row in rows} == {
        ("Equipa 1", "2040-01-10", "2040-01-12"),
        ("Equipa 2", "2040-01-20", "2040-01-22"),
    }

    no_team = _project(db_session, "Instalação Sintética E — Sem PM Atribuído")
    no_team.installer_id = team_one.installer_id
    no_team.work_start_date = dt.date(2040, 2, 1)
    no_team.work_end_date = dt.date(2040, 2, 3)
    compatibility = api_client.get(
        "/api/works/calendar",
        params={"from": "2040-02-01", "to": "2040-02-03"},
        headers=_h(CHEFE),
    )
    row = next(item for item in compatibility.json()["works"] if item["project_id"] == str(no_team.id))
    assert row["assignment_id"] is None
    assert row["installer_team_id"] is None and row["team_name"] is None
    assert (row["work_start_date"], row["work_end_date"]) == ("2040-02-01", "2040-02-03")


def test_assignment_conflicts_are_inclusive_and_survive_calendar_filters(api_client, db_session):
    team = _team(db_session, ALFA, "Equipa 1")
    left = _project(db_session, OTHER)
    right = _project(db_session, "Instalação Sintética E — Sem PM Atribuído")
    left.lifecycle_status = right.lifecycle_status = "construcao"
    left_assignment = _assignment(db_session, left, team, dt.date(2041, 4, 10), dt.date(2041, 4, 15))
    right_assignment = _assignment(db_session, right, team, dt.date(2041, 4, 15), dt.date(2041, 4, 20))

    response = api_client.get(
        "/api/works/calendar",
        params={"from": "2041-04-15", "to": "2041-04-15", "team_id": str(team.id)},
        headers=_h(CHEFE),
    )
    rows = {row["assignment_id"]: row for row in response.json()["works"]}
    assert set(rows) == {str(left_assignment.id), str(right_assignment.id)}
    assert all(row["conflict"] is True for row in rows.values())

    filtered = api_client.get(
        "/api/works/calendar",
        params={"from": "2041-04-10", "to": "2041-04-20", "pm_person_id": "00000000-0000-0000-0000-000000000000"},
        headers=_h(CHEFE),
    )
    assert filtered.status_code == 200 and filtered.json()["works"] == []


def test_teams_view_has_free_visible_and_occupied_outside_scope_states(api_client, db_session):
    team_one = _team(db_session, ALFA, "Equipa 1")
    team_two = _team(db_session, ALFA, "Equipa 2")
    free = InstallerTeam(
        installer=team_one.installer,
        name="Equipa Livre Sintética",
        name_key="equipa livre sintetica",
    )
    team_one.installer.teams.append(free)
    db_session.flush()
    visible_project = _project(db_session, OWN)
    visible_project.lifecycle_status = "construcao"
    _assignment(db_session, visible_project, team_one, dt.date(2042, 6, 10), dt.date(2042, 6, 12))
    hidden_project = _project(db_session, LEGACY_PM)
    hidden_project.lifecycle_status = "construcao"
    _assignment(db_session, hidden_project, team_two, dt.date(2042, 6, 10), dt.date(2042, 6, 12))
    db_session.flush()

    chef = _teams(api_client, CHEFE, dt.date(2042, 6, 10), installer_id=str(team_one.installer_id))
    assert chef.status_code == 200
    assert {item["name"] for item in chef.json()["installers"][0]["teams"]} >= {
        "Equipa 1", "Equipa 2", "Equipa Livre Sintética"
    }
    assert _team_json(chef, "Equipa 1")["status"] == "ocupada"
    assert _team_json(chef, "Equipa 1")["free"] is False
    assert _team_json(chef, "Equipa 1")["assignments"][0]["project_name"] == OWN

    pm = _teams(api_client, PM_UM, dt.date(2042, 6, 10), installer_id=str(team_one.installer_id))
    hidden = _team_json(pm, "Equipa 2")
    assert hidden["status"] == "ocupada_noutra_obra"
    assert hidden["free"] is False and hidden["assignments"] == []
    assert LEGACY_PM not in pm.text
    assert _team_json(pm, "Equipa Livre Sintética")["status"] == "livre"


def test_teams_view_counts_active_project_without_lifecycle_as_occupied_but_not_conflict(api_client, db_session):
    team = _team(db_session, ALFA, "Equipa 1")
    projects = {}
    for key, lifecycle_status in (("sem estado", None), ("em preparação", "preparacao"), ("em construção", "construcao")):
        project = Project(
            name=f"Obra sintética {key}",
            lifecycle_status=lifecycle_status,
            is_active=True,
            installer_id=team.installer_id,
        )
        db_session.add(project)
        db_session.flush()
        _assignment(db_session, project, team, dt.date(2045, 3, 10), dt.date(2045, 3, 12))
        projects[key] = project

    response = _teams(api_client, CHEFE, dt.date(2045, 3, 10), installer_id=str(team.installer_id))
    team_body = _team_json(response, "Equipa 1")
    assert team_body["status"] == "ocupada"
    assert team_body["free"] is False

    assignments = {row["project_name"]: row for row in team_body["assignments"]}
    assert assignments[projects["sem estado"].name]["conflict"] is False
    assert assignments[projects["em preparação"].name]["conflict"] is True
    assert assignments[projects["em construção"].name]["conflict"] is True


def test_teams_view_uses_inclusive_days_one_to_sixty_two(api_client):
    ok = _teams(api_client, CHEFE, dt.date(2043, 1, 1), days=62)
    assert ok.status_code == 200
    too_long = _teams(api_client, CHEFE, dt.date(2043, 1, 1), days=63)
    assert too_long.status_code == 422
    zero = _teams(api_client, CHEFE, dt.date(2043, 1, 1), days=0)
    assert zero.status_code == 422


def test_teams_view_query_count_is_constant_with_more_assignments(api_client, db_session):
    team = _team(db_session, ALFA, "Equipa 1")
    projects = [_project(db_session, OTHER)]
    for index in range(8):
        project = Project(
            name=f"Obra equipas sintética {index}",
            lifecycle_status="construcao",
            is_active=True,
            installer_id=team.installer_id,
        )
        db_session.add(project)
        db_session.flush()
        _assignment(db_session, project, team, dt.date(2044, 1, 1), dt.date(2044, 1, 2))
        projects.append(project)

    def count_queries() -> int:
        counter = {"n": 0}

        def listener(*_args, **_kwargs):
            counter["n"] += 1

        event.listen(engine, "before_cursor_execute", listener)
        try:
            response = _teams(api_client, CHEFE, dt.date(2044, 1, 1), installer_id=str(team.installer_id))
            assert response.status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        return counter["n"]

    before = count_queries()
    for project in projects:
        project.notes = "dados sintéticos"
    db_session.flush()
    after = count_queries()
    assert after <= before + 1, (before, after)
