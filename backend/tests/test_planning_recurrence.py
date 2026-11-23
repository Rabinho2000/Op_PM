from __future__ import annotations

import datetime as dt
import threading
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.calendar import CalendarEvent, CalendarEventAudit, CalendarEventSeries
from app.models.identity import Permission, Role, RolePermission, User, UserRole
from app.models.people import Person
from app.models.project import Project
from app.security.permissions import AuthContext
from app.services.planning import (
    create_weekly_calendar_event_series,
    update_calendar_event_series,
)


ADMIN = {"X-Dev-User-Email": "admin.sintetico@example.invalid"}
CHEFE = {"X-Dev-User-Email": "chefe.sintetico@example.invalid"}
PM = {"X-Dev-User-Email": "pm.um.sintetico@example.invalid"}
LISBON = ZoneInfo("Europe/Lisbon")


def _series_body(project_id, *, key="weekly-series-key-0001", starts_at="2026-03-22T09:00:00+00:00"):
    return {
        "title": "Reunião semanal sintética",
        "starts_at": starts_at,
        "ends_at": starts_at.replace("09:00", "10:00"),
        "project_id": str(project_id),
        "category": "meeting",
        "recurrence": "weekly",
        "recurrence_until": "2026-04-12",
        "idempotency_key": key,
    }


def _visible_project(db, *, name, pm_person_id):
    project = Project(
        name=name,
        pm_person_id=pm_person_id,
        lifecycle_status="construcao",
        work_start_date=dt.date(2042, 6, 1),
        work_end_date=dt.date(2042, 6, 3),
        is_active=True,
    )
    db.add(project)
    db.commit()
    return project


def test_weekly_series_keeps_lisbon_wall_time_and_retry_is_idempotent(db_session, api_client):
    project = _visible_project(
        db_session,
        name="Instalação Sintética Recorrência Lisboa",
        pm_person_id=db_session.query(Person).filter_by(display_name="PM Sintético Um").one().id,
    )
    body = _series_body(project.id)

    first = api_client.post("/api/planning/events", headers=CHEFE, json=body)
    retry = api_client.post("/api/planning/events", headers=CHEFE, json=body)

    assert first.status_code == 201, first.text
    assert retry.status_code == 201, retry.text
    assert first.json()["id"] == retry.json()["id"]
    assert first.json()["recurrence_rule"] == "weekly"
    assert first.json()["recurrence_count"] == 4
    create_audits = db_session.query(CalendarEventAudit).filter_by(action="create").all()
    assert len(create_audits) == 4
    assert {str(audit.series_id) for audit in create_audits} == {
        first.json()["recurrence_series_id"]
    }
    series = db_session.query(CalendarEventSeries).one()
    events = (
        db_session.query(CalendarEvent)
        .filter(CalendarEvent.series_id == series.id)
        .order_by(CalendarEvent.series_occurrence_index)
        .all()
    )
    assert len(events) == 4
    local_starts = [
        (row.starts_at.replace(tzinfo=dt.timezone.utc) if row.starts_at.tzinfo is None else row.starts_at)
        .astimezone(LISBON)
        for row in events
    ]
    assert [value.strftime("%H:%M") for value in local_starts] == ["09:00"] * 4
    assert local_starts[0].utcoffset() == dt.timedelta(0)
    assert local_starts[1].utcoffset() == dt.timedelta(hours=1)

    mismatched_retry = api_client.post(
        "/api/planning/events", headers=CHEFE, json={**body, "title": "Outro conteúdo"}
    )
    assert mismatched_retry.status_code == 409
    assert db_session.query(CalendarEventSeries).count() == 1
    assert db_session.query(CalendarEvent).filter(CalendarEvent.series_id == series.id).count() == 4
    assert db_session.query(CalendarEventAudit).filter_by(action="create").count() == 4


