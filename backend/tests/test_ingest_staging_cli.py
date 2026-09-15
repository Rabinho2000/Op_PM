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

from app.cli.ingest_staging import (
    IngestionError,
    assert_file_is_not_trackable_by_git,
    assert_staging_only_environment,
    run_ingestion,
)
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


# --------------------------------------------------------------------------
# Piloto de staging (docs/STAGING_RUNBOOK.md): dry-run, --only-ids, --limit.
# --------------------------------------------------------------------------


def test_dry_run_leaves_no_trace_in_staging_tables(db_session):
    db = db_session
    batches_before = db.query(ImportBatch).count()

    batch, summary = run_ingestion(
        db, payload=_load_fixture(), source_system="legacy_json", actor_email=None, dry_run=True
    )
    assert summary["projects_seen"] == 3  # o resumo continua correto antes do rollback
    db.rollback()  # o mesmo que main() faz depois de ler o resumo

    assert db.query(ImportBatch).count() == batches_before
    assert db.get(ImportBatch, batch.id) is None


def test_only_ids_restricts_to_the_requested_subset(db_session):
    db = db_session
    batch, summary = run_ingestion(
        db,
        payload=_load_fixture(),
        source_system="legacy_json",
        actor_email=None,
        only_ids="synth_p001,synth_p002",
    )
    assert summary["projects_seen"] == 2
    assert batch.records_seen == 2


def test_limit_restricts_to_the_first_n_projects(db_session):
    db = db_session
    _batch, summary = run_ingestion(
        db, payload=_load_fixture(), source_system="legacy_json", actor_email=None, limit=1
    )
    assert summary["projects_seen"] == 1


def test_only_ids_and_limit_combine(db_session):
    db = db_session
    _batch, summary = run_ingestion(
        db,
        payload=_load_fixture(),
        source_system="legacy_json",
        actor_email=None,
        only_ids="synth_p001,synth_p002,synth_p003",
        limit=2,
    )
    assert summary["projects_seen"] == 2


def test_dry_run_combines_with_only_ids_for_a_pilot_preview(db_session):
    db = db_session
    _batch, summary = run_ingestion(
        db,
        payload=_load_fixture(),
        source_system="legacy_json",
        actor_email=None,
        only_ids="synth_p001",
        dry_run=True,
    )
    assert summary["projects_seen"] == 1
    db.rollback()
    assert db.query(ImportBatch).count() == 0


# --------------------------------------------------------------------------
# Barreira: nunca ler um export que o Git conseguiria apanhar (D-037/piloto).
# --------------------------------------------------------------------------


def test_assert_file_is_not_trackable_by_git_allows_paths_outside_any_repo(tmp_path):
    outside_file = tmp_path / "export_real.json"
    outside_file.write_text("{}", encoding="utf-8")
    assert_file_is_not_trackable_by_git(outside_file)  # não levanta


def test_assert_file_is_not_trackable_by_git_allows_gitignored_paths():
    # backend/data/ está coberto pelo .gitignore da raiz do repositório.
    ignored_path = Path(__file__).resolve().parents[1] / "data" / "_test_export_pilot.json"
    ignored_path.parent.mkdir(parents=True, exist_ok=True)
    ignored_path.write_text("{}", encoding="utf-8")
    try:
        assert_file_is_not_trackable_by_git(ignored_path)  # não levanta
    finally:
        ignored_path.unlink(missing_ok=True)


def _git_check_ignore_plumbing_is_conclusive() -> bool:
    """Algumas instalações do Git para Windows corrompem argumentos
    não-ASCII passados via `subprocess` quando o caminho do repositório
    tem carateres acentuados (mojibake na conversão UTF-16→ANSI do MSYS2) —
    `git check-ignore` devolve 128 (erro) em vez de 0/1. Nesse caso,
    `assert_file_is_not_trackable_by_git` falha sempre "aberto" (nunca
    bloqueia por um erro do Git), por isso o teste de rejeição não consegue
    exercitar o caminho positivo aqui — mas continua a fazê-lo normalmente
    em qualquer ambiente com caminhos ASCII (incl. o CI em Linux)."""
    import subprocess

    repo_root = Path(__file__).resolve().parents[2]
    known_tracked = repo_root / "README.md"
    result = subprocess.run(
        ["git", "-C", str(repo_root), "check-ignore", "-q", "--", str(known_tracked)],
        capture_output=True,
        timeout=5,
    )
    return result.returncode in (0, 1)


def test_assert_file_is_not_trackable_by_git_rejects_a_tracked_path():
    if not _git_check_ignore_plumbing_is_conclusive():
        pytest.skip(
            "git check-ignore não devolve um resultado conclusivo neste ambiente "
            "(caminho não-ASCII + Git para Windows — ver docstring de "
            "_git_check_ignore_plumbing_is_conclusive); corre normalmente no CI (Linux)."
        )
    # backend/fixtures/ nunca está no .gitignore — é onde vivem as fixtures
    # sintéticas versionadas, por isso serve aqui como caminho NÃO ignorado.
    tracked_path = FIXTURE_PATH
    with pytest.raises(IngestionError, match="NÃO está coberto pelo"):
        assert_file_is_not_trackable_by_git(tracked_path)
