"""Regressões para a fonte complementar de realização das metas."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.models.people import Person
from app.models.performance import GoalPeriod
from app.models.project import Project
from app.models.project_data import ProjectLicensingData
from app.models.task import STATUS_DONE, TASK_TYPE_COMISSIONAMENTO, Task
from app.services.performance import compute_goal_progress

GOAL_METRICS = (
    "installations",
    "projects_completed",
    "kwp",
    "power_installed",
    "power_delivered",
)
COUNT_METRICS = {"installations", "projects_completed"}


def _goal(*, metric: str, year: int, pm_person_id=None) -> GoalPeriod:
    return GoalPeriod(
        period_type="year",
        year=year,
        metric=metric,
        target_value=Decimal("1000"),
        pm_person_id=pm_person_id,
    )


def _realized(db_session, *, metric: str, year: int, pm_person_id=None) -> Decimal:
    return compute_goal_progress(
        db_session,
        _goal(metric=metric, year=year, pm_person_id=pm_person_id),
    ).realized


def _project(db_session, *, name: str, lifecycle_status: str, power_kwp: float, pm_person_id=None) -> Project:
    project = Project(
        name=name,
        lifecycle_status=lifecycle_status,
        power_kwp=power_kwp,
        pm_person_id=pm_person_id,
    )
    db_session.add(project)
    db_session.flush()
    return project


def _commissioning_task(db_session, *, project: Project, completed_on: dt.date) -> None:
    db_session.add(
        Task(
            project_id=project.id,
            title="Comissionamento sintético",
            task_type=TASK_TYPE_COMISSIONAMENTO,
            status=STATUS_DONE,
            completed_at=dt.datetime.combine(completed_on, dt.time(12), tzinfo=dt.timezone.utc),
        )
    )
    db_session.flush()


def test_goal_metrics_include_both_final_lifecycle_states_outside_selected_period(db_session):
    before = {metric: _realized(db_session, metric=metric, year=1999) for metric in GOAL_METRICS}

    _project(
        db_session,
        name="Projeto Sintético Entregue Fora do Período",
        lifecycle_status="entregue_cliente",
        power_kwp=4.5,
    )
    _project(
        db_session,
        name="Projeto Sintético Certificado Fora do Período",
        lifecycle_status="certificado_final",
        power_kwp=6.25,
    )

    after = {metric: _realized(db_session, metric=metric, year=1999) for metric in GOAL_METRICS}
    for metric in GOAL_METRICS:
        expected_delta = Decimal("2") if metric in COUNT_METRICS else Decimal("10.75")
        assert after[metric] - before[metric] == expected_delta


def test_goal_metrics_union_deduplicates_a_final_project_with_completed_commissioning(db_session):
    before = {metric: _realized(db_session, metric=metric, year=2026) for metric in GOAL_METRICS}

    project = _project(
        db_session,
        name="Projeto Sintético Final Com Comissionamento",
        lifecycle_status="certificado_final",
        power_kwp=12.75,
    )
    _commissioning_task(db_session, project=project, completed_on=dt.date(2026, 3, 15))

    after = {metric: _realized(db_session, metric=metric, year=2026) for metric in GOAL_METRICS}
    for metric in GOAL_METRICS:
        expected_delta = Decimal("1") if metric in COUNT_METRICS else Decimal("12.75")
        assert after[metric] - before[metric] == expected_delta


def test_goal_union_filters_final_and_date_sources_by_pm(db_session):
    pm_one = db_session.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    pm_two = db_session.query(Person).filter(Person.display_name == "PM Sintético Legado Dois").one()
    year = 2040

    before = {
        pm_one.id: {metric: _realized(db_session, metric=metric, year=year, pm_person_id=pm_one.id) for metric in GOAL_METRICS},
        pm_two.id: {metric: _realized(db_session, metric=metric, year=year, pm_person_id=pm_two.id) for metric in GOAL_METRICS},
    }

    _project(
        db_session,
        name="Projeto Sintético Final PM Um",
        lifecycle_status="entregue_cliente",
        power_kwp=4.5,
        pm_person_id=pm_one.id,
    )
    pm_one_task_project = _project(
        db_session,
        name="Projeto Sintético Datado PM Um",
        lifecycle_status="construcao",
        power_kwp=6.0,
        pm_person_id=pm_one.id,
    )
    _commissioning_task(db_session, project=pm_one_task_project, completed_on=dt.date(year, 6, 1))

    _project(
        db_session,
        name="Projeto Sintético Final PM Dois",
        lifecycle_status="certificado_final",
        power_kwp=7.5,
        pm_person_id=pm_two.id,
    )
    pm_two_task_project = _project(
        db_session,
        name="Projeto Sintético Datado PM Dois",
        lifecycle_status="construcao",
        power_kwp=8.0,
        pm_person_id=pm_two.id,
    )
    _commissioning_task(db_session, project=pm_two_task_project, completed_on=dt.date(year, 6, 1))

    after = {
        pm_one.id: {metric: _realized(db_session, metric=metric, year=year, pm_person_id=pm_one.id) for metric in GOAL_METRICS},
        pm_two.id: {metric: _realized(db_session, metric=metric, year=year, pm_person_id=pm_two.id) for metric in GOAL_METRICS},
    }
    for pm_id, expected_count, expected_power in (
        (pm_one.id, Decimal("2"), Decimal("10.5")),
        (pm_two.id, Decimal("2"), Decimal("15.5")),
    ):
        for metric in GOAL_METRICS:
            expected_delta = expected_count if metric in COUNT_METRICS else expected_power
            assert after[pm_id][metric] - before[pm_id][metric] == expected_delta


def test_projects_certified_remains_certificate_date_based(db_session):
    year = 2041
    before = _realized(db_session, metric="projects_certified", year=year)

    outside_period = _project(
        db_session,
        name="Projeto Sintético Certificado Com Data Antiga",
        lifecycle_status="certificado_final",
        power_kwp=3.0,
    )
    db_session.add(
        ProjectLicensingData(
            project_id=outside_period.id,
            certificate_date=dt.date(year - 1, 12, 31),
        )
    )
    inside_period = _project(
        db_session,
        name="Projeto Sintético Com Certificado No Período",
        lifecycle_status="construcao",
        power_kwp=3.0,
    )
    db_session.add(ProjectLicensingData(project_id=inside_period.id, certificate_date=dt.date(year, 1, 2)))
    db_session.flush()

    after = _realized(db_session, metric="projects_certified", year=year)
    assert after - before == Decimal("1")