def test_concurrent_retries_with_real_sessions_create_one_weekly_series(tmp_path):
    test_engine = create_engine(
        f"sqlite:///{(tmp_path / 'recurrence-concurrency.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
        future=True,
    )

    @event.listens_for(test_engine, "connect")
    def _sqlite_transaction_mode(connection, _record):
        connection.isolation_level = None

    @event.listens_for(test_engine, "begin")
    def _sqlite_begin_immediate(connection):
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    Base.metadata.create_all(bind=test_engine)
    sessions = sessionmaker(bind=test_engine, autoflush=False, future=True)
    setup = sessions()
    try:
        person = Person(display_name="Criador concorrente sintético")
        setup.add(person)
        setup.flush()
        user = User(person_id=person.id, email="recurrence.concurrent@example.invalid", is_active=True)
        project = Project(
            name="Projeto concorrente sintético",
            pm_person_id=person.id,
            lifecycle_status="construcao",
            is_active=True,
        )
        setup.add_all([user, project])
        setup.commit()
        user_id, person_id, project_id = user.id, person.id, project.id
    finally:
        setup.close()

    barrier = threading.Barrier(2, timeout=15)
    session_ids: list[int] = []
    results: list[str] = []
    errors: list[str] = []

    def worker() -> None:
        db = sessions()
        session_ids.append(id(db))
        try:
            user = User(
                id=user_id,
                person_id=person_id,
                email="recurrence.concurrent@example.invalid",
                is_active=True,
            )
            ctx = AuthContext(
                user=user,
                person_id=user.person_id,
                role_codes=frozenset({"recurrence_concurrent_test"}),
                permission_codes=frozenset(
                    {"calendar.manage", "calendar.view", "project.edit_all", "project.view_all"}
                ),
            )
            barrier.wait()
            created = create_weekly_calendar_event_series(
                db,
                ctx=ctx,
                title="Retry concorrente sintético",
                starts_at=dt.datetime.fromisoformat("2026-10-25T01:30:00+00:00"),
                ends_at=dt.datetime.fromisoformat("2026-10-25T02:30:00+00:00"),
                recurrence_until=dt.date(2026, 11, 15),
                idempotency_key="weekly-series-concurrent-real-sessions",
                project_id=project_id,
                task_id=None,
                assigned_to_person_id=None,
                category="meeting",
            )
            results.append(str(created.id))
        except BaseException as exc:  # keep SQL details out of assertion output
            db.rollback()
            errors.append(type(exc).__name__)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        assert all(not thread.is_alive() for thread in threads)
        assert len(set(session_ids)) == 2
        assert errors == []
        assert len(results) == 2
        assert len(set(results)) == 1

        readback = sessions()
        try:
            series = readback.query(CalendarEventSeries).one()
            assert series.starts_fold == 1
            assert (
                readback.query(CalendarEventAudit)
                .filter_by(series_id=series.id, action="create")
                .count()
                == 4
            )
            events = (
                readback.query(CalendarEvent)
                .filter_by(series_id=series.id)
                .order_by(CalendarEvent.series_occurrence_index)
                .all()
            )
            assert len(events) == 4
            first_local_start = events[0].starts_at.replace(tzinfo=dt.timezone.utc).astimezone(LISBON)
            assert first_local_start.fold == 1
        finally:
            readback.close()
    finally:
        test_engine.dispose()


