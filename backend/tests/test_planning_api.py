"""Calendário de planeamento ligado a tarefas: validação
projeto<->tarefa, permissões, cancelamento. Ver app/api/routes_planning.py.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.models.calendar import CalendarEvent
from app.models.identity import Role, User, UserRole
from app.models.people import Person
from app.models.project import Project
from app.models.task import Task
from app.models.workflow import WorkflowStage


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _own_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


def _other_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()


def _iso(delta_hours: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=delta_hours)).isoformat()


def _persisted_event_snapshot(db_session, event_id):
    with Session(
        bind=db_session.connection(),
        join_transaction_mode="create_savepoint",
    ) as snapshot_session:
        persisted = snapshot_session.get(CalendarEvent, event_id)
        assert persisted is not None
        return tuple(
            (column.name, getattr(persisted, column.name))
            for column in CalendarEvent.__table__.columns
        )


def _create_pm(db, *, name: str, email: str) -> Person:
    person = Person(display_name=name, email=email, is_active=True)
    db.add(person)
    db.flush()
    user = User(person_id=person.id, email=email, is_active=True)
    db.add(user)
    db.flush()
    role = db.query(Role).filter(Role.code == "project_manager").one()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.commit()
    return person


def _create_project(db, *, name: str, pm: Person) -> Project:
    project = Project(
        name=name,
        pm_person_id=pm.id,
        start_date=dt.date.today(),
        is_active=True,
    )
    db.add(project)
    db.commit()
    return project


def _create_event(
    api_client,
    *,
    project: Project | None,
    email: str,
    title: str,
    category: str = "meeting",
    starts_in_hours: float = 24,
    assigned_to_person_id=None,
    task_id=None,
    process_stage_id=None,
):
    payload = {
        "title": title,
        "starts_at": _iso(starts_in_hours),
        "ends_at": _iso(starts_in_hours + 1),
        "category": category,
        "project_id": str(project.id) if project else None,
    }
    if assigned_to_person_id is not None:
        payload["assigned_to_person_id"] = str(assigned_to_person_id)
    if task_id is not None:
        payload["task_id"] = str(task_id)
    if process_stage_id is not None:
        payload["process_stage_id"] = str(process_stage_id)
    response = api_client.post("/api/planning/events", json=payload, headers=_headers(email))
    assert response.status_code == 201, response.text
    return response.json()


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


def test_pm_can_read_other_calendar_events_without_project_or_process_access(db_session, api_client):
    pm_one = db_session.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    pm_one_user = db_session.query(User).filter(
        User.email == "pm.um.sintetico@example.invalid"
    ).one()
    from app.security.permissions import load_auth_context

    pm_one_context = load_auth_context(db_session, pm_one_user)
    assert pm_one_context.has_permission("calendar.view_all_pm")
    assert not pm_one_context.has_permission("project.view_all")
    own_project = _own_project(db_session)
    pm_two = _create_pm(
        db_session,
        name="PM Teste Dois",
        email="pm.dois.teste@example.invalid",
    )
    other_project = _create_project(db_session, name="Projeto PM Dois Sintético", pm=pm_two)
    task = Task(project_id=other_project.id, title="Tarefa privada de outro projeto")
    db_session.add(task)
    db_session.commit()
    stage = db_session.query(WorkflowStage).first()
    assert stage is not None

    own_event = _create_event(
        api_client,
        project=own_project,
        email="pm.um.sintetico@example.invalid",
        title="Evento do PM Um",
        assigned_to_person_id=pm_one.id,
    )
    foreign_event = _create_event(
        api_client,
        project=other_project,
        email="pm.dois.teste@example.invalid",
        title="Reunião com Cliente e Projeto PM Dois",
        assigned_to_person_id=pm_two.id,
        task_id=task.id,
        process_stage_id=stage.id,
    )
    foreign_projectless_event = _create_event(
        api_client,
        project=None,
        email="chefe.sintetico@example.invalid",
        title="Evento pessoal do PM Dois",
        category="other",
        assigned_to_person_id=pm_two.id,
    )
    foreign_event_snapshot = _persisted_event_snapshot(db_session, foreign_event["id"])
    projectless_event_snapshot = _persisted_event_snapshot(db_session, foreign_projectless_event["id"])
    filtered_out_event = _create_event(
        api_client,
        project=other_project,
        email="pm.dois.teste@example.invalid",
        title="Evento fora do filtro",
        category="work",
        starts_in_hours=48,
        assigned_to_person_id=pm_two.id,
    )

    listing = api_client.get(
        "/api/planning/events",
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert listing.status_code == 200
    listed = {event["id"]: event for event in listing.json()}
    assert own_event["id"] in listed
    assert foreign_event["id"] in listed
    assert foreign_projectless_event["id"] in listed
    assert filtered_out_event["id"] in listed
    assert listed[own_event["id"]]["project_id"] == str(own_project.id)
    assert listed[own_event["id"]]["project_name"] == own_project.name
    assert listed[own_event["id"]]["project_url"] == f"/projects/{own_project.id}"
    assert listed[own_event["id"]]["project_context_hidden"] is False
    assert listed[foreign_event["id"]]["can_manage"] is False
    assert listed[foreign_event["id"]]["project_id"] is None
    assert listed[foreign_event["id"]]["project_name"] is None
    assert listed[foreign_event["id"]]["project_url"] is None
    assert listed[foreign_event["id"]]["project_context_hidden"] is True
    assert listed[foreign_event["id"]]["task_id"] is None
    assert listed[foreign_event["id"]]["task_title"] is None
    assert listed[foreign_event["id"]]["process_stage_id"] is None
    assert listed[foreign_event["id"]]["process_stage_title"] is None
    assert listed[foreign_projectless_event["id"]]["can_manage"] is False
    assert listed[foreign_projectless_event["id"]]["project_context_hidden"] is False
    assert listed[foreign_event["id"]]["title"] == "Reunião com Cliente e Projeto PM Dois"
    assert listed[foreign_event["id"]]["category"] == "meeting"
    assert listed[foreign_event["id"]]["starts_at"] == foreign_event["starts_at"]
    assert listed[foreign_event["id"]]["ends_at"] == foreign_event["ends_at"]
    assert listed[foreign_event["id"]]["assigned_to_person_ids"] == [str(pm_two.id)]
    assert listed[foreign_event["id"]]["assigned_to_display_names"] == [pm_two.display_name]

    existing_view_all = api_client.get(
        "/api/planning/events",
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert existing_view_all.status_code == 200
    existing_view_all_events = {event["id"]: event for event in existing_view_all.json()}
    assert existing_view_all_events[foreign_event["id"]]["can_manage"] is True
    assert existing_view_all_events[foreign_event["id"]]["task_title"] == task.title

    direct = api_client.get(
        f"/api/planning/events/{foreign_event['id']}",
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert direct.status_code == 200
    assert direct.json() == listed[foreign_event["id"]]
    assert api_client.get(
        f"/api/planning/events/{foreign_event['id']}",
        headers=_headers("pm.dois.teste@example.invalid"),
    ).status_code == 200

    filtered = api_client.get(
        "/api/planning/events",
        params={
            "starts_from": _iso(23),
            "starts_to": _iso(26),
            "category": "meeting",
        },
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert filtered.status_code == 200
    filtered_titles = {event["title"] for event in filtered.json()}
    assert filtered_titles == {"Evento do PM Um", "Reunião com Cliente e Projeto PM Dois"}
    assert "Evento fora do filtro" not in filtered_titles
    assert "Evento pessoal do PM Dois" not in filtered_titles
    mine_filtered = api_client.get(
        "/api/planning/events",
        params={
            "starts_from": _iso(23),
            "starts_to": _iso(26),
            "category": "meeting",
            "mine_only": "true",
        },
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert mine_filtered.status_code == 200
    assert {event["title"] for event in mine_filtered.json()} == {"Evento do PM Um"}

    assert api_client.get(
        f"/api/projects/{other_project.id}",
        headers=_headers("pm.um.sintetico@example.invalid"),
    ).status_code == 404
    assert api_client.get(
        f"/api/projects/{other_project.id}/process",
        headers=_headers("pm.um.sintetico@example.invalid"),
    ).status_code == 404
    assert api_client.get(
        f"/api/planning/process-options/{other_project.id}",
        headers=_headers("pm.um.sintetico@example.invalid"),
    ).status_code == 404
    process_events = api_client.get(
        "/api/planning/process-events",
        params={"project_id": str(other_project.id)},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert process_events.status_code == 200
    assert process_events.json() == []

    denied_create = api_client.post(
        "/api/planning/events",
        json={
            "title": "Tentativa de escrita cruzada",
            "starts_at": _iso(72),
            "ends_at": _iso(73),
            "project_id": str(other_project.id),
        },
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert denied_create.status_code == 403
    assert (
        db_session.query(CalendarEvent)
        .filter(CalendarEvent.title == "Tentativa de escrita cruzada")
        .one_or_none()
        is None
    )

    for changes in (
        {"title": "Tentativa de edição cruzada"},
        {"status": "aprovado"},
    ):
        denied_update = api_client.patch(
            f"/api/planning/events/{foreign_event['id']}",
            json=changes,
            headers=_headers("pm.um.sintetico@example.invalid"),
        )
        assert denied_update.status_code == 403
    denied_cancel = api_client.post(
        f"/api/planning/events/{foreign_event['id']}/cancel",
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert denied_cancel.status_code == 403
    assert api_client.patch(
        f"/api/planning/events/{foreign_projectless_event['id']}",
        json={"title": "Tentativa de edição sem projeto"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    ).status_code == 403
    assert api_client.post(
        f"/api/planning/events/{foreign_projectless_event['id']}/cancel",
        headers=_headers("pm.um.sintetico@example.invalid"),
    ).status_code == 403

    assert _persisted_event_snapshot(db_session, foreign_event["id"]) == foreign_event_snapshot
    assert _persisted_event_snapshot(db_session, foreign_projectless_event["id"]) == projectless_event_snapshot

    own_update = api_client.patch(
        f"/api/planning/events/{own_event['id']}",
        json={"title": "Evento próprio atualizado", "status": "aprovado"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert own_update.status_code == 200
    assert own_update.json()["can_manage"] is True
    assert own_update.json()["status"] == "aprovado"
    own_cancel = api_client.post(
        f"/api/planning/events/{own_event['id']}/cancel",
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert own_cancel.status_code == 200
    assert own_cancel.json()["status"] == "cancelado"

    deleted_project = _create_project(
        db_session, name="Projeto PM Dois Removido Sintético", pm=pm_two
    )
    deleted_event = _create_event(
        api_client,
        project=deleted_project,
        email="pm.dois.teste@example.invalid",
        title="Evento de projeto removido",
    )
    deleted_project.deleted_at = dt.datetime.now(dt.timezone.utc)
    db_session.commit()
    assert api_client.get(
        f"/api/planning/events/{deleted_event['id']}",
        headers=_headers("pm.um.sintetico@example.invalid"),
    ).status_code == 404
    after_delete = api_client.get(
        "/api/planning/events", headers=_headers("pm.um.sintetico@example.invalid")
    )
    assert after_delete.status_code == 200
    assert deleted_event["id"] not in {event["id"] for event in after_delete.json()}


def test_support_and_installer_roles_do_not_receive_cross_pm_calendar_read(db_session, api_client):
    pm_two = _create_pm(
        db_session,
        name="PM Teste Dois",
        email="pm.dois.teste@example.invalid",
    )
    other_project = _create_project(db_session, name="Projeto PM Dois Sintético", pm=pm_two)
    foreign_event = _create_event(
        api_client,
        project=other_project,
        email="pm.dois.teste@example.invalid",
        title="Evento do PM Dois",
        assigned_to_person_id=pm_two.id,
    )

    def create_user(email: str, name: str, role_codes: tuple[str, ...]) -> None:
        person = Person(display_name=name, email=email, is_active=True)
        db_session.add(person)
        db_session.flush()
        user = User(person_id=person.id, email=email, is_active=True)
        db_session.add(user)
        db_session.flush()
        for role_code in role_codes:
            role = db_session.query(Role).filter(Role.code == role_code).one()
            db_session.add(UserRole(user_id=user.id, role_id=role.id))
        db_session.commit()

    create_user(
        "installer.teste@example.invalid",
        "Instalador Teste",
        ("instalador_colaborador",),
    )
    create_user(
        "support.installer.teste@example.invalid",
        "Suporte Instalador Teste",
        ("suporte_operacoes", "instalador_colaborador"),
    )

    from app.security.permissions import load_auth_context

    combined_user = db_session.query(User).filter(
        User.email == "support.installer.teste@example.invalid"
    ).one()
    combined_context = load_auth_context(db_session, combined_user)
    assert "calendar.view_all_pm" not in combined_context.permission_codes

    installer_response = api_client.get(
        "/api/planning/events",
        headers=_headers("installer.teste@example.invalid"),
    )
    assert installer_response.status_code == 403
    combined_response = api_client.get(
        "/api/planning/events",
        headers=_headers("support.installer.teste@example.invalid"),
    )
    assert combined_response.status_code == 200
    assert foreign_event["id"] not in {event["id"] for event in combined_response.json()}
    assert api_client.get(
        f"/api/planning/events/{foreign_event['id']}",
        headers=_headers("support.installer.teste@example.invalid"),
    ).status_code == 404
