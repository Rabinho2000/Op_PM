"""Migração em staging — ingestão persistente, revisão de conflitos,
promoção explícita, rollback. Sempre com dados sintéticos (ver
docs/DECISIONS.md D-017 para o desenho revisto na revisão de hardening).
"""
from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.db import SessionLocal
from app.migration.staging import (
    SOURCE_LEGACY_JSON,
    ingest_export,
    promote_staging_record,
    resolve_conflict,
    rollback_promotion,
)
from app.models.identity import User
from app.models.migration import ImportBatch, StagingProjectRecord
from app.models.project import Project, ProjectExternalId, ProjectHistory

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_legacy_export.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _actor(db):
    """ID da pessoa por trás do utilizador de desenvolvimento 'chefe', para
    usar como `actor_person_id` nas chamadas de staging."""
    user = db.query(User).filter(User.email == "chefe.sintetico@example.invalid").one()
    return user.person_id


# --------------------------------------------------------------------------
# Ingestão — persistente, nunca toca em `projects`.
# --------------------------------------------------------------------------


def test_ingest_never_writes_to_projects_table(db_session):
    db = db_session
    projects_before = db.query(Project).count()

    batch = ingest_export(db, payload=_load_fixture(), actor_person_id=_actor(db))

    assert db.query(Project).count() == projects_before
    assert batch.records_seen == 3


def test_ingest_is_persistent_across_a_later_rollback():
    """Ao contrário do antigo `dry_run` (que nunca persistia nada), a
    ingestão agora é sempre durável — um `rollback()` chamado depois não a
    desfaz, porque `ingest_export` já fez `commit()` internamente."""
    db = SessionLocal()
    try:
        batch = ingest_export(db, payload=_load_fixture())
        batch_id = batch.id
        db.rollback()  # não deve desfazer nada — já foi commitado
    finally:
        db.close()

    db2 = SessionLocal()
    try:
        reloaded = db2.get(ImportBatch, batch_id)
        assert reloaded is not None
        assert reloaded.records_seen == 3
        records = db2.query(StagingProjectRecord).filter(StagingProjectRecord.import_batch_id == batch_id).all()
        assert len(records) == 3
    finally:
        db2.rollback()
        db2.close()


def test_ingest_flags_within_batch_duplicate_as_conflict(db_session):
    db = db_session
    batch = ingest_export(db, payload=_load_fixture())

    records = {r.external_id: r for r in db.query(StagingProjectRecord).filter(
        StagingProjectRecord.import_batch_id == batch.id
    ).all()}

    # synth_p001 é a primeira ocorrência do nome -> limpo, pronto a promover.
    assert records["synth_p001"].status == "ready_to_promote"
    assert records["synth_p001"].resolved_action == "create_new"
    # synth_p002 tem nome único -> limpo.
    assert records["synth_p002"].status == "ready_to_promote"
    # synth_p003 repete o nome de synth_p001 -> conflito.
    assert records["synth_p003"].status == "conflict"
    assert records["synth_p003"].conflict_reason in ("ambiguous_match", "duplicate")
    assert batch.records_ready == 2
    assert batch.records_conflicted == 1


def test_ingest_preserves_raw_payload_verbatim(db_session):
    db = db_session
    original_payload = _load_fixture()
    batch = ingest_export(db, payload=original_payload)

    assert json.loads(batch.raw_payload_json) == original_payload

    record = (
        db.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == batch.id, StagingProjectRecord.external_id == "synth_p001")
        .one()
    )
    assert json.loads(record.raw_record_json) == original_payload["projects"]["synth_p001"]