def test_concurrent_series_editers_wait_and_merge_refreshed_state(tmp_path):
    """Two independent sessions edit different schedule fields while one holds the SQLite write lock."""
    test_engine = create_engine(
        f"sqlite:///{(tmp_path / 'recurrence-edit-concurrency.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
        future=True,
    )

    @event.listens_for(test_engine, "connect")
    def _sqlite_transaction_mode(connection, _record):
        connection.isolation_level = None

    @event.listens_for(test_engine, "begin")
    def _sqlite_begin_immediate(connection):
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    Base.metadata.create_all(bind=test_engine)
    sessions = sessionmaker(bind=test_engine, autoflush=False, future=True)
    setup = sessions()
    try:
        person = Person(display_name="Editor recorrência concorrente sintético")
        setup.add(person)
        setup.flush()
        user = User(person_id=person.id, email="recurrence.edit.concurrent@example.invalid", is_active=True)
        project = Project(
            name="Projeto edição concorrente sintético",
            pm_person_id=person.id,
            lifecycle_status="construcao",
            is_active=True,
        )
        setup.add_all([user, project])
        setup.commit()
        user_id, person_id, project_id = user.id, person.id, project.id

        ctx = AuthContext(
            user=user,
            person_id=person_id,
            role_codes=frozenset({"recurrence_edit_concurrent_test"}),
            permission_codes=frozenset(
                {"calendar.manage", "calendar.view", "project.edit_all", "project.view_all"}
            ),
        )
        first = create_weekly_calendar_event_series(
            setup,
            ctx=ctx,
            title="Série concorrente original",
            starts_at=dt.datetime.fromisoformat("2027-01-04T09:00:00+00:00"),
            ends_at=dt.datetime.fromisoformat("2027-01-04T10:00:00+00:00"),
            recurrence_until=dt.date(2027, 1, 11),
            idempotency_key="weekly-series-edit-concurrent-real-sessions",
            project_id=project_id,
            task_id=None,
            assigned_to_person_id=None,
            category="meeting",
        )
        event_id = first.id
        series_id = first.series_id
        assert setup.query(CalendarEventAudit).filter_by(series_id=series_id, action="create").count() == 2
    finally:
        setup.close()

    # Keep a genuinely stale ORM instance in editor two's identity map. The
    # second editor must refresh it after waiting on the first editor's lock.
    stale_reader = sessions()
    stale_event = stale_reader.query(CalendarEvent).filter_by(id=event_id).one()
    stale_reader.expunge(stale_event)
    stale_reader.close()

    second_writer_attempted = threading.Event()
    first_has_lock = threading.Event()
    release_first = threading.Event()
    second_finished = threading.Event()
    session_ids: list[int] = []
    errors: list[str] = []

    def make_context(db):
        user = db.get(User, user_id)
        return AuthContext(
            user=user,
            person_id=person_id,
            role_codes=frozenset({"recurrence_edit_concurrent_test"}),
            permission_codes=frozenset(
                {"calendar.manage", "calendar.view", "project.edit_all", "project.view_all"}
            ),
        )

    def first_editor() -> None:
        db = sessions()
        session_ids.append(id(db))
        try:
            locked = db.query(CalendarEvent).filter_by(id=event_id).one()
            first_has_lock.set()
            if not release_first.wait(10):
                raise TimeoutError("editor um não recebeu a libertação do lock")
            update_calendar_event_series(
                db,
                event=locked,
                changes={"starts_at": dt.datetime.fromisoformat("2027-01-04T11:00:00+00:00")},
                ctx=make_context(db),
            )
        except BaseException as exc:
            db.rollback()
            errors.append(f"editor um: {type(exc).__name__}: {exc}")
        finally:
            db.close()

    def second_editor() -> None:
        db = sessions()
        session_ids.append(id(db))
        try:
            db.add(stale_event)
            second_writer_attempted.set()
            update_calendar_event_series(
                db,
                event=stale_event,
                changes={"ends_at": dt.datetime.fromisoformat("2027-01-04T13:00:00+00:00")},
                ctx=make_context(db),
            )
        except BaseException as exc:
            db.rollback()
            errors.append(f"editor dois: {type(exc).__name__}: {exc}")
        finally:
            second_finished.set()
            db.close()

    first_thread = threading.Thread(target=first_editor, name="series-editor-one")
    second_thread = threading.Thread(target=second_editor, name="series-editor-two")
    try:
        first_thread.start()
        assert first_has_lock.wait(5), "editor um não adquiriu o lock de escrita"
        second_thread.start()
        assert second_writer_attempted.wait(5), "editor dois não tentou iniciar a transação de escrita"
        assert not second_finished.wait(0.25), (
            "editor dois não bloqueou enquanto o primeiro mantinha o lock; "
            f"erros observados: {errors}"
        )
        release_first.set()
        first_thread.join(timeout=15)
        second_thread.join(timeout=15)

        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert len(set(session_ids)) == 2
        assert errors == []

        readback = sessions()
        try:
            series = readback.get(CalendarEventSeries, series_id)
            rows = (
                readback.query(CalendarEvent)
                .filter_by(series_id=series_id)
                .order_by(CalendarEvent.series_occurrence_index)
                .all()
            )
            assert len(rows) == 2
            local_times = [
                (
                    row.starts_at.replace(tzinfo=dt.timezone.utc)
                    if row.starts_at.tzinfo is None
                    else row.starts_at
                ).astimezone(LISBON)
                for row in rows
            ]
            local_ends = [
                (
                    row.ends_at.replace(tzinfo=dt.timezone.utc)
                    if row.ends_at.tzinfo is None
                    else row.ends_at
                ).astimezone(LISBON)
                for row in rows
            ]
            assert [value.strftime("%H:%M") for value in local_times] == ["11:00", "11:00"]
            assert [value.strftime("%H:%M") for value in local_ends] == ["13:00", "13:00"]
            assert series.starts_at_local == "11:00"
            assert series.ends_at_local == "13:00"
            edit_audits = (
                readback.query(CalendarEventAudit)
                .filter_by(series_id=series_id, action="update")
                .all()
            )
            assert len(edit_audits) == 4
            end_changes = [
                audit
                for audit in edit_audits
                if audit.field_changes.get("ends_at", {}).get("new", "").endswith(
                    "T13:00:00+00:00"
                )
            ]
            assert len(end_changes) == 2
            assert all(
                audit.field_changes["ends_at"] == {
                        "old": "2027-01-04T12:00:00+00:00"
                    if audit.event_id == rows[0].id
                        else "2027-01-11T12:00:00+00:00",
                    "new": "2027-01-04T13:00:00+00:00"
                    if audit.event_id == rows[0].id
                    else "2027-01-11T13:00:00+00:00",
                }
                for audit in end_changes
            )
        finally:
            readback.close()
    finally:
        release_first.set()
        first_thread.join(timeout=15)
        second_thread.join(timeout=15)
        test_engine.dispose()


