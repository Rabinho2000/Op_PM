"""PostgreSQL concurrency regression for the first Projects-list preference."""
from __future__ import annotations

import concurrent.futures
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.db import SessionLocal, engine, get_db
from app.main import app
from app.models.identity import User
from app.models.project_list_views import UserProjectListPreference


pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="requires a real PostgreSQL database",
)


HEADERS = {"X-Dev-User-Email": "chefe.sintetico@example.invalid"}


def _config(direction: str) -> dict[str, object]:
    return {
        "columns": [
            "project",
            "pm",
            "lifecycle",
            "progress",
            "next_task",
            "overdue",
            "warnings",
        ],
        "sort_by": "name",
        "sort_direction": direction,
        "filters": {
            "search": "",
            "status": "",
            "lifecycle": ["on_hold_cliente", "preparacao", "construcao", "construido"],
            "pm": "",
            "active": "active",
            "startFrom": "",
            "startTo": "",
        },
    }


def test_concurrent_first_preference_creation_returns_two_api_successes():
    setup = SessionLocal()
    try:
        user = setup.query(User).filter_by(email=HEADERS["X-Dev-User-Email"]).one()
        user_id = user.id
        setup.query(UserProjectListPreference).filter_by(user_id=user_id).delete(
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
        if "project_list_preferences" not in lowered:
            return
        thread_id = threading.get_ident()
        with gate_lock:
            if thread_id in seen_threads:
                return
            seen_threads.add(thread_id)
        barrier.wait(timeout=20)

    def override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    event.listen(engine, "before_cursor_execute", gate_initial_preference_read)
    try:
        def worker(payload: dict[str, object]):
            try:
                with TestClient(app, raise_server_exceptions=False) as client:
                    response = client.put(
                        "/api/me/project-list-preferences",
                        headers=HEADERS,
                        json={"config": payload},
                    )
                with result_lock:
                    responses.append(response)
                return response
            except BaseException as exc:  # no SQL/values in assertion output
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
            readback.query(UserProjectListPreference)
            .filter_by(user_id=user_id)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].config in payloads
    finally:
        readback.close()
        cleanup = SessionLocal()
        try:
            cleanup.query(UserProjectListPreference).filter_by(user_id=user_id).delete(
                synchronize_session=False
            )
            cleanup.commit()
        finally:
            cleanup.close()
