"""Metas e indicadores — página única, cálculo de progresso e permissões.
Ver app/api/routes_performance.py e app/services/performance.py.
"""
from __future__ import annotations

import datetime as dt

from app.models.people import Person
from app.models.project import Project
from app.models.task import STATUS_DONE, TASK_TYPE_COMISSIONAMENTO, Task


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def test_unauthenticated_request_is_rejected(api_client):
    resp = api_client.get("/api/performance/summary")
    assert resp.status_code == 401


def test_pm_cannot_manage_goals(api_client):
    resp = api_client.post(
        "/api/performance/goals",
        json={"period_type": "year", "year": 2026, "metric": "installations", "target_value": "10"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 403


def test_chefe_can_create_and_update_goal(api_client):
    resp_create = api_client.post(
        "/api/performance/goals",
        json={"period_type": "year", "year": 2026, "metric": "installations", "target_value": "10"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp_create.status_code == 201
    goal_id = resp_create.json()["id"]

    resp_update = api_client.patch(
        f"/api/performance/goals/{goal_id}",
        json={"target_value": "20"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp_update.status_code == 200
    assert resp_update.json()["target_value"] == "20.000"


def test_invalid_period_is_rejected(api_client):
    resp = api_client.post(
        "/api/performance/goals",
        json={"period_type": "quarter", "year": 2026, "quarter": 5, "metric": "installations", "target_value": "10"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 400


def test_goal_progress_reflects_completed_installations(db_session, api_client):
    """O seed já tem 1 comissionamento concluído hoje (cenário "fotos
    pendentes") — esta tarefa acrescenta mais um, para confirmar que o
    realizado aumenta e nunca fica preso ao valor inicial do seed."""
    db = db_session
    project = db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()
    today = dt.date.today()

    baseline = api_client.post(
        "/api/performance/goals",
        json={"period_type": "year", "year": today.year, "metric": "installations", "target_value": "1000"},
        headers=_headers("chefe.sintetico@example.invalid"),
    ).json()
    realized_before = int(float(baseline["realized"]))

    task = (
        db.query(Task)
        .filter(Task.project_id == project.id, Task.task_type == TASK_TYPE_COMISSIONAMENTO)
        .one()
    )
    task.status = STATUS_DONE
    task.completed_at = dt.datetime.now(dt.timezone.utc)
    db.commit()

    resp_create = api_client.post(
        "/api/performance/goals",
        json={
            "period_type": "year",
            "year": today.year,
            "metric": "installations",
            "target_value": str(max(realized_before + 1, 1)),
        },
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp_create.status_code == 201
    body = resp_create.json()
    assert int(float(body["realized"])) == realized_before + 1
    assert body["percent"] == 100.0
    assert body["missing"] == "0.000"


def test_pm_scoped_goal_only_counts_own_installations(db_session, api_client):
    db = db_session
    pm = db.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    today = dt.date.today()

    resp_create = api_client.post(
        "/api/performance/goals",
        json={
            "period_type": "year",
            "year": today.year,
            "metric": "installations",
            "target_value": "5",
            "scope": "pm",
            "pm_person_id": str(pm.id),
        },
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp_create.status_code == 201


def test_portfolio_breakdown_present_in_summary(api_client):
    resp = api_client.get("/api/performance/summary", headers=_headers("chefe.sintetico@example.invalid"))
    assert resp.status_code == 200
    body = resp.json()
    assert "portfolio" in body
    assert body["portfolio"]["not_started"] + body["portfolio"]["in_progress"] + body["portfolio"]["completed"] >= 1
    assert "yearly" in body
    assert len(body["yearly"]) == 5


def test_pm_sees_own_goals_and_company_wide_goals(db_session, api_client):
    pm = db_session.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    api_client.post(
        "/api/performance/goals",
        json={
            "period_type": "year",
            "year": 2030,
            "metric": "installations",
            "target_value": "3",
            "scope": "pm",
            "pm_person_id": str(pm.id),
        },
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    resp = api_client.get(
        "/api/performance/goals?year=2030", headers=_headers("pm.um.sintetico@example.invalid")
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1