def test_recurrence_service_preserves_idempotency_dst_and_exceptions(db_session):
    from app.services.planning import (
        CalendarEventIdempotencyConflict,
        CalendarEventValidationError,
        update_calendar_event,
    )

    person = db_session.query(Person).filter_by(display_name="PM Sintético Um").one()
    user = db_session.query(User).filter_by(email="chefe.sintetico@example.invalid").one()
    project = _visible_project(
        db_session,
        name="Instalação Sintética Recorrência Serviço",
        pm_person_id=person.id,
    )
    ctx = AuthContext(
        user=user,
        person_id=user.person_id,
        role_codes=frozenset({"recurrence_service_regression"}),
        permission_codes=frozenset(
            {"calendar.view", "calendar.manage", "project.view_all", "project.edit_all"}
        ),
    )

    def create_series(key, starts_at, ends_at, until, *, title="Série de serviço sintética"):
        return create_weekly_calendar_event_series(
            db_session,
            ctx=ctx,
            title=title,
            starts_at=dt.datetime.fromisoformat(starts_at),
            ends_at=dt.datetime.fromisoformat(ends_at),
            recurrence_until=dt.date.fromisoformat(until),
            idempotency_key=key,
            project_id=project.id,
            task_id=None,
            assigned_to_person_id=None,
            category="meeting",
        )

    first = create_series(
        "weekly-series-service-idempotency",
        "2026-03-22T09:00:00+00:00",
        "2026-03-22T10:00:00+00:00",
        "2026-04-12",
    )
    retry = create_series(
        "weekly-series-service-idempotency",
        "2026-03-22T09:00:00+00:00",
        "2026-03-22T10:00:00+00:00",
        "2026-04-12",
    )
    assert first.id == retry.id
    series = db_session.query(CalendarEventSeries).filter_by(id=first.series_id).one()
    events = (
        db_session.query(CalendarEvent)
        .filter_by(series_id=series.id)
        .order_by(CalendarEvent.series_occurrence_index)
        .all()
    )
    assert len(events) == 4
    local_starts = [
        (row.starts_at.replace(tzinfo=dt.timezone.utc) if row.starts_at.tzinfo is None else row.starts_at)
        .astimezone(LISBON)
        for row in events
    ]
    assert [value.strftime("%H:%M") for value in local_starts] == ["09:00"] * 4
    assert local_starts[0].utcoffset() == dt.timedelta(0)
    assert local_starts[1].utcoffset() == dt.timedelta(hours=1)
    assert db_session.query(CalendarEventAudit).filter_by(series_id=series.id, action="create").count() == 4

    try:
        create_series(
            "weekly-series-service-idempotency",
            "2026-03-22T09:00:00+00:00",
            "2026-03-22T10:00:00+00:00",
            "2026-04-12",
            title="Conteúdo incompatível",
        )
        raise AssertionError("a reutilização da chave com outros dados devia falhar")
    except CalendarEventIdempotencyConflict as exc:
        assert exc.status_code == 409
    assert db_session.query(CalendarEventSeries).count() == 1
    assert db_session.query(CalendarEventAudit).filter_by(series_id=series.id, action="create").count() == 4

    fall = create_series(
        "weekly-series-service-fall-fold",
        "2026-10-25T01:30:00+00:00",
        "2026-10-25T02:30:00+00:00",
        "2026-11-08",
    )
    fall_series = db_session.query(CalendarEventSeries).filter_by(id=fall.series_id).one()
    fall_rows = (
        db_session.query(CalendarEvent)
        .filter_by(series_id=fall_series.id)
        .order_by(CalendarEvent.series_occurrence_index)
        .all()
    )
    assert fall_series.starts_fold == 1
    first_local = fall_rows[0].starts_at.replace(tzinfo=dt.timezone.utc).astimezone(LISBON)
    second_local = fall_rows[1].starts_at.replace(tzinfo=dt.timezone.utc).astimezone(LISBON)
    assert first_local.fold == 1
    assert second_local.fold == 0
    assert first_local.strftime("%H:%M") == second_local.strftime("%H:%M") == "01:30"

    try:
        create_series(
            "weekly-series-service-dst-gap",
            "2026-03-22T01:30:00+00:00",
            "2026-03-22T02:30:00+00:00",
            "2026-04-05",
        )
        raise AssertionError("a nonexistent Lisboa wall-clock time devia falhar")
    except CalendarEventValidationError as exc:
        assert "não existe" in str(exc)
    assert db_session.query(CalendarEventSeries).count() == 2

    exception_series = create_series(
        "weekly-series-service-exception",
        "2027-01-04T09:00:00+00:00",
        "2027-01-04T10:00:00+00:00",
        "2027-01-11",
    )
    exception_rows = (
        db_session.query(CalendarEvent)
        .filter_by(series_id=exception_series.series_id)
        .order_by(CalendarEvent.series_occurrence_index)
        .all()
    )
    update_calendar_event_series(
        db_session,
        event=exception_rows[0],
        changes={"starts_at": dt.datetime.fromisoformat("2027-01-04T11:00:00+00:00")},
        ctx=ctx,
    )
    second = db_session.query(CalendarEvent).filter_by(id=exception_rows[1].id).one()
    update_calendar_event(
        db_session,
        event=second,
        changes={
            "title": "Exceção de data preservada",
            "starts_at": dt.datetime.fromisoformat("2027-01-20T14:00:00+00:00"),
            "ends_at": dt.datetime.fromisoformat("2027-01-20T15:00:00+00:00"),
        },
        ctx=ctx,
    )
    exception_times = (
        db_session.query(CalendarEvent.starts_at, CalendarEvent.ends_at)
        .filter(CalendarEvent.series_id == exception_series.series_id)
        .order_by(CalendarEvent.series_occurrence_index)
        .all()
    )
    second = db_session.query(CalendarEvent).filter_by(id=exception_rows[1].id).one()
    update_calendar_event_series(
        db_session,
        event=second,
        changes={"title": "Nome atualizado sem mover exceções"},
        ctx=ctx,
    )
    final_rows = (
        db_session.query(CalendarEvent)
        .filter_by(series_id=exception_series.series_id)
        .order_by(CalendarEvent.series_occurrence_index)
        .all()
    )
    assert [(row.starts_at, row.ends_at) for row in final_rows] == exception_times
    assert [row.title for row in final_rows] == [
        "Nome atualizado sem mover exceções",
        "Nome atualizado sem mover exceções",
    ]


