from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as OrmSession

from app.models.identity import Permission, Role, RolePermission, User, UserRole
from app.models.people import Person
from app.models.time_bank import TimeBankAudit, TimeBankEntry


ADMIN = {"X-Dev-User-Email": "admin.sintetico@example.invalid"}
CHEFE = {"X-Dev-User-Email": "chefe.sintetico@example.invalid"}
PM = {"X-Dev-User-Email": "pm.um.sintetico@example.invalid"}


def _person(db_session, name: str) -> Person:
    return db_session.query(Person).filter(Person.display_name == name).one()


def test_manager_creates_entry_and_reader_only_sees_own_scope(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    response = api_client.post(
        "/api/time-bank/entries",
        headers=ADMIN,
        json={
            "person_id": str(pm.id),
            "work_date": "2026-10-16",
            "start_minute": 540,
            "end_minute": 840,
            "lunch_taken": False,
            "calculation_mode": "standard",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["balance_seconds"] == 3600
    assert body["calculated_seconds"] == 3600

    own = api_client.get("/api/time-bank/entries", headers=PM)
    assert own.status_code == 200
    assert own.json()["total"] == 1
    assert own.json()["items"][0]["person_id"] == str(pm.id)

    other = _person(db_session, "Chefe Sintético")
    denied = api_client.get(f"/api/time-bank/entries?person_id={other.id}", headers=PM)
    assert denied.status_code == 403


def test_manager_can_list_entries_and_adjustments_globally_with_filters_and_pagination(db_session, api_client):
    own = _person(db_session, "PM Sintético Um")
    other = _person(db_session, "Chefe Sintético")

    entry_rows = [
        (own, "2025-12-31"),
        (other, "2026-01-01"),
        (own, "2026-10-16"),
        (other, "2026-12-31"),
        (own, "2027-01-01"),
    ]
    for person, work_date in entry_rows:
        response = api_client.post(
            "/api/time-bank/entries",
            headers=ADMIN,
            json={
                "person_id": str(person.id),
                "work_date": work_date,
                "start_minute": 540,
                "end_minute": 840,
                "lunch_taken": False,
                "calculation_mode": "standard",
            },
        )
        assert response.status_code == 201, response.text

    global_entries = api_client.get(
        "/api/time-bank/entries?from_date=2025-12-31&to_date=2026-12-31&limit=2&offset=1",
        headers=CHEFE,
    )
    assert global_entries.status_code == 200, global_entries.text
    global_entries_body = global_entries.json()
    assert global_entries_body["total"] == 4
    assert [item["work_date"] for item in global_entries_body["items"]] == ["2026-01-01", "2026-10-16"]
    assert {item["person_id"] for item in global_entries_body["items"]} == {str(own.id), str(other.id)}

    person_entries = api_client.get(
        f"/api/time-bank/entries?person_id={own.id}&from_date=2025-12-31&to_date=2026-12-31",
        headers=CHEFE,
    )
    assert person_entries.status_code == 200, person_entries.text
    assert person_entries.json()["total"] == 2
    assert all(item["person_id"] == str(own.id) for item in person_entries.json()["items"])

    adjustment_rows = [
        (own, "2025-12-31", 60),
        (other, "2026-01-01", -60),
        (own, "2026-10-16", 120),
        (other, "2027-01-01", -120),
    ]
    for person, effective_date, delta_seconds in adjustment_rows:
        response = api_client.post(
            "/api/time-bank/adjustments",
            headers=ADMIN,
            json={
                "person_id": str(person.id),
                "effective_date": effective_date,
                "delta_seconds": delta_seconds,
                "kind": "correction",
                "reason": "Correção global sintética.",
            },
        )
        assert response.status_code == 201, response.text

    global_adjustments = api_client.get(
        "/api/time-bank/adjustments?from_date=2025-12-31&to_date=2026-12-31&limit=1&offset=1",
        headers=CHEFE,
    )
    assert global_adjustments.status_code == 200, global_adjustments.text
    global_adjustments_body = global_adjustments.json()
    assert global_adjustments_body["total"] == 3
    assert [item["effective_date"] for item in global_adjustments_body["items"]] == ["2026-01-01"]
    assert global_adjustments_body["items"][0]["person_id"] == str(other.id)

    person_adjustments = api_client.get(
        f"/api/time-bank/adjustments?person_id={other.id}&from_date=2025-12-31&to_date=2026-12-31",
        headers=CHEFE,
    )
    assert person_adjustments.status_code == 200, person_adjustments.text
    assert person_adjustments.json()["total"] == 1
    assert all(item["person_id"] == str(other.id) for item in person_adjustments.json()["items"])


def test_reader_omitted_person_id_uses_own_scope_and_rejects_other_person(db_session, api_client):
    own = _person(db_session, "PM Sintético Um")
    other = _person(db_session, "Chefe Sintético")

    for person, work_date in ((own, "2026-10-16"), (other, "2026-10-19")):
        response = api_client.post(
            "/api/time-bank/entries",
            headers=ADMIN,
            json={
                "person_id": str(person.id),
                "work_date": work_date,
                "start_minute": 540,
                "end_minute": 840,
                "lunch_taken": False,
                "calculation_mode": "standard",
            },
        )
        assert response.status_code == 201, response.text

    for person, effective_date in ((own, "2026-10-16"), (other, "2026-10-17")):
        response = api_client.post(
            "/api/time-bank/adjustments",
            headers=ADMIN,
            json={
                "person_id": str(person.id),
                "effective_date": effective_date,
                "delta_seconds": 60,
                "kind": "correction",
                "reason": "Correção de âmbito sintética.",
            },
        )
        assert response.status_code == 201, response.text

    own_entries = api_client.get("/api/time-bank/entries", headers=PM)
    assert own_entries.status_code == 200, own_entries.text
    assert own_entries.json()["total"] == 1
    assert all(item["person_id"] == str(own.id) for item in own_entries.json()["items"])

    other_entries = api_client.get(f"/api/time-bank/entries?person_id={other.id}", headers=PM)
    assert other_entries.status_code == 403

    own_adjustments = api_client.get("/api/time-bank/adjustments", headers=PM)
    assert own_adjustments.status_code == 200, own_adjustments.text
    assert own_adjustments.json()["total"] == 1
    assert all(item["person_id"] == str(own.id) for item in own_adjustments.json()["items"])

    other_adjustments = api_client.get(f"/api/time-bank/adjustments?person_id={other.id}", headers=PM)
    assert other_adjustments.status_code == 403


def test_append_only_reversal_preserves_original_and_audits_same_transaction(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    created = api_client.post(
        "/api/time-bank/entries",
        headers=CHEFE,
        json={
            "person_id": str(pm.id),
            "work_date": "2026-10-16",
            "start_minute": 540,
            "end_minute": 840,
            "lunch_taken": False,
            "calculation_mode": "standard",
        },
    )
    original_id = created.json()["id"]
    reversed_response = api_client.post(
        f"/api/time-bank/entries/{original_id}/reverse",
        headers=CHEFE,
        json={"reason": "Correção sintética."},
    )
    assert reversed_response.status_code == 200
    assert reversed_response.json()["balance_seconds"] == -3600
    assert reversed_response.json()["reversal_of_id"] == original_id

    original = db_session.get(TimeBankEntry, original_id)
    assert original is not None
    assert original.balance_seconds == 3600
    assert db_session.query(TimeBankEntry).count() == 2
    assert db_session.query(TimeBankAudit).count() >= 2

    duplicate = api_client.post(
        f"/api/time-bank/entries/{original_id}/reverse",
        headers=CHEFE,
        json={"reason": "Segunda tentativa."},
    )
    assert duplicate.status_code == 409


def test_manual_sunday_and_negative_values_are_explicit(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    manual = api_client.post(
        "/api/time-bank/entries",
        headers=ADMIN,
        json={
            "person_id": str(pm.id),
            "work_date": "2026-10-18",
            "calculation_mode": "manual",
            "manual_balance_seconds": -1800,
            "reason": "Domingo sintético aprovado.",
        },
    )
    assert manual.status_code == 201
    assert manual.json()["calculated_seconds"] is None
    assert manual.json()["balance_seconds"] == -1800


def test_summary_warns_without_blocking_and_adjustment_consumption_is_negative(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    entry = api_client.post(
        "/api/time-bank/entries",
        headers=ADMIN,
        json={
            "person_id": str(pm.id),
            "work_date": "2026-10-12",
            "start_minute": 540,
            "end_minute": 1260,
            "lunch_taken": True,
            "calculation_mode": "standard",
        },
    )
    assert entry.status_code == 201
    summary = api_client.get(f"/api/time-bank/summary?person_id={pm.id}&year=2026&month=10", headers=PM)
    assert summary.status_code == 200
    codes = {warning["code"] for warning in summary.json()["people"][0]["warnings"]}
    assert "daily_threshold" in codes

    adjustment = api_client.post(
        "/api/time-bank/adjustments",
        headers=ADMIN,
        json={
            "person_id": str(pm.id),
            "effective_date": "2026-10-20",
            "delta_seconds": -3600,
            "kind": "consumption",
            "reason": "Consumo sintético.",
        },
    )
    assert adjustment.status_code == 201
    positive = api_client.post(
        "/api/time-bank/adjustments",
        headers=ADMIN,
        json={
            "person_id": str(pm.id),
            "effective_date": "2026-10-20",
            "delta_seconds": 3600,
            "kind": "consumption",
            "reason": "Inválido.",
        },
    )
    assert positive.status_code == 422


def test_api_rejects_bool_as_integer_and_unknown_fields(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    response = api_client.post(
        "/api/time-bank/entries",
        headers=ADMIN,
        json={
            "person_id": str(pm.id),
            "work_date": "2026-10-16",
            "start_minute": 540,
            "end_minute": 840,
            "lunch_taken": 1,
            "calculation_mode": "standard",
            "not_allowed": "x",
        },
    )
    assert response.status_code == 422


def _fail_selects_after_this_session_commits(db_session):
    state = {"armed": False}

    def arm(session):
        if session is db_session:
            state["armed"] = True

    def fail(execute_state):
        if execute_state.session is db_session and state["armed"] and execute_state.is_select:
            raise SQLAlchemyError("injected post-commit read failure with raw database detail")

    event.listen(OrmSession, "after_commit", arm)
    event.listen(OrmSession, "do_orm_execute", fail)

    def remove():
        event.remove(OrmSession, "after_commit", arm)
        event.remove(OrmSession, "do_orm_execute", fail)

    return remove


def test_entry_response_is_captured_before_commit_and_survives_post_commit_read_fault(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    remove_fault = _fail_selects_after_this_session_commits(db_session)
    try:
        response = api_client.post(
            "/api/time-bank/entries",
            headers=ADMIN,
            json={
                "person_id": str(pm.id),
                "work_date": "2026-10-16",
                "start_minute": 540,
                "end_minute": 840,
                "lunch_taken": False,
                "calculation_mode": "standard",
            },
        )
    finally:
        remove_fault()

    assert response.status_code == 201, response.text
    assert response.json()["balance_seconds"] == 3600
    assert db_session.query(TimeBankEntry).count() == 1


def test_storage_flush_error_is_503_sanitized_and_rolls_back(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")

    def fail_entry_flush(session, _flush_context, _instances):
        if session is db_session and any(isinstance(item, TimeBankEntry) for item in session.new):
            raise SQLAlchemyError("raw SQL connection details must not escape")

    event.listen(OrmSession, "before_flush", fail_entry_flush)
    try:
        response = api_client.post(
            "/api/time-bank/entries",
            headers=ADMIN,
            json={
                "person_id": str(pm.id),
                "work_date": "2026-10-16",
                "start_minute": 540,
                "end_minute": 840,
                "lunch_taken": False,
                "calculation_mode": "standard",
            },
        )
    finally:
        event.remove(OrmSession, "before_flush", fail_entry_flush)

    assert response.status_code == 503
    assert "raw SQL" not in response.text
    assert db_session.query(TimeBankEntry).count() == 0


def test_all_time_bank_dtos_require_authentication(db_session, api_client):
    del db_session
    for path in (
        "/api/time-bank/people",
        "/api/time-bank/entries",
        "/api/time-bank/adjustments",
        "/api/time-bank/summary",
        f"/api/time-bank/imports/{uuid.uuid4()}",
    ):
        response = api_client.get(path)
        assert response.status_code == 401, (path, response.text)


def test_reader_scope_is_enforced_for_every_person_dto(db_session, api_client):
    other = _person(db_session, "Chefe Sintético")
    for path in (
        f"/api/time-bank/entries?person_id={other.id}",
        f"/api/time-bank/adjustments?person_id={other.id}",
        f"/api/time-bank/summary?person_id={other.id}&year=2026",
    ):
        response = api_client.get(path, headers=PM)
        assert response.status_code == 403, (path, response.text)


def test_combined_role_permissions_use_union_scope_without_granting_mutation(db_session, api_client):
    pm_user = db_session.query(User).filter(User.email == "pm.um.sintetico@example.invalid").one()
    view_all = db_session.query(Permission).filter(Permission.code == "time_bank.view_all").one()
    combined = Role(code="combined_time_bank_reader", name="Combined time bank reader")
    db_session.add(combined)
    db_session.flush()
    db_session.add_all([
        RolePermission(role_id=combined.id, permission_id=view_all.id),
        UserRole(user_id=pm_user.id, role_id=combined.id),
    ])
    db_session.flush()

    other = _person(db_session, "Chefe Sintético")
    listed = api_client.get(f"/api/time-bank/entries?person_id={other.id}", headers=PM)
    assert listed.status_code == 200
    denied_write = api_client.post(
        "/api/time-bank/adjustments",
        headers=PM,
        json={
            "person_id": str(other.id),
            "effective_date": "2026-10-20",
            "delta_seconds": 60,
            "kind": "correction",
            "reason": "Sem gestão.",
        },
    )
    assert denied_write.status_code == 403


def test_manual_body_validation_rejects_missing_value_atomically(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    response = api_client.post(
        "/api/time-bank/entries",
        headers=ADMIN,
        json={
            "person_id": str(pm.id),
            "work_date": "2026-10-18",
            "calculation_mode": "manual",
            "reason": "Motivo sem valor.",
        },
    )
    assert response.status_code == 422
    assert db_session.query(TimeBankEntry).count() == 0
    assert db_session.query(TimeBankAudit).count() == 0