def test_ingest_maps_all_relevant_legacy_fields(db_session):
    """Requisito: mapear PM, email, contacto, coordenadas, data de início,
    estado ClickUp, e os restantes campos relevantes do export legado."""
    db = db_session
    batch = ingest_export(db, payload=_load_fixture())
    record = (
        db.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == batch.id, StagingProjectRecord.external_id == "synth_p001")
        .one()
    )
    mapped = json.loads(record.mapped_fields_json)

    assert mapped["pm_name_raw"] == "PM Sintético Um"
    assert mapped["contact"] == "Cliente Fictício A"
    assert mapped["email"] == "cliente.ficticio.a@example.invalid"
    assert mapped["lat"] == 38.7
    assert mapped["lon"] == -9.1
    assert mapped["start_date_raw"] == "2026-02-10"
    assert mapped["clickup_status"] == "em execução"
    assert mapped["role"] == "instalador"
    assert mapped["equipment_notes"] == "Inversor Fictício X1, 12 painéis fictícios"
    assert mapped["injection_notes"] == "Injeção total fictícia"
    assert mapped["om_notes"] == "Contrato O&M fictício de 2 anos"
    assert mapped["commercial_assumptions"].startswith("Pressupostos comerciais fictícios")
    assert mapped["upac_registration"] == "UPAC-SYNTH-0001"
    assert mapped["m2m_card"] == "M2M-SYNTH-0001"
    assert mapped["upac_connection_date_raw"] == "2026-03-01"
    assert mapped["award_year_raw"] == "2026"
    assert mapped["power_raw"] == "10,50 kWp"


# --------------------------------------------------------------------------
# Promoção — só isto escreve em `projects`.
# --------------------------------------------------------------------------


def test_promote_create_new_applies_mapped_fields_to_project(db_session):
    db = db_session
    actor = _actor(db)
    batch = ingest_export(db, payload=_load_fixture(), actor_person_id=actor)
    record = (
        db.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == batch.id, StagingProjectRecord.external_id == "synth_p001")
        .one()
    )
    assert record.status == "ready_to_promote"

    project = promote_staging_record(db, staging_record_id=record.id, actor_person_id=actor)

    assert project.name == "Instalação Fictícia Quinta do Exemplo"
    assert project.client_contact == "Cliente Fictício A"
    assert project.client_email == "cliente.ficticio.a@example.invalid"
    assert project.lat == 38.7
    assert project.lon == -9.1
    assert project.power_raw == "10,50 kWp"
    assert project.power_kwp == pytest.approx(10.5)
    assert project.start_date == dt.date(2026, 2, 10)
    assert project.clickup_status_mirror == "em execução"
    assert project.role == "instalador"
    assert project.upac_registration == "UPAC-SYNTH-0001"
    assert project.m2m_card == "M2M-SYNTH-0001"
    assert project.upac_connection_date_raw == "2026-03-01"
    assert project.award_year_raw == "2026"

    # PM resolvido por nome exato contra o Person seedado.
    assert project.pm_person_id is not None
    assert project.pm.display_name == "PM Sintético Um"

    # Ligação externa criada.
    link = db.query(ProjectExternalId).filter(ProjectExternalId.project_id == project.id).one()
    assert link.source_system == SOURCE_LEGACY_JSON
    assert link.external_id == "synth_p001"

    # Registo de staging marcado como promovido.
    db.refresh(record)
    assert record.status == "promoted"
    assert record.promoted_project_id == project.id
    assert record.promoted_by_person_id == actor

    # Auditoria: uma entrada de histórico por campo não-nulo, todas
    # correlacionadas com este registo de staging.
    history = db.query(ProjectHistory).filter(ProjectHistory.project_id == project.id).all()
    assert len(history) > 5
    assert all(h.source == "import_legacy" for h in history)
    assert all(h.related_staging_record_id == record.id for h in history)
    assert all(h.old_value is None for h in history)


def test_promote_preserves_incomplete_fields_as_none(db_session):
    db = db_session
    actor = _actor(db)
    batch = ingest_export(db, payload=_load_fixture(), actor_person_id=actor)
    record = (
        db.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == batch.id, StagingProjectRecord.external_id == "synth_p002")
        .one()
    )
    project = promote_staging_record(db, staging_record_id=record.id, actor_person_id=actor)

    assert project.name == "Instalação Fictícia Armazém Beta"
    assert project.client_email is None
    assert project.client_contact is None
    assert project.lat is None
    assert project.lon is None
    assert project.power_kwp is None
    assert project.power_raw is None
    assert project.pm_person_id is None
    assert project.start_date is None


def test_promote_rejects_record_not_ready(db_session):
    db = db_session
    actor = _actor(db)
    batch = ingest_export(db, payload=_load_fixture(), actor_person_id=actor)
    conflicted = (
        db.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == batch.id, StagingProjectRecord.status == "conflict")
        .one()
    )
    with pytest.raises(ValueError, match="registo pronto"):
        promote_staging_record(db, staging_record_id=conflicted.id, actor_person_id=actor)


