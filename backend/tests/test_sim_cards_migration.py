"""Migração c3e5a7b9d1f2 (cartões SIM como lista + PIN/PUK cifrados) em SQLite:
upgrade/downgrade/upgrade com data migration, e recusa de downgrade com PIN/PUK.

Usa a base de cada teste (tmp_path) — nunca a base da suite nem dados reais.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS = "b2d4f6a8c0e1"
HEAD = "c3e5a7b9d1f2"

WITH_SIM = str(uuid.UUID("00000000-0000-0000-0000-0000000000a1"))
WITHOUT_SIM = str(uuid.UUID("00000000-0000-0000-0000-0000000000a2"))


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


def _version(database_path: Path) -> str:
    with sqlite3.connect(database_path) as c:
        return c.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def _columns(database_path: Path, table: str) -> set[str]:
    with sqlite3.connect(database_path) as c:
        return {row[1] for row in c.execute(f"PRAGMA table_info({table})")}


def _tables(database_path: Path) -> set[str]:
    with sqlite3.connect(database_path) as c:
        return {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _insert_projects_before_migration(database_path: Path) -> None:
    """Dois projetos mínimos: um com SIM nos campos antigos, outro sem nada."""
    with sqlite3.connect(database_path) as c:
        for project_id, name in ((WITH_SIM, "Projeto SIM sintético"), (WITHOUT_SIM, "Projeto sem SIM sintético")):
            c.execute(
                "INSERT INTO projects (id, name, is_active, notes, work_dates_estimated) VALUES (?, ?, 1, '', 0)",
                (project_id, name),
            )
            c.execute(
                "INSERT INTO project_communication_data (id, project_id, notes) VALUES (?, ?, '')",
                (str(uuid.uuid4()), project_id),
            )
        c.execute(
            "UPDATE project_communication_data SET operator = ?, gsm_m2m_number = ?, card_identifier = ?, "
            "operator_verified = 1, operator_verified_date = '2026-01-02' WHERE project_id = ?",
            ("Operador Sintético", "910000001", "ICCID-SINTETICO-1", WITH_SIM),
        )
        c.commit()


def _sim_rows(database_path: Path) -> list[tuple]:
    with sqlite3.connect(database_path) as c:
        return c.execute(
            "SELECT project_id, purpose, operator, phone_number, iccid, verified_on_portal, verified_date, "
            "pin_encrypted, puk_encrypted, deleted_at FROM project_sim_cards ORDER BY project_id"
        ).fetchall()


def _comm_row(database_path: Path, project_id: str) -> tuple:
    with sqlite3.connect(database_path) as c:
        return c.execute(
            "SELECT operator, gsm_m2m_number, card_identifier, operator_verified, operator_verified_date "
            "FROM project_communication_data WHERE project_id = ?",
            (project_id,),
        ).fetchone()


def test_sim_cards_migration_up_down_up_with_data(tmp_path: Path):
    database_path = tmp_path / "sim-migration.db"
    assert _run_alembic(database_path, "upgrade", PREVIOUS).returncode == 0
    _insert_projects_before_migration(database_path)

    # UP — data migration: 1 linha só para o projeto com SIM; o outro não gera nada.
    up = _run_alembic(database_path, "upgrade", HEAD)
    assert up.returncode == 0, up.stdout + up.stderr
    assert _version(database_path) == HEAD
    assert "project_sim_cards" in _tables(database_path)
    rows = _sim_rows(database_path)
    assert len(rows) == 1
    project_id, purpose, operator, phone, iccid, verified, verified_date, pin, puk, deleted_at = rows[0]
    assert project_id == WITH_SIM
    assert (purpose, operator, phone, iccid) == ("comunicacoes", "Operador Sintético", "910000001", "ICCID-SINTETICO-1")
    assert verified == 1 and str(verified_date) == "2026-01-02"
    assert pin is None and puk is None and deleted_at is None
    for column in ("operator", "gsm_m2m_number", "card_identifier", "operator_verified", "operator_verified_date"):
        assert column not in _columns(database_path, "project_communication_data")
    assert "email" in _columns(database_path, "project_portal_credentials")
    assert "upac_registration_date" in _columns(database_path, "project_licensing_data")

    # DOWN — repõe as colunas antigas com o primeiro SIM de cada projeto.
    down = _run_alembic(database_path, "downgrade", PREVIOUS)
    assert down.returncode == 0, down.stdout + down.stderr
    assert _version(database_path) == PREVIOUS
    assert "project_sim_cards" not in _tables(database_path)
    assert _comm_row(database_path, WITH_SIM) == ("Operador Sintético", "910000001", "ICCID-SINTETICO-1", 1, "2026-01-02")
    assert _comm_row(database_path, WITHOUT_SIM) == (None, None, None, None, None)

    # UP outra vez — volta a produzir a mesma linha.
    again = _run_alembic(database_path, "upgrade", HEAD)
    assert again.returncode == 0, again.stdout + again.stderr
    assert _version(database_path) == HEAD
    assert [r[0] for r in _sim_rows(database_path)] == [WITH_SIM]


def test_downgrade_refuses_when_pin_or_puk_would_be_lost(tmp_path: Path):
    database_path = tmp_path / "sim-migration-secrets.db"
    assert _run_alembic(database_path, "upgrade", PREVIOUS).returncode == 0
    _insert_projects_before_migration(database_path)
    assert _run_alembic(database_path, "upgrade", HEAD).returncode == 0

    # Token falso: a migração só verifica a presença, nunca decifra.
    with sqlite3.connect(database_path) as c:
        c.execute("UPDATE project_sim_cards SET puk_encrypted = 'token-sintetico-nao-decifrado'")
        c.commit()

    refused = _run_alembic(database_path, "downgrade", PREVIOUS)
    assert refused.returncode != 0
    assert "PIN/PUK" in (refused.stdout + refused.stderr)
    assert _version(database_path) == HEAD  # nada foi revertido
    assert "project_sim_cards" in _tables(database_path)
    assert len(_sim_rows(database_path)) == 1

    # Sem segredos guardados, o downgrade passa.
    with sqlite3.connect(database_path) as c:
        c.execute("UPDATE project_sim_cards SET puk_encrypted = NULL, pin_encrypted = NULL")
        c.commit()
    down = _run_alembic(database_path, "downgrade", PREVIOUS)
    assert down.returncode == 0, down.stdout + down.stderr
    assert _version(database_path) == PREVIOUS