def test_weekly_series_preserves_second_lisbon_fall_fold(db_session, api_client):
    project = _visible_project(
        db_session,
        name="Instalação Sintética Recorrência Fold Outono",
        pm_person_id=db_session.query(Person).filter_by(display_name="PM Sintético Um").one().id,
    )
    body = _series_body(
        project.id,
        key="weekly-series-fall-fold",
        starts_at="2026-10-25T01:30:00+00:00",
    )
    body["ends_at"] = "2026-10-25T02:30:00+00:00"
    body["recurrence_until"] = "2026-11-08"

    response = api_client.post("/api/planning/events", headers=CHEFE, json=body)

    assert response.status_code == 201, response.text
    series = db_session.query(CalendarEventSeries).one()
    assert series.starts_fold == 1
    events = (
        db_session.query(CalendarEvent)
        .filter(CalendarEvent.series_id == series.id)
        .order_by(CalendarEvent.series_occurrence_index)
        .all()
    )
    local_starts = [
        (row.starts_at.replace(tzinfo=dt.timezone.utc) if row.starts_at.tzinfo is None else row.starts_at)
        .astimezone(LISBON)
        for row in events
    ]
    assert [value.strftime("%H:%M") for value in local_starts] == ["01:30"] * 3
    assert local_starts[0].fold == 1
    assert local_starts[0].utcoffset() == dt.timedelta(0)
    assert local_starts[1].fold == 0
    assert local_starts[1].utcoffset() == dt.timedelta(0)


