"""Endpoints de férias/ausências: criação, validação de datas, permissões
por perfil (ver visibility/manage matrix em app/security/catalog.py)."""
from __future__ import annotations

import datetime as dt

from app.models.absence import Absence
from app.models.people import Person


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _person(db, name: str) -> Person:
    return db.query(Person).filter(Person.display_name == name).one()


def test_pm_can_register_own_absence(db_session, api_client):
    db = db_session
    pm = _person(db, "PM Sintético Um")
    today = dt.date.today()

    resp = api_client.post(
        "/api/absences",
        json={
            "person_id": str(pm.id),
            "start_date": str(today + dt.timedelta(days=30)),
            "end_date": str(today + dt.timedelta(days=35)),
            "type": "ferias",
        },
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "aprovada"


def test_pm_cannot_register_absence_for_someone_else(db_session, api_client):
    db = db_session
    chefe = _person(db, "Chefe Sintético")
    today = dt.date.today()

    resp = api_client.post(
        "/api/absences",
        json={
            "person_id": str(chefe.id),
            "start_date": str(today + dt.timedelta(days=1)),
            "end_date": str(today + dt.timedelta(days=2)),
        },
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 403


def test_chefe_can_register_absence_for_anyone(db_session, api_client):
    db = db_session
    pm = _person(db, "PM Sintético Um")
    today = dt.date.today()

    resp = api_client.post(
        "/api/absences",
        json={
            "person_id": str(pm.id),
            "start_date": str(today + dt.timedelta(days=1)),
            "end_date": str(today + dt.timedelta(days=2)),
        },
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 201


def test_end_date_before_start_date_is_rejected(db_session, api_client):
    db = db_session
    pm = _person(db, "PM Sintético Um")
    today = dt.date.today()

    resp = api_client.post(
        "/api/absences",
        json={
            "person_id": str(pm.id),
            "start_date": str(today + dt.timedelta(days=10)),
            "end_date": str(today + dt.timedelta(days=5)),
        },
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 400


def test_invalid_absence_type_is_rejected(db_session, api_client):
    db = db_session
    pm = _person(db, "PM Sintético Um")
    today = dt.date.today()

    resp = api_client.post(
        "/api/absences",
        json={
            "person_id": str(pm.id),
            "start_date": str(today),
            "end_date": str(today + dt.timedelta(days=1)),
            "type": "tipo_invalido",
        },
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 400


def test_pm_only_sees_own_absences(db_session, api_client):
    db = db_session
    resp = api_client.get("/api/absences", headers=_headers("pm.um.sintetico@example.invalid"))
    assert resp.status_code == 200
    person_ids = {a["person_id"] for a in resp.json()}
    pm = _person(db, "PM Sintético Um")
    assert person_ids <= {str(pm.id)}


def test_chefe_sees_all_absences(db_session, api_client):
    resp = api_client.get("/api/absences", headers=_headers("chefe.sintetico@example.invalid"))
    assert resp.status_code == 200
    assert len(resp.json()) >= 4  # ver app/migration/seed_dev.py:seed_absences


def test_pm_can_cancel_own_absence(db_session, api_client):
    db = db_session
    pm = _person(db, "PM Sintético Um")
    absence = Absence(
        person_id=pm.id,
        start_date=dt.date.today() + dt.timedelta(days=60),
        end_date=dt.date.today() + dt.timedelta(days=61),
    )
    db.add(absence)
    db.commit()

    resp = api_client.patch(
        f"/api/absences/{absence.id}",
        json={"status": "cancelada"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelada"


def test_pm_cannot_cancel_someone_elses_absence(db_session, api_client):
    db = db_session
    chefe = _person(db, "Chefe Sintético")
    absence = Absence(
        person_id=chefe.id,
        start_date=dt.date.today() + dt.timedelta(days=60),
        end_date=dt.date.today() + dt.timedelta(days=61),
    )
    db.add(absence)
    db.commit()

    resp = api_client.patch(
        f"/api/absences/{absence.id}",
        json={"status": "cancelada"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 403


def test_unauthenticated_request_is_rejected(api_client):
    resp = api_client.get("/api/absences")
    assert resp.status_code == 401
