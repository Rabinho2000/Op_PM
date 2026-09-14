"""Importação em staging com dados sintéticos — nunca dados reais nesta fase.

Cobre: dry-run sem rasto na base de dados, criação limpa, deteção de
duplicado/ambiguidade para revisão manual, preservação de campos incompletos,
e idempotência (reexecutar não duplica o que já foi ligado por ID externo).
"""
from __future__ import annotations

import json
from pathlib import Path

from app.migration.staging_import import SOURCE_LEGACY_JSON, run_staging_import
from app.models.project import Project, ProjectExternalId
from app.models.sync import SyncConflict

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_legacy_export.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_dry_run_creates_no_rows(db_session):
    db = db_session
    payload = _load_fixture()
    projects_before = db.query(Project).count()

    result = run_staging_import(db, payload=payload, mode="dry_run")

    assert result.sync_run.records_seen == 3
    # synth_p001 (primeira ocorrência do nome) e synth_p002 (nome único)
    # seriam criados; synth_p003 partilha o nome de synth_p001 e fica
    # marcado como possível duplicado para revisão manual.
    assert result.sync_run.records_created == 2
    assert result.sync_run.records_conflicted == 1
    assert db.query(Project).count() == projects_before
    assert db.query(SyncConflict).count() == 0  # dry-run não persiste conflitos


def test_apply_creates_project_and_preserves_incomplete_fields(db_session):
    db = db_session
    payload = {
        "projects": {
            "synth_only_p002": _load_fixture()["projects"]["synth_p002"],
        }
    }
    result = run_staging_import(db, payload=payload, mode="apply")

    assert result.sync_run.records_created == 1
    project = (
        db.query(Project)
        .join(ProjectExternalId, ProjectExternalId.project_id == Project.id)
        .filter(ProjectExternalId.source_system == SOURCE_LEGACY_JSON, ProjectExternalId.external_id == "synth_only_p002")
        .one()
    )
    assert project.name == "Instalação Fictícia Armazém Beta"
    # Campos incompletos preservados como None, nunca inventados.
    assert project.client_email is None
    assert project.lat is None
    assert project.lon is None
    assert project.pm_person_id is None


def test_apply_flags_ambiguous_names_for_manual_review(db_session):
    db = db_session
    payload = {
        "projects": {
            "synth_dup_a": {"name": "Nome Ambíguo Sintético", "pm": None, "contact": None, "email": None, "coords": None, "power": 1.0},
            "synth_dup_b": {"name": "Nome Ambíguo Sintético", "pm": None, "contact": None, "email": None, "coords": None, "power": 1.0},
        }
    }
    result = run_staging_import(db, payload=payload, mode="apply")

    assert result.sync_run.records_created == 1
    assert result.sync_run.records_conflicted == 1
    conflicts = db.query(SyncConflict).filter(SyncConflict.sync_run_id == result.sync_run.id).all()
    assert len(conflicts) == 1
    assert conflicts[0].status == "pending"
    assert conflicts[0].reason in ("ambiguous_match", "duplicate")


def test_reapplying_same_payload_is_idempotent_for_already_linked_projects(db_session):
    db = db_session
    payload = {
        "projects": {
            "synth_idempotent_001": {
                "name": "Instalação Sintética Idempotente",
                "pm": None,
                "contact": None,
                "email": None,
                "coords": None,
                "power": 3.3,
            }
        }
    }
    first = run_staging_import(db, payload=payload, mode="apply")
    assert first.sync_run.records_created == 1

    second = run_staging_import(db, payload=payload, mode="apply")
    assert second.sync_run.records_created == 0
    assert second.sync_run.records_updated == 1

    count = (
        db.query(Project)
        .join(ProjectExternalId, ProjectExternalId.project_id == Project.id)
        .filter(ProjectExternalId.external_id == "synth_idempotent_001")
        .count()
    )
    assert count == 1  # não duplicou o projeto na segunda execução