def test_weekly_series_requires_end_date_caps_occurrences_and_rejects_dst_gap(db_session, api_client):
    project = _visible_project(
        db_session,
        name="Instalação Sintética Recorrência Limites",
        pm_person_id=db_session.query(Person).filter_by(display_name="PM Sintético Um").one().id,
    )
    body = _series_body(project.id)

    missing_end = api_client.post(
        "/api/planning/events", headers=CHEFE, json={key: value for key, value in body.items() if key != "recurrence_until"}
    )
    assert missing_end.status_code == 422

    too_many = api_client.post(
        "/api/planning/events",
        headers=CHEFE,
        json={**body, "recurrence_until": "2027-03-21", "idempotency_key": "weekly-series-key-0002"},
    )
    assert too_many.status_code == 400
    assert "52" in too_many.json()["detail"]

    dst_gap = api_client.post(
        "/api/planning/events",
        headers=CHEFE,
        json={
            **body,
            "starts_at": "2026-03-22T01:30:00+00:00",
            "ends_at": "2026-03-22T02:30:00+00:00",
            "recurrence_until": "2026-04-05",
            "idempotency_key": "weekly-series-key-0003",
        },
    )
    assert dst_gap.status_code == 400
    assert "não existe" in dst_gap.json()["detail"]
    assert db_session.query(CalendarEventSeries).count() == 0

    another_pm = db_session.query(Person).filter_by(display_name="Chefe Sintético").one()
    project_outside_pm_scope = _visible_project(
        db_session,
        name="Instalação Sintética Recorrência Fora do Âmbito",
        pm_person_id=another_pm.id,
    )
    forbidden = api_client.post(
        "/api/planning/events",
        headers=PM,
        json=_series_body(project_outside_pm_scope.id, key="weekly-series-key-0004"),
    )
    assert forbidden.status_code == 403
    assert db_session.query(CalendarEventSeries).count() == 0