def test_power_raw_preserved_even_when_unparseable(db_session):
    db = db_session
    actor = _actor(db)
    payload = {"projects": {"synth_bad_power": {"name": "Projeto Sintético Potência Inválida", "power": "n/d"}}}
    batch = ingest_export(db, payload=payload, actor_person_id=actor)
    record = db.query(StagingProjectRecord).filter(StagingProjectRecord.import_batch_id == batch.id).one()
    project = promote_staging_record(db, staging_record_id=record.id, actor_person_id=actor)

    assert project.power_raw == "n/d"
    assert project.power_kwp is None


# --------------------------------------------------------------------------
# Revisão de conflitos + promoção subsequente.
# --------------------------------------------------------------------------


def test_resolve_conflict_then_promote_links_to_target_project(db_session):
    db = db_session
    actor = _actor(db)
    batch = ingest_export(db, payload=_load_fixture(), actor_person_id=actor)

    original = (
        db.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == batch.id, StagingProjectRecord.external_id == "synth_p001")
        .one()
    )
    duplicate = (
        db.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == batch.id, StagingProjectRecord.external_id == "synth_p003")
        .one()
    )
    assert duplicate.status == "conflict"
    assert duplicate.conflict_reason in ("ambiguous_match", "duplicate")

    canonical_project = promote_staging_record(db, staging_record_id=original.id, actor_person_id=actor)

    resolved = resolve_conflict(
        db,
        staging_record_id=duplicate.id,
        action="link_existing",
        target_project_id=canonical_project.id,
        actor_person_id=actor,
        note="Confirmado como o mesmo projeto físico.",
    )
    # synth_p003 tem pm="PM Sintético Dois", que não está seedado — o
    # conflito de nome fica resolvido, mas o registo permanece bloqueado
    # por PM não resolvido (D-023) até uma segunda decisão explícita.
    assert resolved.status == "conflict"
    assert resolved.conflict_reason == "pm_unresolved"

    resolved = resolve_conflict(
        db,
        staging_record_id=duplicate.id,
        action="proceed_without_pm",
        actor_person_id=actor,
        note="PM Sintético Dois não seedado neste teste — prosseguir sem PM.",
    )
    assert resolved.status == "ready_to_promote"

    result_project = promote_staging_record(db, staging_record_id=duplicate.id, actor_person_id=actor)
    assert result_project.id == canonical_project.id

    # Duas ligações externas diferentes (synth_p001, synth_p003) apontando
    # para o mesmo projeto canónico — intencional (duplicado na origem).
    links = db.query(ProjectExternalId).filter(ProjectExternalId.project_id == canonical_project.id).all()
    assert {link.external_id for link in links} == {"synth_p001", "synth_p003"}


def test_resolve_conflict_skip_rejects_record_and_blocks_promotion(db_session):
    db = db_session
    actor = _actor(db)
    batch = ingest_export(db, payload=_load_fixture(), actor_person_id=actor)
    duplicate = (
        db.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == batch.id, StagingProjectRecord.external_id == "synth_p003")
        .one()
    )

    resolved = resolve_conflict(db, staging_record_id=duplicate.id, action="skip", actor_person_id=actor)
    assert resolved.status == "rejected"

    with pytest.raises(ValueError, match="registo pronto"):
        promote_staging_record(db, staging_record_id=duplicate.id, actor_person_id=actor)


def test_resolve_conflict_rejects_non_conflicted_record(db_session):
    db = db_session
    actor = _actor(db)
    batch = ingest_export(db, payload=_load_fixture(), actor_person_id=actor)
    ready = (
        db.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == batch.id, StagingProjectRecord.status == "ready_to_promote")
        .first()
    )
    with pytest.raises(ValueError, match="conflito"):
        resolve_conflict(db, staging_record_id=ready.id, action="skip", actor_person_id=actor)


# --------------------------------------------------------------------------
# Idempotência: reingestão depois de uma promoção.
# --------------------------------------------------------------------------


