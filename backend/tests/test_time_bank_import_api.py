from __future__ import annotations

import datetime as dt
import io

import openpyxl
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as OrmSession

from app.models.people import Person
from app.models.time_bank import TimeBankEntry, TimeBankImportBatch


ADMIN = {"X-Dev-User-Email": "admin.sintetico@example.invalid"}


def _xlsx() -> bytes:
    workbook = openpyxl.Workbook()
    monthly = workbook.active
    monthly.title = "Janeiro"
    monthly.append(["Janeiro"])
    monthly.append(["Colaborador", "Weekday", "Data", "Hora de entrada", "Hora de almoço", "Hora de saída", "Balanço"])
    monthly.append(["Person Alpha", 2, dt.datetime(2026, 1, 5), 9, "sim", 18.5, 0])
    monthly.append(["Person Beta", 6, dt.datetime(2026, 1, 9), None, None, None, 1.5])
    summary = workbook.create_sheet("Balanço final")
    summary.append([2026])
    summary.append(["Mês", "Person Alpha", "Person Beta"])
    for _ in range(12):
        summary.append(["Mês", 0, 0])
    summary.append(["Total", 0, 0])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_preview_requires_explicit_people_resolution_then_apply_is_idempotent(db_session, api_client):
    file_content = _xlsx()
    preview = api_client.post(
        "/api/time-bank/imports/preview",
        headers=ADMIN,
        files={"file": ("synthetic.xlsx", file_content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["status"] == "pending"
    assert preview_body["counts"]["entries"] == 2
    assert any(issue["code"] == "person_unresolved" for issue in preview_body["issues"])
    batch_id = preview_body["id"]

    blocked = api_client.post(f"/api/time-bank/imports/{batch_id}/apply", headers=ADMIN)
    assert blocked.status_code == 409

    pm = db_session.query(Person).filter(Person.email == "pm.um.sintetico@example.invalid").one()
    chefe = db_session.query(Person).filter(Person.email == "chefe.sintetico@example.invalid").one()
    resolved = api_client.post(
        f"/api/time-bank/imports/{batch_id}/resolve",
        headers=ADMIN,
        json={"person_mapping": {"Person Alpha": str(pm.id), "Person Beta": str(chefe.id)}},
    )
    assert resolved.status_code == 200
    assert all(item["person_id"] is not None for item in resolved.json()["people"])

    applied = api_client.post(f"/api/time-bank/imports/{batch_id}/apply", headers=ADMIN)
    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"
    assert applied.json()["applied_counts"] == {"entries": 2, "openings": 0}
    assert db_session.query(TimeBankEntry).count() == 2

    replay = api_client.post(f"/api/time-bank/imports/{batch_id}/apply", headers=ADMIN)
    assert replay.status_code == 200
    assert replay.json()["applied_counts"] == {"entries": 2, "openings": 0}
    assert db_session.query(TimeBankEntry).count() == 2

    same_file = api_client.post(
        "/api/time-bank/imports/preview",
        headers=ADMIN,
        files={"file": ("renamed.xlsx", file_content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert same_file.status_code == 200
    assert same_file.json()["id"] == batch_id
    assert db_session.query(TimeBankImportBatch).count() == 1


def test_import_apply_response_is_captured_before_commit_and_survives_post_commit_read_fault(db_session, api_client):
    preview = api_client.post(
        "/api/time-bank/imports/preview",
        headers=ADMIN,
        files={"file": ("synthetic.xlsx", _xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert preview.status_code == 200, preview.text
    batch_id = preview.json()["id"]
    people = {
        "Person Alpha": str(db_session.query(Person).filter(Person.email == "pm.um.sintetico@example.invalid").one().id),
        "Person Beta": str(db_session.query(Person).filter(Person.email == "chefe.sintetico@example.invalid").one().id),
    }
    resolved = api_client.post(
        f"/api/time-bank/imports/{batch_id}/resolve",
        headers=ADMIN,
        json={"person_mapping": people},
    )
    assert resolved.status_code == 200, resolved.text

    state = {"armed": False}

    def arm(session):
        if session is db_session:
            state["armed"] = True

    def fail(execute_state):
        if execute_state.session is db_session and state["armed"] and execute_state.is_select:
            raise SQLAlchemyError("injected post-commit read failure with raw database detail")

    event.listen(OrmSession, "after_commit", arm)
    event.listen(OrmSession, "do_orm_execute", fail)
    try:
        applied = api_client.post(f"/api/time-bank/imports/{batch_id}/apply", headers=ADMIN)
    finally:
        event.remove(OrmSession, "after_commit", arm)
        event.remove(OrmSession, "do_orm_execute", fail)

    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    assert db_session.query(TimeBankEntry).count() == 2
