"""Contrato backend do planeamento pedido no feedback de calendário.

Estes testes exercitam a API contra as entidades reais do seed sintético: não
criam uma implementação paralela nem aceitam tarefas artificiais para
representar etapas do Processo.
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

from app.models.calendar import CalendarEvent
from app.models.identity import User
from app.models.people import Person
from app.models.project import Project
from app.models.workflow import WorkflowStage
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext
from app.services.planning import get_planning_preferences

CHEFE = "chefe.sintetico@example.invalid"
PM_UM = "pm.um.sintetico@example.invalid"
COMERCIAL = "comercial.sintetico@example.invalid"


def _headers(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _project(db, name: str = "Instalação Sintética de Demonstração") -> Project:
    return db.query(Project).filter(Project.name == name).one()


def _person(db, name: str) -> Person:
    return db.query(Person).filter(Person.display_name == name).one()


def _iso(hours: int = 24) -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)).isoformat()


def _utc(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    return parsed.astimezone(dt.timezone.utc)


def test_calendar_event_instants_are_utc_aware_across_sqlite_create_patch_and_filters(
    db_session, api_client
):
    project = _project(db_session)
    created = api_client.post(
        "/api/planning/events",
        json={
            "title": "Evento DST de teste",
            "starts_at": "2026-10-25T00:30:00+01:00",
            "ends_at": "2026-10-25T02:00:00+00:00",
            "project_id": str(project.id),
        },
        headers=_headers(CHEFE),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert _utc(body["starts_at"]) == dt.datetime(2026, 10, 24, 23, 30, tzinfo=dt.timezone.utc)
    assert _utc(body["ends_at"]) == dt.datetime(2026, 10, 25, 2, tzinfo=dt.timezone.utc)
    assert dt.datetime.fromisoformat(body["starts_at"]).tzinfo is not None
    assert dt.datetime.fromisoformat(body["ends_at"]).tzinfo is not None

    stored = db_session.get(CalendarEvent, uuid.UUID(body["id"]))
    assert stored is not None
    expected_start = dt.datetime(2026, 10, 24, 23, 30, tzinfo=dt.timezone.utc)
    expected_end = dt.datetime(2026, 10, 25, 2, tzinfo=dt.timezone.utc)
    if db_session.bind.dialect.name == "sqlite":
        assert stored.starts_at == expected_start.replace(tzinfo=None)
        assert stored.ends_at == expected_end.replace(tzinfo=None)
    else:
        assert stored.starts_at.astimezone(dt.timezone.utc) == expected_start
        assert stored.ends_at.astimezone(dt.timezone.utc) == expected_end

    patched = api_client.patch(
        f"/api/planning/events/{body['id']}",
        json={
            "starts_at": "2026-01-15T10:00:00-05:00",
            "ends_at": "2026-01-15T12:00:00-05:00",
        },
        headers=_headers(CHEFE),
    )
    assert patched.status_code == 200, patched.text
    assert _utc(patched.json()["starts_at"]) == dt.datetime(2026, 1, 15, 15, tzinfo=dt.timezone.utc)
    assert _utc(patched.json()["ends_at"]) == dt.datetime(2026, 1, 15, 17, tzinfo=dt.timezone.utc)

    readback = api_client.get(
        f"/api/planning/events/{body['id']}",
        headers=_headers(CHEFE),
    )
    assert readback.status_code == 200, readback.text
    assert _utc(readback.json()["starts_at"]) == dt.datetime(2026, 1, 15, 15, tzinfo=dt.timezone.utc)
    assert _utc(readback.json()["ends_at"]) == dt.datetime(2026, 1, 15, 17, tzinfo=dt.timezone.utc)

    crossing_midnight = api_client.post(
        "/api/planning/events",
        json={
            "title": "Evento antes do limite UTC",
            "starts_at": "2026-10-25T00:30:00+01:00",
            "ends_at": "2026-10-25T01:30:00+01:00",
            "project_id": str(project.id),
        },
        headers=_headers(CHEFE),
    )
    assert crossing_midnight.status_code == 201, crossing_midnight.text
    filtered = api_client.get(
        "/api/planning/events",
        params={
            "project_id": str(project.id),
            "starts_from": "2026-10-25T00:45:00+00:00",
            "starts_to": "2026-10-25T01:00:00+00:00",
        },
        headers=_headers(CHEFE),
    )
    assert filtered.status_code == 200, filtered.text
    assert all(item["title"] != "Evento antes do limite UTC" for item in filtered.json())


@pytest.mark.parametrize(
    ("start", "end", "start_offset", "end_offset", "duration_hours"),
    [
        (dt.date(2026, 1, 15), dt.date(2026, 1, 15), 0, 0, 24),
        (dt.date(2026, 7, 15), dt.date(2026, 7, 15), 1, 1, 24),
        (dt.date(2026, 3, 29), dt.date(2026, 3, 29), 0, 1, 23),
        (dt.date(2026, 10, 25), dt.date(2026, 10, 25), 1, 0, 25),
    ],
)
def test_process_date_only_ranges_keep_lisbon_dst_offsets(
    start: dt.date,
    end: dt.date,
    start_offset: int,
    end_offset: int,
    duration_hours: int,
):
    from app.services.planning import _lisbon_day_range

    starts_at, ends_at = _lisbon_day_range(start, end)
    assert starts_at.utcoffset() == dt.timedelta(hours=start_offset)
    assert ends_at.utcoffset() == dt.timedelta(hours=end_offset)
    assert ends_at.astimezone(dt.timezone.utc) - starts_at.astimezone(dt.timezone.utc) == dt.timedelta(
        hours=duration_hours
    )


def test_planning_preferences_default_are_per_user_and_invalid_values_are_rejected(api_client, db_session):
    default = api_client.get("/api/me/planning-preferences", headers=_headers(PM_UM))
    assert default.status_code == 200
    assert default.json() == {"view": "month", "hide_weekends": False}

    changed = api_client.patch(
        "/api/me/planning-preferences",
        json={"view": "week", "hide_weekends": True},
        headers=_headers(PM_UM),
    )
    assert changed.status_code == 200
    assert changed.json() == {"view": "week", "hide_weekends": True}

    other_user = api_client.get("/api/me/planning-preferences", headers=_headers(CHEFE))
    assert other_user.status_code == 200
    assert other_user.json() == {"view": "month", "hide_weekends": False}

    invalid = api_client.patch(
        "/api/me/planning-preferences",
        json={"view": "quarter"},
        headers=_headers(PM_UM),
    )
    assert invalid.status_code == 422


def test_planning_preferences_read_propagates_db_error_without_rollback(monkeypatch, db_session):
    user = db_session.query(User).filter(User.email == PM_UM).one()
    ctx = AuthContext(
        user=user,
        person_id=user.person_id,
        role_codes=frozenset(),
        permission_codes=frozenset(),
    )
    pending_project = _project(db_session)
    pending_project.name = "alteração pendente do chamador"
    rollback_calls: list[bool] = []

    monkeypatch.setattr(db_session, "rollback", lambda: rollback_calls.append(True))

    def fail_query(*args, **kwargs):
        raise OperationalError(
            "SELECT ... FROM planning_preferences",
            {},
            RuntimeError("no such table: planning_preferences"),
        )

    monkeypatch.setattr(db_session, "query", fail_query)

    with pytest.raises(OperationalError):
        get_planning_preferences(db_session, ctx)

    assert rollback_calls == []
    assert pending_project in db_session.dirty
    assert pending_project.name == "alteração pendente do chamador"


def test_planning_preferences_schema_failure_is_sanitized_at_api_boundary(monkeypatch, api_client):
    from app.api import routes_planning

    def fail_preferences(*args, **kwargs):
        raise OperationalError(
            "SELECT ... FROM planning_preferences",
            {},
            RuntimeError("no such table: planning_preferences"),
        )

    monkeypatch.setattr(routes_planning, "get_planning_preferences", fail_preferences)
    response = api_client.get(
        "/api/me/planning-preferences",
        headers=_headers(PM_UM),
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Não foi possível carregar as preferências de planeamento."
    }
    assert "planning_preferences" not in response.text


def test_event_category_catalog_requires_authenticated_calendar_view(api_client, db_session):
    unauthenticated = api_client.get("/api/planning/event-categories")
    assert unauthenticated.status_code == 401

    authorized = api_client.get(
        "/api/planning/event-categories",
        headers=_headers(CHEFE),
    )
    assert authorized.status_code == 200
    assert len(authorized.json()) == 7

    from app.main import app

    user = db_session.query(User).filter(User.email == COMERCIAL).one()
    no_calendar_view = AuthContext(
        user=user,
        person_id=user.person_id,
        role_codes=frozenset({"test_without_calendar_view"}),
        permission_codes=frozenset(),
    )
    app.dependency_overrides[get_auth_context] = lambda: no_calendar_view
    try:
        denied = api_client.get("/api/planning/event-categories")
    finally:
        app.dependency_overrides.pop(get_auth_context, None)

    assert denied.status_code == 403


def test_existing_out_of_scope_event_is_hidden_on_get_but_denied_on_mutation(db_session, api_client):
    support = Person(display_name="Pessoa suporte planeamento")
    delegated_pm = Person(display_name="PM delegado planeamento")
    outside_pm = Person(display_name="PM externo planeamento")
    db_session.add_all([support, delegated_pm, outside_pm])
    db_session.flush()
    outside_project = Project(
        name="Projeto externo planeamento",
        pm_person_id=outside_pm.id,
        is_active=True,
    )
    outside_event = CalendarEvent(
        title="Evento fora do âmbito",
        project=outside_project,
        starts_at=dt.datetime.now(dt.timezone.utc),
        ends_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
        status="rascunho",
    )
    db_session.add(outside_event)
    db_session.flush()

    from app.main import app

    ctx = AuthContext(
        user=User(person_id=support.id, email="support-planning@example.invalid"),
        person_id=support.id,
        role_codes=frozenset({"test_delegated_support"}),
        permission_codes=frozenset(
            {
                "calendar.view",
                "calendar.manage",
                "project.view_delegated",
                "project.edit_own_progress",
            }
        ),
        delegating_pm_ids=frozenset({delegated_pm.id}),
    )
    app.dependency_overrides[get_auth_context] = lambda: ctx
    try:
        detail = api_client.get(f"/api/planning/events/{outside_event.id}")
        update = api_client.patch(
            f"/api/planning/events/{outside_event.id}",
            json={"title": "Tentativa de alteração"},
        )
        cancel = api_client.post(f"/api/planning/events/{outside_event.id}/cancel")
    finally:
        app.dependency_overrides.pop(get_auth_context, None)

    assert detail.status_code == 404
    assert update.status_code == 403
    assert cancel.status_code == 403
    db_session.refresh(outside_event)
    assert outside_event.title == "Evento fora do âmbito"
    assert outside_event.status == "rascunho"


def test_calendar_event_categories_and_multiple_assignees_are_scoped_and_compatible(db_session, api_client):
    project = _project(db_session)
    chefe = _person(db_session, "Chefe Sintético")
    pm = _person(db_session, "PM Sintético Um")

    created = api_client.post(
        "/api/planning/events",
        json={
            "title": "Reunião de planeamento",
            "category": "meeting",
            "starts_at": _iso(),
            "ends_at": _iso(25),
            "project_id": str(project.id),
            # O primário legado é o Chefe; o PM adicional tem de aparecer no mine.
            "assigned_to_person_id": str(chefe.id),
            "assigned_to_person_ids": [str(chefe.id), str(pm.id), str(chefe.id)],
        },
        headers=_headers(CHEFE),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["category"] == "meeting"
    assert body["assigned_to_person_id"] == str(chefe.id)
    assert body["assigned_to_person_ids"] == [str(chefe.id), str(pm.id)]
    assert body["assigned_to_display_names"] == ["Chefe Sintético", "PM Sintético Um"]
    assert body["source"] == "manual"
    assert body["can_manage"] is True

    mine = api_client.get(
        "/api/planning/events",
        params={"mine_only": "true", "category": "meeting"},
        headers=_headers(PM_UM),
    )
    assert mine.status_code == 200
    assert {event["id"] for event in mine.json()} == {body["id"]}

    updated = api_client.patch(
        f"/api/planning/events/{body['id']}",
        json={"title": "Reunião atualizada"},
        headers=_headers(CHEFE),
    )
    assert updated.status_code == 200
    assert updated.json()["assigned_to_person_ids"] == [str(chefe.id), str(pm.id)]

    cleared = api_client.patch(
        f"/api/planning/events/{body['id']}",
        json={"assigned_to_person_ids": []},
        headers=_headers(CHEFE),
    )
    assert cleared.status_code == 200
    assert cleared.json()["assigned_to_person_id"] is None
    assert cleared.json()["assigned_to_person_ids"] == []

    null_list = api_client.patch(
        f"/api/planning/events/{body['id']}",
        json={"assigned_to_person_ids": None},
        headers=_headers(CHEFE),
    )
    assert null_list.status_code == 422


def test_invalid_assignee_is_422_and_does_not_create_event(db_session, api_client):
    project = _project(db_session)
    before = db_session.query(Project).count()
    missing_person = str(uuid.uuid4())
    response = api_client.post(
        "/api/planning/events",
        json={
            "title": "Evento inválido",
            "category": "pending",
            "starts_at": _iso(),
            "ends_at": _iso(25),
            "project_id": str(project.id),
            "assigned_to_person_ids": [missing_person],
        },
        headers=_headers(CHEFE),
    )
    assert response.status_code == 422
    assert db_session.query(Project).count() == before
    assert not any(event.title == "Evento inválido" for event in project.__dict__.get("events", []))


def test_process_event_projection_is_read_only_stable_and_overlaps_requested_range(db_session, api_client):
    project = _project(db_session)
    project.start_date = dt.date(2026, 3, 2)
    db_session.commit()

    process = api_client.get(f"/api/projects/{project.id}/process", headers=_headers(CHEFE))
    assert process.status_code == 200
    stage = next(
        stage
        for phase in process.json()["phases"]
        for stage in phase["stages"]
        if stage["planned_start"] and stage["planned_end"]
    )

    projected = api_client.get(
        "/api/planning/process-events",
        params={
            "project_id": str(project.id),
            "starts_from": f"{stage['planned_start']}T00:00:00+00:00",
            "starts_to": f"{stage['planned_end']}T23:59:59+00:00",
        },
        headers=_headers(PM_UM),
    )
    assert projected.status_code == 200, projected.text
    events = projected.json()
    event = next(item for item in events if item["process_stage_id"] == stage["id"])
    assert event["source"] == "process"
    assert event["source_id"]
    assert event["can_manage"] is False
    assert event["project_url"] == f"/projects/{project.id}?tab=processo"
    assert event["project_id"] == str(project.id)
    assert event["responsible_person_ids"]
    assert all("email" not in key for key in event)
    assert all(item["process_subtask_id"] is None for item in events)

    # A janela que começa depois do início mas ainda intersecta a etapa tem de
    # manter o evento; filtrar apenas pelo starts_at perderia este caso.
    start = dt.datetime.fromisoformat(event["starts_at"])
    end = dt.datetime.fromisoformat(event["ends_at"])
    overlap = api_client.get(
        "/api/planning/process-events",
        params={
            "project_id": str(project.id),
            "starts_from": (start + dt.timedelta(hours=1)).isoformat(),
            "starts_to": (end - dt.timedelta(hours=1)).isoformat(),
        },
        headers=_headers(PM_UM),
    )
    assert overlap.status_code == 200
    assert any(item["source_id"] == event["source_id"] for item in overlap.json())

    # O ID da projeção não é um CalendarEvent persistido e não pode ser editado
    # nem cancelado através das rotas de escrita.
    assert api_client.patch(
        f"/api/planning/events/{event['id']}",
        json={"title": "não editar"},
        headers=_headers(CHEFE),
    ).status_code == 404
    assert api_client.post(
        f"/api/planning/events/{event['id']}/cancel",
        headers=_headers(CHEFE),
    ).status_code == 404


def test_manual_event_can_reference_process_stage_and_invalid_stage_is_atomic(db_session, api_client):
    project = _project(db_session)
    stage = db_session.query(WorkflowStage).filter(WorkflowStage.code == "etapa-06").one()
    created = api_client.post(
        "/api/planning/events",
        json={
            "title": "Visita ligada ao Processo",
            "category": "technical_visit",
            "starts_at": _iso(),
            "ends_at": _iso(25),
            "project_id": str(project.id),
            "process_stage_id": str(stage.id),
        },
        headers=_headers(CHEFE),
    )
    assert created.status_code == 201, created.text
    assert created.json()["process_stage_id"] == str(stage.id)
    assert created.json()["source"] == "manual"
    assert created.json()["project_url"] == f"/projects/{project.id}?tab=processo"

    before = db_session.query(Project).count()
    invalid = api_client.post(
        "/api/planning/events",
        json={
            "title": "Etapa inexistente",
            "category": "other",
            "starts_at": _iso(),
            "ends_at": _iso(25),
            "project_id": str(project.id),
            "process_stage_id": str(uuid.uuid4()),
        },
        headers=_headers(CHEFE),
    )
    assert invalid.status_code == 422
    assert db_session.query(Project).count() == before


def _run_alembic(database_path: Path, backend_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "APP_ENV": "test",
            "DATABASE_URL": f"sqlite:///{database_path}",
            "EXPECTED_DB_DIALECT": "sqlite",
        }
    )
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=backend_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_planning_migration_backfills_legacy_participant_and_roundtrips(tmp_path):
    backend_path = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "planning-migration.db"
    before = _run_alembic(database_path, backend_path, "upgrade", "d4e6f8a1b2c3")
    assert before.returncode == 0, before.stdout + before.stderr

    event_id = str(uuid.uuid4())
    person_id = str(uuid.uuid4())
    now = "2040-03-01 09:00:00"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO people (id, display_name, email, legacy_ref, is_active, created_at, updated_at) "
            "VALUES (?, ?, NULL, NULL, 1, ?, ?)",
            (person_id, "Pessoa Sintética", now, now),
        )
        connection.execute(
            "INSERT INTO calendar_events "
            "(id, visit_id, project_id, title, starts_at, ends_at, status, graph_event_id, ics_fallback_path, "
            "created_at, updated_at, task_id, assigned_to_person_id) "
            "VALUES (?, NULL, NULL, ?, ?, ?, 'rascunho', NULL, NULL, ?, ?, NULL, ?)",
            (event_id, "Evento legado", now, "2040-03-01 10:00:00", now, now, person_id),
        )
        connection.commit()

    upgraded = _run_alembic(database_path, backend_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM calendar_event_assignees WHERE event_id = ? AND person_id = ?",
            (event_id, person_id),
        ).fetchone()[0] == 1
        assert {row[1] for row in connection.execute("PRAGMA table_info(calendar_events)")} >= {
            "category",
            "process_stage_id",
            "process_subtask_id",
        }
        assert connection.execute("SELECT view, hide_weekends FROM planning_preferences").fetchall() == []

    downgraded = _run_alembic(database_path, backend_path, "downgrade", "d4e6f8a1b2c3")
    assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='calendar_event_assignees'"
        ).fetchone()[0] == 0
        assert "category" not in {row[1] for row in connection.execute("PRAGMA table_info(calendar_events)")}

    upgraded_again = _run_alembic(database_path, backend_path, "upgrade", "head")
    assert upgraded_again.returncode == 0, upgraded_again.stdout + upgraded_again.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM calendar_event_assignees").fetchone()[0] == 1