def test_series_edit_and_cancel_distinguish_occurrence_from_series(db_session, api_client):
    project = _visible_project(
        db_session,
        name="Instalação Sintética Recorrência Edição",
        pm_person_id=db_session.query(Person).filter_by(display_name="PM Sintético Um").one().id,
    )
    body = _series_body(project.id, key="weekly-series-key-edit", starts_at="2027-01-04T09:00:00+00:00")
    body["recurrence_until"] = "2027-01-11"
    first = api_client.post("/api/planning/events", headers=CHEFE, json=body)
    assert first.status_code == 201, first.text
    series_id = first.json()["recurrence_series_id"]
    series_uuid = db_session.query(CalendarEventSeries).one().id
    assert db_session.query(CalendarEventAudit).filter_by(action="create").count() == 2
    rows = (
        db_session.query(CalendarEvent)
        .filter(CalendarEvent.series_id == series_id)
        .order_by(CalendarEvent.series_occurrence_index)
        .all()
    )
    first_id, second_id = str(rows[0].id), str(rows[1].id)

    updated_series = api_client.patch(
        f"/api/planning/events/{first_id}?scope=series",
        headers=CHEFE,
        json={
            "title": "Reunião semanal atualizada",
            "starts_at": "2027-01-04T11:00:00+00:00",
            "ends_at": "2027-01-04T12:00:00+00:00",
        },
    )
    assert updated_series.status_code == 200, updated_series.text
    db_session.expire_all()
    rows = (
        db_session.query(CalendarEvent)
        .filter(CalendarEvent.series_id == series_id)
        .order_by(CalendarEvent.series_occurrence_index)
        .all()
    )
    assert [row.title for row in rows] == ["Reunião semanal atualizada"] * 2
    assert [row.starts_at.hour for row in rows] == [11, 11]
    series_update_audits = (
        db_session.query(CalendarEventAudit)
        .filter_by(series_id=series_uuid, action="update")
        .all()
    )
    assert len(series_update_audits) == 2
    assert all("starts_at" in audit.field_changes for audit in series_update_audits)

    updated_occurrence = api_client.patch(
        f"/api/planning/events/{second_id}?scope=occurrence",
        headers=CHEFE,
        json={
            "title": "Só esta ocorrência",
            "starts_at": "2027-01-20T14:00:00+00:00",
            "ends_at": "2027-01-20T15:00:00+00:00",
        },
    )
    assert updated_occurrence.status_code == 200, updated_occurrence.text
    db_session.expire_all()
    rows = (
        db_session.query(CalendarEvent)
        .filter(CalendarEvent.series_id == series_id)
        .order_by(CalendarEvent.series_occurrence_index)
        .all()
    )
    assert [row.title for row in rows] == ["Reunião semanal atualizada", "Só esta ocorrência"]
    exception_dates = [(row.starts_at, row.ends_at) for row in rows]
    occurrence_audits = (
        db_session.query(CalendarEventAudit)
        .filter_by(event_id=rows[1].id, action="update")
        .all()
    )
    expected_title_change = {
        "old": "Reunião semanal atualizada",
        "new": "Só esta ocorrência",
    }
    matching_occurrence_audits = [
        audit
        for audit in occurrence_audits
        if audit.field_changes.get("title") == expected_title_change
    ]
    assert len(matching_occurrence_audits) == 1
    occurrence_audit = matching_occurrence_audits[0]
    assert occurrence_audit.field_changes["title"] == {
        "old": "Reunião semanal atualizada",
        "new": "Só esta ocorrência",
    }
    assert occurrence_audit.field_changes["starts_at"] == {
        "old": "2027-01-11T11:00:00+00:00",
        "new": "2027-01-20T14:00:00+00:00",
    }
    assert occurrence_audit.field_changes["ends_at"] == {
        "old": "2027-01-11T12:00:00+00:00",
        "new": "2027-01-20T15:00:00+00:00",
    }

    updated_series_title = api_client.patch(
        f"/api/planning/events/{second_id}?scope=series",
        headers=CHEFE,
        json={"title": "Série editada depois da exceção"},
    )
    assert updated_series_title.status_code == 200, updated_series_title.text
    db_session.expire_all()
    rows = (
        db_session.query(CalendarEvent)
        .filter(CalendarEvent.series_id == series_id)
        .order_by(CalendarEvent.series_occurrence_index)
        .all()
    )
    assert [row.title for row in rows] == ["Série editada depois da exceção"] * 2
    assert [(row.starts_at, row.ends_at) for row in rows] == exception_dates
    assert (
        db_session.query(CalendarEventAudit)
        .filter_by(series_id=series_uuid, action="update")
        .count()
        == 5
    )

    cancelled = api_client.post(
        f"/api/planning/events/{first_id}/cancel?scope=series", headers=CHEFE
    )
    assert cancelled.status_code == 200, cancelled.text
    db_session.expire_all()
    assert {
        row.status for row in db_session.query(CalendarEvent).filter(CalendarEvent.series_id == series_id).all()
    } == {"cancelado"}
    cancellation_audits = (
        db_session.query(CalendarEventAudit)
        .filter_by(series_id=series_uuid, action="cancel")
        .all()
    )
    assert len(cancellation_audits) == 2
    assert all(
        audit.field_changes["status"] == {"old": "rascunho", "new": "cancelado"}
        for audit in cancellation_audits
    )


