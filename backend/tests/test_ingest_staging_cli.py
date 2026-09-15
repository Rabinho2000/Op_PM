"""Ingestão controlada para staging (D-037) —
`app/cli/ingest_staging.py`. Testa sempre `run_ingestion`/
`assert_staging_only_environment`/`_resolve_actor_person_id` diretamente
(o mesmo núcleo que `main()` chama), nunca a CLI/argparse. Fixtures
exclusivamente sintéticas (`backend/fixtures/synthetic_legacy_export.json`).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cli.ingest_staging import IngestionError, assert_staging_only_environment, run_ingestion
from app.models.identity import User
from app.models.migration import ImportBatch
from app.models.project import Project

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_legacy_export.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Modo staging-only (D-037).
# --------------------------------------------------------------------------


def test_assert_staging_only_environment_rejects_production():
    with pytest.raises(IngestionError, match="staging-only"):
        assert_staging_only_environment("production")


@pytest.mark.parametrize("app_env", ["local", "test", "staging"])
def test_assert_staging_only_environment_allows_everything_else(app_env):
    assert_staging_only_environment(app_env)  # não levanta


# --------------------------------------------------------------------------
# run_ingestion — nunca toca em 'projects', preserva o payload, resumo correto.
# --------------------------------------------------------------------------


def test_run_ingestion_never_writes_to_projects(db_session):
    db = db_session
    projects_before = db.query(Project).count()

    batch, _summary = run_ingestion(
        db, payload=_load_fixture(), source_system="legacy_json", actor_email=None
    )

    assert db.query(Project).count() == projects_before
    assert batch.records_seen == 3


def test_run_ingestion_preserves_raw_payload_verbatim(db_session):
    db = db_session
    fixture = _load_fixture()

    batch, _summary = run_ingestion(db, payload=fixture, source_system="legacy_json", actor_email=None)

    reloaded = db.get(ImportBatch, batch.id)
    assert json.loads(reloaded.raw_payload_json) == fixture


def test_run_ingestion_summary_counts_match_the_fixture(db_session):
    db = db_session
    _batch, summary = run_ingestion(db, payload=_load_fixture(), source_system="legacy_json", actor_email=None)

    # Fixture: 3 projetos; 2 têm PM distinto ('PM Sintético Um', 'PM
    # Sintético Dois' — synth_p002 não tem PM); 2 têm email; 2 têm contacto;
    # 2 têm coordenadas (lat e lon).
    assert summary["projects_seen"] == 3
    assert summary["distinct_pm_names"] == 2
    assert summary["with_email"] == 2
    assert summary["with_contact"] == 2
    assert summary["with_coordinates"] == 2
    assert summary["ready_to_promote"] + summary["conflicts"] == 3


def test_run_ingestion_resolves_actor_by_email(db_session):
    db = db_session
    user = db.query(User).filter(User.email == "chefe.sintetico@example.invalid").one()

    batch, _summary = run_ingestion(
        db, payload=_load_fixture(), source_system="legacy_json", actor_email=user.email
    )

    assert batch.started_by_person_id == user.person_id


def test_run_ingestion_rejects_unknown_actor_email(db_session):
    db = db_session
    with pytest.raises(IngestionError, match="nenhum utilizador ATIVO"):
        run_ingestion(
            db,
            payload=_load_fixture(),
            source_system="legacy_json",
            actor_email="ninguem.assim@example.invalid",
        )


def test_run_ingestion_works_without_an_actor_email(db_session):
    db = db_session
    batch, _summary = run_ingestion(db, payload=_load_fixture(), source_system="legacy_json", actor_email=None)
    assert batch.started_by_person_id is None
