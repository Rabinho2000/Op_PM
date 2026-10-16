"""Regressions for commit boundaries in works preferences."""
from __future__ import annotations

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from app.db import engine
from app.models.identity import User
from app.models.works_preferences import UserWorksPreference

PM_UM = "pm.um.sintetico@example.invalid"


def _headers(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _user_id(db_session):
    return db_session.query(User).filter(User.email == PM_UM).one().id


def _insert_existing_preference(db_session):
    row = UserWorksPreference(
        user_id=_user_id(db_session),
        zoom="months",
        lifecycle_status=["construcao"],
        show_idle=False,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _install_post_commit_read_fault(db_session, monkeypatch):
    state = {"committed": False, "preference_selects": []}
    original_commit = db_session.commit

    def commit_then_expire():
        original_commit()
        # Model the normal expire_on_commit boundary explicitly. Any attempt to
        # reconstruct the response now needs a database read.
        db_session.expire_all()
        state["committed"] = True

    monkeypatch.setattr(db_session, "commit", commit_then_expire)

    def fail_post_commit_preference_read(
        conn, cursor, statement, parameters, context, executemany
    ):
        normalized = statement.lower()
        if state["committed"] and normalized.lstrip().startswith("select") and (
            "works_calendar_preferences" in normalized
        ):
            state["preference_selects"].append(" ".join(statement.split()))
            raise OperationalError(
                statement,
                parameters,
                RuntimeError("injected post-commit read failure"),
            )

    event.listen(engine, "before_cursor_execute", fail_post_commit_preference_read)
    return state, fail_post_commit_preference_read


@pytest.mark.parametrize("existing", [False, True], ids=["creation", "existing"])
def test_successful_commit_returns_precommit_payload_without_postcommit_read(
    existing, monkeypatch, db_session, api_client
):
    if existing:
        _insert_existing_preference(db_session)

    state, listener = _install_post_commit_read_fault(db_session, monkeypatch)
    try:
        response = api_client.patch(
            "/api/me/works-preferences",
            json={"show_idle": True},
            headers=_headers(PM_UM),
        )
    finally:
        event.remove(engine, "before_cursor_execute", listener)

    assert response.status_code == 200, response.text
    expected = {
        "zoom": "months" if existing else "month_days",
        "lifecycle_status": ["construcao"] if existing else [],
        "pm_person_id": None,
        "installer_id": None,
        "team_id": None,
        "show_idle": True,
    }
    assert response.json() == expected
    assert state["preference_selects"] == []

    db_session.expire_all()
    row = (
        db_session.query(UserWorksPreference)
        .filter(UserWorksPreference.user_id == _user_id(db_session))
        .one()
    )
    assert row.zoom == expected["zoom"]
    assert row.lifecycle_status == expected["lifecycle_status"]
    assert row.show_idle is True


def test_commit_failure_returns_503_without_durable_creation(
    monkeypatch, db_session, api_client
):
    def fail_commit():
        raise OperationalError(
            "COMMIT",
            {},
            RuntimeError("injected commit failure"),
        )

    monkeypatch.setattr(db_session, "commit", fail_commit)
    response = api_client.patch(
        "/api/me/works-preferences",
        json={"show_idle": True},
        headers=_headers(PM_UM),
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Não foi possível guardar as preferências do calendário de obras."
    }

    db_session.expire_all()
    row = (
        db_session.query(UserWorksPreference)
        .filter(UserWorksPreference.user_id == _user_id(db_session))
        .one_or_none()
    )
    assert row is None
