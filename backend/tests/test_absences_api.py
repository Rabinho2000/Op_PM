"""Endpoints de férias/ausências: criação, validação de datas, permissões
por perfil (ver visibility/manage matrix em app/security/catalog.py)."""
from __future__ import annotations

import datetime as dt

from app.models.absence import Absence
from app.models.people import Person
from app.models.project import Project


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
    assert resp.json()["status"] == "pendente"


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


def test_absence_work_warning_ignores_deleted_project_and_returns_after_restore(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    start = dt.date(2048, 5, 10)
    absence = Absence(person_id=pm.id, start_date=start, end_date=start + dt.timedelta(days=2))
    project = Project(
        name="Projeto Sintético para aviso de ausência",
        pm_person_id=pm.id,
        lifecycle_status="construcao",
        is_active=True,
        work_start_date=start,
        work_end_date=start + dt.timedelta(days=1),
    )
    db_session.add_all([absence, project])
    db_session.flush()

    def project_warnings() -> list[dict]:
        response = api_client.get(
            "/api/absences",
            params={"person_id": str(pm.id)},
            headers=_headers("admin.sintetico@example.invalid"),
        )
        assert response.status_code == 200, response.text
        row = next(item for item in response.json() if item["id"] == str(absence.id))
        return row["overlapping_projects"]

    assert [row["name"] for row in project_warnings()] == [project.name]

    deleted = api_client.request(
        "DELETE",
        f"/api/projects/{project.id}",
        json={"reason": "Teste de aviso de ausência"},
        headers=_headers("admin.sintetico@example.invalid"),
    )
    assert deleted.status_code == 204, deleted.text
    assert project_warnings() == []

    restored = api_client.post(
        f"/api/projects/{project.id}/restore", headers=_headers("admin.sintetico@example.invalid")
    )
    assert restored.status_code == 200, restored.text
    assert [row["name"] for row in project_warnings()] == [project.name]


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

    resp = api_client.post(
        f"/api/absences/{absence.id}/cancel",
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

    resp = api_client.post(
        f"/api/absences/{absence.id}/cancel",
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 404


def test_unauthenticated_request_is_rejected(api_client):
    resp = api_client.get("/api/absences")
    assert resp.status_code == 401
