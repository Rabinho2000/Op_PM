"""Licenciamento: estado derivado por etapa, campo do certificado provisório,
leitura pela API e migração b2d4f6a8c0e1 (upgrade/downgrade/upgrade em SQLite).
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app.models.project import Project
from app.models.project_data import ProjectLicensingData
from app.services.project_data import derive_licensing_state

CHEFE = "chefe.sintetico@example.invalid"
BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS_HEAD = "a1c3e5f7b9d2"
THIS_REVISION = "b2d4f6a8c0e1"


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _own_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


def _other_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()


def test_derive_licensing_state_each_stage():
    assert derive_licensing_state(None) == "sem_registo"
    assert derive_licensing_state(ProjectLicensingData()) == "sem_registo"
    stages = [
        ("registration_date", "cadastrado"),
        ("certification_request_date", "certificacao_pedida"),
        ("inspection_date", "inspecionado"),
        ("provisional_certificate_date", "certificado_provisorio"),
        ("certificate_date", "certificado_definitivo"),
    ]
    import datetime as dt

    data = ProjectLicensingData()
    for field, expected in stages:
        setattr(data, field, dt.date(2026, 1, 1))
        assert derive_licensing_state(data) == expected


def test_derive_licensing_state_uses_most_advanced_stage_not_order_of_entry():
    import datetime as dt

    data = ProjectLicensingData()
    data.certificate_date = dt.date(2026, 3, 1)
    data.registration_date = dt.date(2026, 1, 1)
    assert derive_licensing_state(data) == "certificado_definitivo"
    data.certificate_date = None
    data.inspection_date = dt.date(2026, 2, 1)
    assert derive_licensing_state(data) == "inspecionado"


def test_licensing_read_exposes_derived_state_and_provisional_date(db_session, api_client):
    project = _own_project(db_session)
    headers = _headers(CHEFE)
    resp = api_client.patch(
        f"/api/projects/{project.id}/licensing-data",
        json={"registration_date": "2026-01-10", "provisional_certificate_date": "2026-04-02"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["licensing_state"] == "certificado_provisorio"
    assert resp.json()["provisional_certificate_date"] == "2026-04-02"

    got = api_client.get(f"/api/projects/{project.id}/licensing-data", headers=headers)
    assert got.json()["licensing_state"] == "certificado_provisorio"


def test_licensing_state_without_record_is_sem_registo(db_session, api_client):
    other = _other_project(db_session)
    resp = api_client.get(f"/api/projects/{other.id}/licensing-data", headers=_headers(CHEFE))
    assert resp.status_code == 200
    assert resp.json()["licensing_state"] == "sem_registo"




def _run_alembic(database_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "APP_ENV": "test",
            "AUTH_ENABLED": "false",
            "DATABASE_URL": f"sqlite:///{database_path}",
            "EXPECTED_DB_DIALECT": "sqlite",
        }
    )
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _columns(database_path: Path, table: str) -> set[str]:
    with sqlite3.connect(database_path) as connection:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def _tables(database_path: Path) -> set[str]:
    with sqlite3.connect(database_path) as connection:
        return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _permission_grants(database_path: Path) -> set[tuple[str, str]]:
    with sqlite3.connect(database_path) as connection:
        return set(
            connection.execute(
                "SELECT p.code, r.code FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id "
                "JOIN roles r ON r.id = rp.role_id WHERE p.code LIKE 'project.credentials.%'"
            ).fetchall()
        )


def _version(database_path: Path) -> str:
    with sqlite3.connect(database_path) as connection:
        return connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def test_migration_b2d4_upgrade_downgrade_upgrade_on_sqlite(tmp_path: Path):
    database_path = tmp_path / "licensing-migration.db"
    assert _run_alembic(database_path, "upgrade", PREVIOUS_HEAD).returncode == 0
    assert "project_portal_credentials" not in _tables(database_path)
    assert "whereversim_login" not in _columns(database_path, "project_communication_data")
    # Papéis como os de produção (o seed concede o catálogo; a migração concede
    # só às funções fixadas. Sem papéis, não há nada a conceder).
    with sqlite3.connect(database_path) as connection:
        for code in ("administrador", "chefe_operacoes", "project_manager"):
            connection.execute(
                "INSERT INTO roles (id, code, name, description) VALUES (?, ?, ?, '')",
                (str(uuid.uuid4()), code, code),
            )
        connection.commit()

    # Alvo fixo: esta revisão. A c3e5a7b9d1f2 (SIMs) tem o seu próprio teste.
    up = _run_alembic(database_path, "upgrade", THIS_REVISION)
    assert up.returncode == 0, up.stdout + up.stderr
    assert _version(database_path) == THIS_REVISION
    assert {"project_portal_credentials", "project_surplus_contracts"} <= _tables(database_path)
    assert "provisional_certificate_date" in _columns(database_path, "project_licensing_data")
    assert {"whereversim_login", "operator_verified", "operator_verified_date"} <= _columns(
        database_path, "project_communication_data"
    )
    assert "record_id" in _columns(database_path, "project_data_history")
    grants_up = _permission_grants(database_path)
    assert grants_up == {
        ("project.credentials.edit", "administrador"),
        ("project.credentials.edit", "chefe_operacoes"),
        ("project.credentials.edit", "project_manager"),
        ("project.credentials.reveal", "administrador"),
        ("project.credentials.reveal", "chefe_operacoes"),
        ("project.credentials.reveal", "project_manager"),
    }

    down = _run_alembic(database_path, "downgrade", PREVIOUS_HEAD)
    assert down.returncode == 0, down.stdout + down.stderr
    assert _version(database_path) == PREVIOUS_HEAD
    assert "project_portal_credentials" not in _tables(database_path)
    assert "project_surplus_contracts" not in _tables(database_path)
    assert "provisional_certificate_date" not in _columns(database_path, "project_licensing_data")
    assert "whereversim_login" not in _columns(database_path, "project_communication_data")
    assert "record_id" not in _columns(database_path, "project_data_history")
    assert _permission_grants(database_path) == set()

    again = _run_alembic(database_path, "upgrade", THIS_REVISION)
    assert again.returncode == 0, again.stdout + again.stderr
    assert _version(database_path) == THIS_REVISION
    assert len(_permission_grants(database_path)) == 6
