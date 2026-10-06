"""Fluxo de aprovação de férias (PR A)."""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from app.models.absence import Absence, STATUS_APROVADA
from app.models.people import Person
from app.models.project import Project
from app.utils.timezones import today_lisbon


STATUS_PENDENTE = "pendente"


def _headers(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _person(db, name: str) -> Person:
    return db.query(Person).filter(Person.display_name == name).one()


def _create(api_client, *, email: str, person_id, start: dt.date, end: dt.date, type_: str = "ferias"):
    return api_client.post(
        "/api/absences",
        json={
            "person_id": str(person_id),
            "start_date": str(start),
            "end_date": str(end),
            "type": type_,
        },
        headers=_headers(email),
    )


def test_pm_ferias_fica_pendente_e_nao_se_auto_aprova(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    start = today_lisbon() + dt.timedelta(days=90)
    created = _create(
        api_client,
        email="pm.um.sintetico@example.invalid",
        person_id=pm.id,
        start=start,
        end=start + dt.timedelta(days=3),
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == STATUS_PENDENTE
    assert body["decided_by_person_id"] is None
    assert body["can_approve"] is False
    assert api_client.patch(
        f"/api/absences/{body['id']}",
        json={"status": STATUS_APROVADA},
        headers=_headers("pm.um.sintetico@example.invalid"),
    ).status_code == 422


def test_chefe_cria_ferias_ja_aprovada_com_auditoria(db_session, api_client):
    chefe = _person(db_session, "Chefe Sintético")
    pm = _person(db_session, "PM Sintético Um")
    start = today_lisbon() + dt.timedelta(days=100)
    response = _create(
        api_client,
        email="chefe.sintetico@example.invalid",
        person_id=pm.id,
        start=start,
        end=start + dt.timedelta(days=2),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == STATUS_APROVADA
    assert body["decided_by_person_id"] == str(chefe.id)
    assert body["decided_at"] is not None


def test_baixa_medica_de_pm_fica_aprovada(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    start = today_lisbon() + dt.timedelta(days=110)
    response = _create(
        api_client,
        email="pm.um.sintetico@example.invalid",
        person_id=pm.id,
        start=start,
        end=start + dt.timedelta(days=1),
        type_="baixa_medica",
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == STATUS_APROVADA


def test_outro_de_pm_fica_aprovado(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    start = today_lisbon() + dt.timedelta(days=115)
    response = _create(
        api_client,
        email="pm.um.sintetico@example.invalid",
        person_id=pm.id,
        start=start,
        end=start + dt.timedelta(days=1),
        type_="outro",
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == STATUS_APROVADA


def test_administrador_tem_approvacao_automatica(db_session, api_client):
    admin = _person(db_session, "Admin Sintético")
    pm = _person(db_session, "PM Sintético Um")
    start = today_lisbon() + dt.timedelta(days=117)
    response = _create(
        api_client,
        email="admin.sintetico@example.invalid",
        person_id=pm.id,
        start=start,
        end=start + dt.timedelta(days=1),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == STATUS_APROVADA
    assert body["decided_by_person_id"] == str(admin.id)


def test_chefe_aprova_pendente_e_pm_recebe_403(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    start = today_lisbon() + dt.timedelta(days=120)
    created = _create(
        api_client,
        email="pm.um.sintetico@example.invalid",
        person_id=pm.id,
        start=start,
        end=start + dt.timedelta(days=2),
    )
    absence_id = created.json()["id"]

    denied = api_client.post(
        f"/api/absences/{absence_id}/approve",
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert denied.status_code == 403

    approved = api_client.post(
        f"/api/absences/{absence_id}/approve",
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == STATUS_APROVADA
    assert approved.json()["decided_by_display_name"] == "Chefe Sintético"
    assert approved.json()["can_approve"] is False


def test_rejeitar_exige_nota_e_rejeitada_e_final(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    start = today_lisbon() + dt.timedelta(days=130)
    created = _create(
        api_client,
        email="pm.um.sintetico@example.invalid",
        person_id=pm.id,
        start=start,
        end=start + dt.timedelta(days=1),
    )
    absence_id = created.json()["id"]
    headers = _headers("chefe.sintetico@example.invalid")

    assert api_client.post(f"/api/absences/{absence_id}/reject", json={}, headers=headers).status_code == 422
    rejected = api_client.post(
        f"/api/absences/{absence_id}/reject",
        json={"note": "A janela coincide com a disponibilidade da equipa."},
        headers=headers,
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejeitada"
    assert rejected.json()["decision_note"] == "A janela coincide com a disponibilidade da equipa."
    assert api_client.post(f"/api/absences/{absence_id}/cancel", headers=headers).status_code == 400


def test_cancelar_usando_endpoint_explicito_e_transicoes_finais(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    start = today_lisbon() + dt.timedelta(days=140)
    created = _create(
        api_client,
        email="pm.um.sintetico@example.invalid",
        person_id=pm.id,
        start=start,
        end=start + dt.timedelta(days=1),
    )
    assert created.status_code == 201, created.text
    created_body = created.json()
    absence_id = created_body["id"]
    assert created_body["decided_by_person_id"] is None
    assert created_body["decided_at"] is None
    cancelled = api_client.post(
        f"/api/absences/{absence_id}/cancel",
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert cancelled.status_code == 200, cancelled.text
    cancelled_body = cancelled.json()
    assert cancelled_body["status"] == "cancelada"
    assert cancelled_body["decided_by_person_id"] is None
    assert cancelled_body["decided_at"] is None
    assert cancelled_body["cancelled_by_person_id"] == str(pm.id)
    assert cancelled_body["cancelled_by_display_name"] == "PM Sintético Um"
    assert cancelled_body["cancelled_at"] is not None
    assert api_client.post(
        f"/api/absences/{absence_id}/cancel",
        headers=_headers("pm.um.sintetico@example.invalid"),
    ).status_code == 400


def test_cancelar_ferias_aprovada_preserva_decisao_e_regista_cancelamento(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    chefe = _person(db_session, "Chefe Sintético")
    start = today_lisbon() + dt.timedelta(days=145)
    created = _create(
        api_client,
        email="pm.um.sintetico@example.invalid",
        person_id=pm.id,
        start=start,
        end=start + dt.timedelta(days=1),
    )
    absence_id = created.json()["id"]

    approved = api_client.post(
        f"/api/absences/{absence_id}/approve",
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()
    decided_at = approved_body["decided_at"]
    assert approved_body["decided_by_person_id"] == str(chefe.id)

    cancelled = api_client.post(
        f"/api/absences/{absence_id}/cancel",
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert cancelled.status_code == 200, cancelled.text
    body = cancelled.json()
    assert body["status"] == "cancelada"
    assert body["decided_by_person_id"] == str(chefe.id)
    assert body["decided_by_display_name"] == "Chefe Sintético"
    assert body["decided_at"] == decided_at
    assert body["cancelled_by_person_id"] == str(pm.id)
    assert body["cancelled_by_display_name"] == "PM Sintético Um"
    assert body["cancelled_at"] is not None


def test_absencia_de_outra_pessoa_nao_visivel_e_404(db_session, api_client):
    chefe = _person(db_session, "Chefe Sintético")
    absence = Absence(
        person_id=chefe.id,
        start_date=today_lisbon() + dt.timedelta(days=150),
        end_date=today_lisbon() + dt.timedelta(days=151),
        status=STATUS_PENDENTE,
    )
    db_session.add(absence)
    db_session.commit()

    response = api_client.post(
        f"/api/absences/{absence.id}/approve",
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert response.status_code == 404


def test_aviso_de_obra_e_outra_ausencia_e_calculado_para_aprovador(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    start = today_lisbon() + dt.timedelta(days=160)
    db_session.add(
        Project(
            name="Projeto sintético com janela sobreposta",
            pm_person_id=pm.id,
            lifecycle_status="construcao",
            work_start_date=start + dt.timedelta(days=1),
            work_end_date=start + dt.timedelta(days=2),
            is_active=True,
        )
    )
    db_session.add(
        Absence(
            person_id=pm.id,
            start_date=start + dt.timedelta(days=1),
            end_date=start + dt.timedelta(days=3),
            status=STATUS_PENDENTE,
        )
    )
    db_session.commit()
    created = _create(
        api_client,
        email="pm.um.sintetico@example.invalid",
        person_id=pm.id,
        start=start,
        end=start + dt.timedelta(days=2),
    )
    assert created.status_code == 201

    rows = api_client.get(
        "/api/absences",
        headers=_headers("chefe.sintetico@example.invalid"),
    ).json()
    row = next(item for item in rows if item["id"] == created.json()["id"])
    assert row["overlapping_projects_count"] == 1
    assert row["overlapping_projects"][0]["name"] == "Projeto sintético com janela sobreposta"
    assert row["overlapping_absences_count"] == 1
    assert row["overlapping_absences"][0]["status"] == STATUS_PENDENTE


def test_aviso_de_obra_sem_estado_tambem_e_calculado(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    start = today_lisbon() + dt.timedelta(days=170)
    db_session.add(
        Project(
            name="Projeto sintético sem estado",
            pm_person_id=pm.id,
            lifecycle_status=None,
            work_start_date=start,
            work_end_date=start + dt.timedelta(days=2),
            is_active=True,
        )
    )
    db_session.flush()
    created = _create(
        api_client,
        email="pm.um.sintetico@example.invalid",
        person_id=pm.id,
        start=start,
        end=start + dt.timedelta(days=1),
    )
    assert created.status_code == 201
    rows = api_client.get(
        "/api/absences", headers=_headers("chefe.sintetico@example.invalid")
    ).json()
    row = next(item for item in rows if item["id"] == created.json()["id"])
    assert row["overlapping_projects_count"] == 1
    assert row["overlapping_projects"][0]["lifecycle_status"] is None


def test_dashboard_conta_pendentes_mas_nao_os_mostra_como_ausentes(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    start = today_lisbon()
    absence = Absence(
        person_id=pm.id,
        start_date=start,
        end_date=start + dt.timedelta(days=1),
        status=STATUS_PENDENTE,
    )
    db_session.add(absence)
    db_session.commit()

    dashboard = api_client.get(
        "/api/dashboard/summary",
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()
    assert body["pending_absences_count"] >= 1
    assert str(absence.id) not in {item["id"] for item in body["current_absences"]}
    assert all(day["people_absent_count"] >= 0 for day in body["week_overview"])

    pm_dashboard = api_client.get(
        "/api/dashboard/summary",
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert pm_dashboard.status_code == 200
    assert pm_dashboard.json()["pending_absences_count"] in (None, 0)


def _run_alembic(db_path: Path, *arguments: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _absence_columns(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        return {row[1] for row in connection.execute("PRAGMA table_info(absences)")}


def test_migracao_ferias_upgrade_downgrade_upgrade(tmp_path):
    db_path = tmp_path / "fa_mig.db"
    upgraded = _run_alembic(db_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    assert {"cancelled_by_person_id", "cancelled_at"} <= _absence_columns(db_path)

    downgraded = _run_alembic(db_path, "downgrade", "-1")
    assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
    downgraded_head = _run_alembic(db_path, "downgrade", "b4d8f2a6c1e3")
    assert downgraded_head.returncode == 0, downgraded_head.stdout + downgraded_head.stderr
    assert not {"cancelled_by_person_id", "cancelled_at"} & _absence_columns(db_path)

    upgraded_again = _run_alembic(db_path, "upgrade", "head")
    assert upgraded_again.returncode == 0, upgraded_again.stdout + upgraded_again.stderr
    assert {"cancelled_by_person_id", "cancelled_at"} <= _absence_columns(db_path)
