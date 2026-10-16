"""Real PostgreSQL races for personal Task-list persistence."""
from __future__ import annotations

import concurrent.futures
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.db import SessionLocal, engine, get_db
from app.main import app
from app.models.identity import User
from app.models.task_list_views import TaskListView, UserTaskListPreference

pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="requires a real PostgreSQL database",
)

HEADERS = {"X-Dev-User-Email": "chefe.sintetico@example.invalid"}


def _config(direction: str = "asc") -> dict[str, object]:
    return {
        "columns": ["task", "project", "assignee", "priority", "due_date", "status"],
        "sort_by": "default",
        "sort_direction": direction,
        "view": "lista",
        "filters": {
            "project_id": "",
            "assigned_to_person_id": "",
            "priority": "",
            "status": "",
            "overdue_only": False,
        },
    }


def _override_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_concurrent_first_task_preference_creation_returns_two_successes_and_one_row():
    setup = SessionLocal()
    try:
        user = setup.query(User).filter_by(email=HEADERS["X-Dev-User-Email"]).one()
        user_id = user.id
        setup.query(UserTaskListPreference).filter_by(user_id=user_id).delete(
            synchronize_session=False
        )
        setup.commit()
    finally:
        setup.close()

    barrier = threading.Barrier(2, timeout=20)
    seen_threads: set[int] = set()
    gate_lock = threading.Lock()
    responses = []
    errors: list[str] = []
    result_lock = threading.Lock()

    def gate_initial_preference_read(
        conn, cursor, statement, parameters, context, executemany
    ):
        lowered = statement.lower()
        if threading.current_thread() is threading.main_thread():
            return
        if not lowered.lstrip().startswith("select"):
            return
        if "task_list_preferences" not in lowered:
            return
        thread_id = threading.get_ident()
        with gate_lock:
            if thread_id in seen_threads:
                return
            seen_threads.add(thread_id)
        barrier.wait(timeout=20)

    app.dependency_overrides[get_db] = _override_db
    event.listen(engine, "before_cursor_execute", gate_initial_preference_read)
    try:
        def worker(payload: dict[str, object]):
            try:
                with TestClient(app, raise_server_exceptions=False) as client:
                    response = client.put(
                        "/api/me/task-list-preferences",
                        headers=HEADERS,
                        json={"config": payload},
                    )
                with result_lock:
                    responses.append(response)
                return response
            except BaseException as exc:  # no SQL/values in assertion output  # noqa: BLE001
                with result_lock:
                    errors.append(type(exc).__name__)
                return None

        payloads = [_config("asc"), _config("desc")]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, payloads))

        assert errors == []
        assert all(response is not None for response in results)
        assert sorted(response.status_code for response in responses) == [200, 200]
        assert all(response.json()["config"] in payloads for response in responses)
    finally:
        event.remove(engine, "before_cursor_execute", gate_initial_preference_read)
        app.dependency_overrides.pop(get_db, None)

    readback = SessionLocal()
    try:
        rows = (
            readback.query(UserTaskListPreference)
            .filter_by(user_id=user_id)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].config in payloads
    finally:
        readback.close()
        cleanup = SessionLocal()
        try:
            cleanup.query(UserTaskListPreference).filter_by(user_id=user_id).delete(
                synchronize_session=False
            )
            cleanup.commit()
        finally:
            cleanup.close()


def test_concurrent_same_task_view_name_returns_one_created_and_one_conflict():
    setup = SessionLocal()
    try:
        user = setup.query(User).filter_by(email=HEADERS["X-Dev-User-Email"]).one()
        setup.query(TaskListView).filter(
            TaskListView.user_id == user.id,
            TaskListView.name == "Concorrência Task View Sintética",
        ).update({"is_active": False}, synchronize_session=False)
        setup.commit()
    finally:
        setup.close()

    barrier = threading.Barrier(2, timeout=20)
    seen_threads: set[int] = set()
    gate_lock = threading.Lock()
    responses = []
    result_lock = threading.Lock()

    def gate_name_precheck(conn, cursor, statement, parameters, context, executemany):
        lowered = statement.lower()
        if threading.current_thread() is threading.main_thread():
            return
        if not lowered.lstrip().startswith("select"):
            return
        if "task_list_views" not in lowered or "is_active" not in lowered:
            return
        thread_id = threading.get_ident()
        with gate_lock:
            if thread_id in seen_threads:
                return
            seen_threads.add(thread_id)
        barrier.wait(timeout=20)

    app.dependency_overrides[get_db] = _override_db
    event.listen(engine, "before_cursor_execute", gate_name_precheck)
    try:
        def worker():
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/api/me/task-list-views",
                    headers=HEADERS,
                    json={
                        "name": "Concorrência Task View Sintética",
                        "config": _config(),
                    },
                )
            with result_lock:
                responses.append(response)
            return response

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _item: worker(), (1, 2)))
        assert sorted(response.status_code for response in results) == [201, 409]
    finally:
        event.remove(engine, "before_cursor_execute", gate_name_precheck)
        app.dependency_overrides.pop(get_db, None)

    readback = SessionLocal()
    try:
        user = readback.query(User).filter_by(email=HEADERS["X-Dev-User-Email"]).one()
        assert readback.query(TaskListView).filter(
            TaskListView.user_id == user.id,
            TaskListView.name == "Concorrência Task View Sintética",
            TaskListView.is_active.is_(True),
        ).count() == 1
    finally:
        readback.close()
        cleanup = SessionLocal()
        try:
            user = cleanup.query(User).filter_by(email=HEADERS["X-Dev-User-Email"]).one()
            cleanup.query(TaskListView).filter(
                TaskListView.user_id == user.id,
                TaskListView.name == "Concorrência Task View Sintética",
            ).update({"is_active": False}, synchronize_session=False)
            cleanup.commit()
        finally:
            cleanup.close()