def test_reingest_after_promotion_is_recognized_as_update_not_conflict(db_session):
    db = db_session
    actor = _actor(db)
    fixture = _load_fixture()

    first_batch = ingest_export(db, payload=fixture, actor_person_id=actor)
    record = (
        db.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == first_batch.id, StagingProjectRecord.external_id == "synth_p001")
        .one()
    )
    promote_staging_record(db, staging_record_id=record.id, actor_person_id=actor)

    second_batch = ingest_export(db, payload=fixture, actor_person_id=actor)
    reingested = (
        db.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == second_batch.id, StagingProjectRecord.external_id == "synth_p001")
        .one()
    )
    assert reingested.status == "ready_to_promote"
    assert reingested.resolved_action == "update_existing"


# --------------------------------------------------------------------------
# Rollback — nunca apaga histórico.
# --------------------------------------------------------------------------


def test_rollback_of_created_project_deactivates_and_preserves_history(db_session):
    db = db_session
    actor = _actor(db)
    batch = ingest_export(db, payload=_load_fixture(), actor_person_id=actor)
    record = (
        db.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == batch.id, StagingProjectRecord.external_id == "synth_p002")
        .one()
    )
    project = promote_staging_record(db, staging_record_id=record.id, actor_person_id=actor)
    assert project.is_active is True
    history_before = db.query(ProjectHistory).filter(ProjectHistory.project_id == project.id).count()

    reverted = rollback_promotion(
        db, staging_record_id=record.id, actor_person_id=actor, reason="Importado por engano (teste sintético)."
    )

    db.refresh(project)
    assert project.is_active is False
    assert reverted.status == "pending_review"
    assert reverted.reverted_at is not None
    assert reverted.reverted_by_person_id == actor

    history_after = db.query(ProjectHistory).filter(ProjectHistory.project_id == project.id).count()
    assert history_after == history_before + 1  # acrescentou, nunca apagou

    rollback_entry = (
        db.query(ProjectHistory)
        .filter(ProjectHistory.project_id == project.id, ProjectHistory.source == "migration_rollback")
        .one()
    )
    assert rollback_entry.field_name == "is_active"
    assert rollback_entry.new_value == "False"


def test_rollback_of_updated_project_restores_previous_field_value(db_session):
    db = db_session
    actor = _actor(db)
    fixture = _load_fixture()

    first_batch = ingest_export(db, payload=fixture, actor_person_id=actor)
    create_record = (
        db.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == first_batch.id, StagingProjectRecord.external_id == "synth_p001")
        .one()
    )
    project = promote_staging_record(db, staging_record_id=create_record.id, actor_person_id=actor)
    original_contact = project.client_contact
    assert original_contact == "Cliente Fictício A"

    updated_fixture = json.loads(json.dumps(fixture))  # cópia profunda
    updated_fixture["projects"]["synth_p001"]["contact"] = "Cliente Fictício A (atualizado)"
    second_batch = ingest_export(db, payload=updated_fixture, actor_person_id=actor)
    update_record = (
        db.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == second_batch.id, StagingProjectRecord.external_id == "synth_p001")
        .one()
    )
    assert update_record.resolved_action == "update_existing"

    promote_staging_record(db, staging_record_id=update_record.id, actor_person_id=actor)
    db.refresh(project)
    assert project.client_contact == "Cliente Fictício A (atualizado)"

    rollback_promotion(db, staging_record_id=update_record.id, actor_person_id=actor, reason="Teste de rollback de atualização.")
    db.refresh(project)
    assert project.client_contact == original_contact

    # Nenhuma entrada de histórico anterior foi apagada — só acrescentadas.
    all_history = (
        db.query(ProjectHistory)
        .filter(ProjectHistory.project_id == project.id, ProjectHistory.field_name == "client_contact")
        .order_by(ProjectHistory.changed_at.asc())
        .all()
    )
    assert len(all_history) >= 3  # criação, atualização, rollback
    values_seen = [h.new_value for h in all_history]
    assert "Cliente Fictício A (atualizado)" in values_seen
    assert values_seen[-1] == original_contact


def test_rollback_only_allowed_for_promoted_records(db_session):
    db = db_session
    actor = _actor(db)
    batch = ingest_export(db, payload=_load_fixture(), actor_person_id=actor)
    not_promoted = (
        db.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == batch.id, StagingProjectRecord.status == "ready_to_promote")
        .first()
    )
    with pytest.raises(ValueError, match="promovido"):
        rollback_promotion(db, staging_record_id=not_promoted.id, actor_person_id=actor, reason="teste")