def test_series_mutations_require_visibility_of_every_occurrence(db_session):
    from fastapi import HTTPException

    from app.api.routes_planning import cancel_event_endpoint, update_event_endpoint
    from app.schemas.planning import CalendarEventUpdate

    outside_pm = db_session.query(Person).filter_by(display_name="Chefe Sintético").one()
    project = _visible_project(
        db_session,
        name="Instalação Sintética Recorrência Privada",
        pm_person_id=outside_pm.id,
    )
    creator = db_session.query(User).filter_by(email="chefe.sintetico@example.invalid").one()
    creator_ctx = AuthContext(
        user=creator,
        person_id=creator.person_id,
        role_codes=frozenset({"calendar_visibility_test_creator"}),
        permission_codes=frozenset({"calendar.view", "calendar.manage", "project.view_all", "project.edit_all"}),
    )
    created = create_weekly_calendar_event_series(
        db_session,
        ctx=creator_ctx,
        title="Título original privado",
        starts_at=dt.datetime.fromisoformat("2027-02-01T09:00:00+00:00"),
        ends_at=dt.datetime.fromisoformat("2027-02-01T10:00:00+00:00"),
        recurrence_until=dt.date(2027, 2, 8),
        idempotency_key="weekly-series-visibility",
        project_id=project.id,
        task_id=None,
        assigned_to_person_id=None,
        category="meeting",
    )
    event_id = created.id
    series_id = created.series_id
    assert db_session.query(CalendarEventAudit).filter_by(action="create").count() == 2

    person = Person(display_name="Gestor Sintético Outro Projeto")
    user = User(person=person, email="calendar.other-project@example.invalid", is_active=True)
    role = Role(code="calendar_other_project_test", name="calendar_other_project_test")
    db_session.add_all([person, user, role])
    db_session.flush()
    codes = {"calendar.view", "calendar.manage", "project.view_own", "project.edit_all"}
    db_session.add_all(
        [
            RolePermission(
                role_id=role.id,
                permission_id=db_session.query(Permission).filter_by(code=code).one().id,
            )
            for code in codes
        ]
    )
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    scoped_ctx = AuthContext(
        user=user,
        person_id=user.person_id,
        role_codes=frozenset({role.code}),
        permission_codes=frozenset(codes),
    )

    for mutate in (
        lambda: update_event_endpoint(
            event_id=event_id,
            body=CalendarEventUpdate(title="Título que não pode ser divulgado"),
            scope="series",
            db=db_session,
            ctx=scoped_ctx,
        ),
        lambda: cancel_event_endpoint(event_id=event_id, scope="series", db=db_session, ctx=scoped_ctx),
    ):
        try:
            mutate()
            raise AssertionError("mutação da série fora do âmbito de leitura devia devolver 403")
        except HTTPException as exc:
            assert exc.status_code == 403
            assert "Título original privado" not in str(exc.detail)

    db_session.expire_all()
    unchanged = db_session.query(CalendarEvent).filter_by(series_id=series_id).all()
    assert {row.title for row in unchanged} == {"Título original privado"}
    assert {row.status for row in unchanged} == {"rascunho"}
    assert db_session.query(CalendarEventAudit).filter_by(series_id=series_id).count() == 2

    updated = update_event_endpoint(
        event_id=event_id,
        body=CalendarEventUpdate(title="Edição autorizada"),
        scope="series",
        db=db_session,
        ctx=creator_ctx,
    )
    assert updated.title == "Edição autorizada"
    db_session.expire_all()
    assert {
        row.title for row in db_session.query(CalendarEvent).filter_by(series_id=series_id).all()
    } == {"Edição autorizada"}
    update_audits = db_session.query(CalendarEventAudit).filter_by(series_id=series_id, action="update").all()
    assert len(update_audits) == 2
    assert all(audit.field_changes["title"]["new"] == "Edição autorizada" for audit in update_audits)

    cancel_event_endpoint(event_id=event_id, scope="series", db=db_session, ctx=creator_ctx)
    db_session.expire_all()
    assert {
        row.status for row in db_session.query(CalendarEvent).filter_by(series_id=series_id).all()
    } == {"cancelado"}
    assert db_session.query(CalendarEventAudit).filter_by(series_id=series_id, action="cancel").count() == 2
