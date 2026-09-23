"""Calendário de planeamento ligado a tarefas: validação
projeto<->tarefa, permissões, cancelamento. Ver app/api/routes_planning.py.
"""
from __future__ import annotations

import datetime as dt

from app.models.project import Project
from app.models.task import Task


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _own_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


def _other_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()


def _iso(delta_hours: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=delta_hours)).isoformat()


def test_unauthenticated_request_is_rejected(api_client):
    resp = api_client.get("/api/planning/events")
    assert resp.status_code == 401


def test_pm_can_create_event_on_own_project(db_session, api_client):
    project = _own_project(db_session)
    resp = api_client.post(
        "/api/planning/events",
        json={"title": "Visita técnica sintética", "starts_at": _iso(24), "ends_at": _iso(25), "project_id": str(project.id)},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "rascunho"


def test_pm_cannot_create_event_on_project_they_do_not_manage(db_session, api_client):
    other = _other_project(db_session)
    resp = api_client.post(
        "/api/planning/events",
        json={"title": "Tentativa indevida", "starts_at": _iso(24), "ends_at": _iso(25), "project_id": str(other.id)},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 403


def test_end_before_start_is_rejected(db_session, api_client):
    project = _own_project(db_session)
    resp = api_client.post(
        "/api/planning/events",
        json={"title": "Evento inválido", "starts_at": _iso(25), "ends_at": _iso(24), "project_id": str(project.id)},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 400


def test_task_from_different_project_is_rejected(db_session, api_client):
    own = _own_project(db_session)
    other = _other_project(db_session)
    task_of_other_project = Task(project_id=other.id, title="Tarefa de outro projeto")
    db_session.add(task_of_other_project)
    db_session.commit()

    resp = api_client.post(
        "/api/planning/events",
        json={
            "title": "Evento com tarefa incoerente",
            "starts_at": _iso(24),
            "ends_at": _iso(25),
            "project_id": str(own.id),
            "task_id": str(task_of_other_project.id),
        },
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 400


def test_task_from_same_project_is_accepted_and_shown(db_session, api_client):
    project = _own_project(db_session)
    task = Task(project_id=project.id, title="Tarefa ligada ao evento")
    db_session.add(task)
    db_session.commit()

    resp = api_client.post(
        "/api/planning/events",
        json={
            "title": "Evento ligado a tarefa",
            "starts_at": _iso(24),
            "ends_at": _iso(25),
            "project_id": str(project.id),
            "task_id": str(task.id),
        },
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 201
    assert resp.json()["task_id"] == str(task.id)
    assert resp.json()["task_title"] == "Tarefa ligada ao evento"


def test_mine_only_filter(db_session, api_client):
    project = _own_project(db_session)
    from app.models.people import Person

    pm = db_session.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    chefe = db_session.query(Person).filter(Person.display_name == "Chefe Sintético").one()

    api_client.post(
        "/api/planning/events",
        json={
            "title": "Evento do PM",
            "starts_at": _iso(24),
            "ends_at": _iso(25),
            "project_id": str(project.id),
            "assigned_to_person_id": str(pm.id),
        },
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    api_client.post(
        "/api/planning/events",
        json={
            "title": "Evento do Chefe",
            "starts_at": _iso(24),
            "ends_at": _iso(25),
            "project_id": str(project.id),
            "assigned_to_person_id": str(chefe.id),
        },
        headers=_headers("chefe.sintetico@example.invalid"),
    )

    resp = api_client.get(
        "/api/planning/events?mine_only=true", headers=_headers("pm.um.sintetico@example.invalid")
    )
    assert resp.status_code == 200
    titles = {e["title"] for e in resp.json()}
    assert "Evento do PM" in titles
    assert "Evento do Chefe" not in titles


def test_cancel_event(db_session, api_client):
    project = _own_project(db_session)
    resp_create = api_client.post(
        "/api/planning/events",
        json={"title": "Evento a cancelar", "starts_at": _iso(24), "ends_at": _iso(25), "project_id": str(project.id)},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    event_id = resp_create.json()["id"]

    resp_cancel = api_client.post(
        f"/api/planning/events/{event_id}/cancel", headers=_headers("chefe.sintetico@example.invalid")
    )
    assert resp_cancel.status_code == 200
    assert resp_cancel.json()["status"] == "cancelado"


def test_comercial_cannot_manage_events(db_session, api_client):
    project = _own_project(db_session)
    resp = api_client.post(
        "/api/planning/events",
        json={"title": "Tentativa indevida", "starts_at": _iso(24), "ends_at": _iso(25), "project_id": str(project.id)},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert resp.status_code == 403
