from __future__ import annotations

import datetime as dt

from app.models.people import Person
from app.models.installer import Installer, InstallerTeam
from app.models.project import Project
from app.models.task import Task, STATUS_DONE, STATUS_TODO

CHEFE = {"X-Dev-User-Email": "chefe.sintetico@example.invalid"}
PM = {"X-Dev-User-Email": "pm.um.sintetico@example.invalid"}


def _create_project(
    db_session,
    *,
    name: str,
    lifecycle_status: str | None,
    start_date: dt.date | None = None,
    work_start_date: dt.date | None = None,
    is_active: bool = True,
    pm_email: str = "pm.um.sintetico@example.invalid",
) -> Project:
    pm = db_session.query(Person).filter(Person.email == pm_email).one()
    project = Project(
        name=name,
        pm_person_id=pm.id,
        lifecycle_status=lifecycle_status,
        start_date=start_date,
        work_start_date=work_start_date,
        is_active=is_active,
    )
    db_session.add(project)
    db_session.flush()
    return project


def _assign_installer(db_session, project: Project, *, installer_name: str, team_name: str) -> None:
    installer = Installer(name=installer_name, name_key=installer_name.casefold())
    db_session.add(installer)
    db_session.flush()
    team = InstallerTeam(installer_id=installer.id, name=team_name, name_key=team_name.casefold())
    db_session.add(team)
    db_session.flush()
    project.installer_id = installer.id
    project.installer_team_id = team.id
    db_session.flush()


def test_dashboard_works_returns_only_active_construction_and_preparation_projects(api_client, db_session):
    construction = _create_project(
        db_session,
        name="Obra Sintética em Curso",
        lifecycle_status="construcao",
        work_start_date=dt.date(2026, 11, 5),
    )
    preparation = _create_project(
        db_session,
        name="Obra Sintética em Preparação",
        lifecycle_status="preparacao",
        work_start_date=dt.date(2026, 12, 5),
    )
    inactive = _create_project(
        db_session,
        name="Obra Sintética Inativa",
        lifecycle_status="construcao",
        is_active=False,
    )
    other_status = _create_project(db_session, name="Obra Sintética Concluída", lifecycle_status="construido")
    _assign_installer(db_session, preparation, installer_name="Instalador Sintético", team_name="Equipa Sintética")

    response = api_client.get("/api/dashboard/works", headers=CHEFE)

    assert response.status_code == 200, response.text
    body = response.json()
    construction_ids = {p["id"] for p in body["construction"]}
    preparation_ids = {p["id"] for p in body["preparation"]}
    assert str(construction.id) in construction_ids
    assert str(preparation.id) in preparation_ids
    assert str(inactive.id) not in str(body)
    assert str(other_status.id) not in str(body)
    preparation_entry = next(p for p in body["preparation"] if p["id"] == str(preparation.id))
    assert preparation_entry["installer_display_name"] == "Instalador Sintético"
    assert preparation_entry["team_display_name"] == "Equipa Sintética"


def test_dashboard_works_respects_project_visibility(api_client, db_session):
    own = _create_project(db_session, name="Projeto Sintético Visível", lifecycle_status="construcao")
    hidden = _create_project(
        db_session,
        name="Projeto Sintético Oculto",
        lifecycle_status="preparacao",
        pm_email="financeiro.sintetico@example.invalid",
    )

    response = api_client.get("/api/dashboard/works", headers=PM)

    assert response.status_code == 200, response.text
    body = response.json()
    returned_ids = {p["id"] for p in body["construction"] + body["preparation"]}
    assert str(own.id) in returned_ids
    assert str(hidden.id) not in returned_ids


def test_dashboard_works_orders_preparation_by_expected_start_date(api_client, db_session):
    later = _create_project(
        db_session,
        name="Obra Sintética Mais Tarde",
        lifecycle_status="preparacao",
        start_date=dt.date(2026, 10, 1),
        work_start_date=dt.date(2027, 1, 5),
    )
    earlier = _create_project(
        db_session,
        name="Obra Sintética Mais Cedo",
        lifecycle_status="preparacao",
        start_date=dt.date(2026, 12, 1),
        work_start_date=dt.date(2026, 12, 20),
    )
    undated = _create_project(db_session, name="Obra Sintética Sem Data", lifecycle_status="preparacao")

    response = api_client.get("/api/dashboard/works", headers=CHEFE)

    assert response.status_code == 200, response.text
    wanted_ids = {str(earlier.id), str(later.id), str(undated.id)}
    projects = [p for p in response.json()["preparation"] if p["id"] in wanted_ids]
    assert [p["id"] for p in projects] == [str(earlier.id), str(later.id), str(undated.id)]
    assert projects[0]["expected_start_date"] == "2026-12-20"
    assert projects[1]["expected_start_date"] == "2027-01-05"
    assert projects[2]["expected_start_date"] is None


def test_dashboard_works_includes_next_open_task_not_a_completed_task(api_client, db_session):
    project = _create_project(db_session, name="Obra Sintética com Tarefas", lifecycle_status="preparacao")
    first_due = Task(
        project_id=project.id,
        title="Tarefa sintética mais próxima",
        status=STATUS_TODO,
        due_date=dt.date(2026, 11, 1),
    )
    later_due = Task(
        project_id=project.id,
        title="Tarefa sintética mais tarde",
        status=STATUS_TODO,
        due_date=dt.date(2026, 11, 5),
    )
    completed = Task(
        project_id=project.id,
        title="Tarefa sintética concluída",
        status=STATUS_DONE,
        due_date=dt.date(2026, 10, 1),
    )
    db_session.add_all([first_due, later_due, completed])
    db_session.flush()

    response = api_client.get("/api/dashboard/works", headers=CHEFE)

    assert response.status_code == 200, response.text
    result = next(p for p in response.json()["preparation"] if p["id"] == str(project.id))
    assert result["next_task_title"] == "Tarefa sintética mais próxima"
    assert result["next_task_due_date"] == "2026-11-01"
