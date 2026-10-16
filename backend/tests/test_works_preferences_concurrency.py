"""PostgreSQL concurrency regressions for works preferences."""
from __future__ import annotations

import threading

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from app.db import engine
from app.models.identity import User
from app.models.works_preferences import UserWorksPreference
from app.security.permissions import load_auth_context
from app.services.works_preferences import update_works_preferences


pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="requires a real PostgreSQL database",
)


SessionFactory = sessionmaker(
    bind=engine,
    future=True,
    autoflush=False,
    expire_on_commit=True,
)


def test_concurrent_first_creation_for_same_user_returns_two_successes():
    setup = SessionFactory()
    try:
        user = setup.query(User).filter_by(email="chefe.sintetico@example.invalid").one()
        user_id = user.id
        setup.query(UserWorksPreference).filter_by(user_id=user_id).delete(
            synchronize_session=False
        )
        setup.commit()
    finally:
        setup.close()

    barrier = threading.Barrier(2, timeout=10)
    seen_threads: set[int] = set()
    gate_lock = threading.Lock()
    results: list[dict[str, object]] = []
    errors: list[str] = []
    result_lock = threading.Lock()

    def gate_initial_preference_read(
        conn, cursor, statement, parameters, context, executemany
    ):
        normalized = statement.lower()
        if not normalized.lstrip().startswith("select") or (
            "works_calendar_preferences" not in normalized
        ):
            return
        if threading.current_thread() is threading.main_thread():
            return
        thread_id = threading.get_ident()
        with gate_lock:
            if thread_id in seen_threads:
                return
            seen_threads.add(thread_id)
        barrier.wait(timeout=10)

    event.listen(engine, "before_cursor_execute", gate_initial_preference_read)

    def worker() -> None:
        db = SessionFactory()
        try:
            user = db.get(User, user_id)
            assert user is not None
            ctx = load_auth_context(db, user)
            try:
                payload = update_works_preferences(db, ctx, {"show_idle": True})
                with result_lock:
                    results.append(payload)
            except BaseException as exc:  # no SQL/values in the assertion output
                db.rollback()
                with result_lock:
                    errors.append(type(exc).__name__)
        finally:
            db.close()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        assert all(not thread.is_alive() for thread in threads)
        assert errors == []
        assert len(results) == 2
        assert all(payload["show_idle"] is True for payload in results)

        readback = SessionFactory()
        try:
            row = (
                readback.query(UserWorksPreference)
                .filter(UserWorksPreference.user_id == user_id)
                .one()
            )
            assert row.show_idle is True
        finally:
            readback.close()
    finally:
        event.remove(engine, "before_cursor_execute", gate_initial_preference_read)
        cleanup = SessionFactory()
        try:
            cleanup.query(UserWorksPreference).filter_by(user_id=user_id).delete(
                synchronize_session=False
            )
            cleanup.commit()
        finally:
            cleanup.close()
