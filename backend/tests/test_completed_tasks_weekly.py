"""Item 12 — tarefas e subtarefas concluídas por semana ISO e PM."""
from __future__ import annotations

import datetime as dt

from app.models.identity import User
from app.models.people import Person
from app.models.project import Project, ProjectSubtaskProgress
from app.models.task import STATUS_DONE, STATUS_TODO, Task
from app.models.workflow import WorkflowSubtask

CHEFE = "chefe.sintetico@example.invalid"
PM_UM = "pm.um.sintetico@example.invalid"
PM_LEGADO = "pm.legado.dois.sintetico@example.invalid"


def _headers(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _person(db, display_name: str) -> Person:
    return db.query(Person).filter(Person.display_name == display_name).one()


def _project(db, name: str, pm: Person, *, is_active: bool = True) -> Project:
    project = Project(name=name, pm_person_id=pm.id, is_active=is_active)
    db.add(project)
    db.flush()
    return project


def _task(db, project: Project, title: str, completed_at: dt.datetime | None, *, status: str = STATUS_DONE) -> Task:
    task = Task(project_id=project.id, title=title, status=status, completed_at=completed_at)
    db.add(task)
    db.flush()
    return task


def _weeks(response):
    return {(row["iso_year"], row["iso_week"]): row for row in response.json()}


def test_completed_tasks_are_grouped_by_iso_week_and_project_pm(db_session, api_client):
    pm_one = _person(db_session, "PM Sintético Um")
    pm_two = _person(db_session, "PM Sintético Legado Dois")
    project_one = _project(db_session, "Projeto Sintético Semanal Um", pm_one)
    project_two = _project(db_session, "Projeto Sintético Semanal Dois", pm_two)
    first_week = dt.datetime(2026, 6, 2, 10, tzinfo=dt.timezone.utc)
    second_week = dt.datetime(2026, 6, 9, 10, tzinfo=dt.timezone.utc)
    task_one = _task(db_session, project_one, "Tarefa semanal um", first_week)
    task_two = _task(db_session, project_one, "Tarefa semanal dois", first_week + dt.timedelta(hours=1))
    _task(db_session, project_two, "Tarefa semanal três", first_week + dt.timedelta(hours=2))
    task_four = _task(db_session, project_one, "Tarefa semanal quatro", second_week)

    response = api_client.get(
        "/api/performance/completed-tasks-weekly?from=2026-06-01&to=2026-06-14",
        headers=_headers(CHEFE),
    )

    assert response.status_code == 200, response.text
    weeks = _weeks(response)
    first = weeks[(2026, 23)]
    second = weeks[(2026, 24)]
    by_pm = {row["pm_display_name"]: row for row in first["pms"]}
    assert by_pm["PM Sintético Um"]["task_count"] == 2
    assert by_pm["PM Sintético Um"]["subtask_count"] == 0
    assert {task["id"] for task in by_pm["PM Sintético Um"]["tasks"]} == {str(task_one.id), str(task_two.id)}
    assert by_pm["PM Sintético Legado Dois"]["task_count"] == 1
    assert by_pm["PM Sintético Legado Dois"]["tasks"][0]["project_name"] == project_two.name
    second_pm = {row["pm_display_name"]: row for row in second["pms"]}["PM Sintético Um"]
    assert second_pm["task_count"] == 1
    assert second_pm["tasks"][0]["id"] == str(task_four.id)


def test_week_boundary_uses_europe_lisbon_date_before_grouping(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    project = _project(db_session, "Projeto Sintético Fronteira Lisboa", pm)
    sunday_local = _task(db_session, project, "Domingo em Lisboa", dt.datetime(2026, 6, 7, 22, 30, tzinfo=dt.timezone.utc))
    monday_local = _task(db_session, project, "Segunda em Lisboa", dt.datetime(2026, 6, 7, 23, 30, tzinfo=dt.timezone.utc))

    response = api_client.get(
        "/api/performance/completed-tasks-weekly?from=2026-06-07&to=2026-06-08",
        headers=_headers(CHEFE),
    )

    assert response.status_code == 200, response.text
    weeks = _weeks(response)
    assert weeks[(2026, 23)]["week_start"] == "2026-06-01"
    assert [task["id"] for task in weeks[(2026, 23)]["pms"][0]["tasks"]] == [str(sunday_local.id)]
    assert weeks[(2026, 24)]["week_start"] == "2026-06-08"
    assert [task["id"] for task in weeks[(2026, 24)]["pms"][0]["tasks"]] == [str(monday_local.id)]


def test_weekly_result_intersects_project_and_task_visibility_and_excludes_inactive_projects(db_session, api_client):
    own_pm = _person(db_session, "PM Sintético Um")
    other_pm = _person(db_session, "PM Sintético Legado Dois")
    own = _project(db_session, "Projeto Sintético Visível", own_pm)
    other = _project(db_session, "Projeto Sintético Fora do Âmbito", other_pm)
    inactive = _project(db_session, "Projeto Sintético Inativo", own_pm, is_active=False)
    completed_at = dt.datetime(2026, 7, 1, 10, tzinfo=dt.timezone.utc)
    _task(db_session, own, "Tarefa visível", completed_at)
    _task(db_session, other, "Tarefa fora do âmbito", completed_at)
    _task(db_session, inactive, "Tarefa de projeto inativo", completed_at)

    response = api_client.get(
        "/api/performance/completed-tasks-weekly?from=2026-07-01&to=2026-07-07",
        headers=_headers(PM_UM),
    )

    assert response.status_code == 200, response.text
    rows = response.json()[0]["pms"]
    assert len(rows) == 1
    assert rows[0]["pm_display_name"] == "PM Sintético Um"
    assert [task["title"] for task in rows[0]["tasks"]] == ["Tarefa visível"]

    chefe_response = api_client.get(
        "/api/performance/completed-tasks-weekly?from=2026-07-01&to=2026-07-07",
        headers=_headers(CHEFE),
    )
    assert chefe_response.status_code == 200, chefe_response.text
    titles = [task["title"] for pm in chefe_response.json()[0]["pms"] for task in pm["tasks"]]
    assert set(titles) == {"Tarefa visível", "Tarefa fora do âmbito"}


def test_weekly_counts_process_subtasks_separately_only_when_done_at_exists(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    project = _project(db_session, "Projeto Sintético Subtarefas Semanais", pm)
    subtasks = (
        db_session.query(WorkflowSubtask)
        .filter(WorkflowSubtask.stage_id == db_session.query(WorkflowSubtask).filter(WorkflowSubtask.code == "etapa-02.0").one().stage_id)
        .order_by(WorkflowSubtask.sort_order)
        .all()
    )
    db_session.add(
        ProjectSubtaskProgress(
            project_id=project.id,
            subtask_id=subtasks[0].id,
            done=True,
            done_at=dt.datetime(2026, 8, 4, 10, tzinfo=dt.timezone.utc),
        )
    )
    db_session.add(ProjectSubtaskProgress(project_id=project.id, subtask_id=subtasks[1].id, done=True))
    db_session.flush()

    response = api_client.get(
        "/api/performance/completed-tasks-weekly?from=2026-08-03&to=2026-08-09",
        headers=_headers(CHEFE),
    )

    assert response.status_code == 200, response.text
    row = response.json()[0]["pms"][0]
    assert row["task_count"] == 0
    assert row["subtask_count"] == 1
    assert row["tasks"] == []


def test_tasks_without_completion_date_never_count(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    project = _project(db_session, "Projeto Sintético Sem Data", pm)
    _task(db_session, project, "Tarefa feita sem data", None)
    _task(db_session, project, "Tarefa aberta com data", dt.datetime(2026, 9, 2, tzinfo=dt.timezone.utc), status=STATUS_TODO)

    response = api_client.get(
        "/api/performance/completed-tasks-weekly?from=2026-09-01&to=2026-09-07",
        headers=_headers(CHEFE),
    )

    assert response.status_code == 200, response.text
    assert response.json()[0]["pms"] == []


def test_weekly_endpoint_requires_performance_view_permission(db_session, api_client):
    person = Person(display_name="Pessoa Sintética Sem Desempenho", is_active=True)
    db_session.add(person)
    db_session.flush()
    db_session.add(User(person_id=person.id, email="sem.desempenho.sintetico@example.invalid", is_active=True))
    db_session.flush()

    response = api_client.get(
        "/api/performance/completed-tasks-weekly?from=2026-01-01&to=2026-01-07",
        headers=_headers("sem.desempenho.sintetico@example.invalid"),
    )

    assert response.status_code == 403
