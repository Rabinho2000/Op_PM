"""Reconciliação de pessoas/PMs — etapa explícita antes da migração de
projetos (D-023). Cobre os quatro requisitos pedidos: preservar PMs
históricos como Person, só associar User a utilizadores ativos, enviar
nomes desconhecidos/ambíguos para revisão, e nunca promover um projeto
com PM conhecido mas não resolvido.
"""
from __future__ import annotations

import json

import pytest

from app.migration.people_reconciliation import (
    classify_pm_name,
    reconcile_pm_names,
    resolve_person_reconciliation,
)
from app.migration.staging import ingest_export, promote_staging_record, resolve_conflict, retry_pm_resolution
from app.models.identity import User
from app.models.migration import PersonReconciliationItem, StagingProjectRecord
from app.models.people import Person


def _actor(db):
    user = db.query(User).filter(User.email == "chefe.sintetico@example.invalid").one()
    return user.person_id


# --------------------------------------------------------------------------
# classify_pm_name
# --------------------------------------------------------------------------


def test_classify_empty_or_missing_name(db_session):
    db = db_session
    assert classify_pm_name(db, None).status == "empty"
    assert classify_pm_name(db, "").status == "empty"
    assert classify_pm_name(db, "   ").status == "empty"


def test_classify_resolved_name_matches_seeded_person(db_session):
    db = db_session
    result = classify_pm_name(db, "PM Sintético Um")
    assert result.status == "resolved"
    assert result.person is not None
    assert result.person.display_name == "PM Sintético Um"


def test_classify_unknown_name_is_unresolved_with_no_candidates(db_session):
    db = db_session
    result = classify_pm_name(db, "Nome Completamente Desconhecido Sintético")
    assert result.status == "unresolved"
    assert result.candidate_person_ids == []


def test_classify_ambiguous_name_is_unresolved_with_candidates(db_session):
    db = db_session
    p1 = Person(display_name="PM Ambíguo Sintético")
    p2 = Person(display_name="PM Ambíguo Sintético")
    db.add_all([p1, p2])
    db.flush()

    result = classify_pm_name(db, "PM Ambíguo Sintético")
    assert result.status == "unresolved"
    assert len(result.candidate_person_ids) == 2


# --------------------------------------------------------------------------
# reconcile_pm_names — fila de revisão
# --------------------------------------------------------------------------


def test_reconcile_queues_unknown_and_ambiguous_names_only(db_session):
    db = db_session
    payload = {
        "projects": {
            "p1": {"name": "Projeto Sintético 1", "pm": "PM Sintético Um"},  # resolvido, não entra na fila
            "p2": {"name": "Projeto Sintético 2", "pm": "PM Reconciliação Desconhecido"},  # desconhecido
            "p3": {"name": "Projeto Sintético 3", "pm": None},  # sem PM, ignorado
            "p4": {"name": "Projeto Sintético 4", "pm": ""},  # sem PM, ignorado
        }
    }
    summary = reconcile_pm_names(db, payload=payload)
    assert summary["created"] == 1
    assert summary["already_resolved"] == 1

    items = db.query(PersonReconciliationItem).filter(
        PersonReconciliationItem.normalized_name == "pm reconciliação desconhecido"
    ).all()
    assert len(items) == 1
    assert items[0].reason == "unknown"
    assert items[0].status == "pending"


def test_reconcile_is_idempotent_for_the_same_name(db_session):
    db = db_session
    payload = {"projects": {"p1": {"name": "Projeto Sintético", "pm": "PM Repetido Sintético"}}}
    reconcile_pm_names(db, payload=payload)
    summary_second = reconcile_pm_names(db, payload=payload)

    assert summary_second["created"] == 0
    assert summary_second["already_open"] == 1
    items = db.query(PersonReconciliationItem).filter(
        PersonReconciliationItem.normalized_name == "pm repetido sintético"
    ).all()
    assert len(items) == 1  # nunca duplica


# --------------------------------------------------------------------------
# resolve_person_reconciliation
# --------------------------------------------------------------------------


def test_resolve_link_existing(db_session):
    db = db_session
    actor = _actor(db)
    reconcile_pm_names(db, payload={"projects": {"p1": {"name": "P", "pm": "PM Para Ligar Sintético"}}})
    item = db.query(PersonReconciliationItem).filter(
        PersonReconciliationItem.normalized_name == "pm para ligar sintético"
    ).one()
    target = db.query(Person).filter(Person.display_name == "PM Sintético Um").one()

    resolved = resolve_person_reconciliation(
        db, item_id=item.id, action="link_existing", actor_person_id=actor, target_person_id=target.id
    )
    assert resolved.status == "resolved"
    assert resolved.resolved_person_id == target.id


def test_resolve_create_new_person_has_no_user_and_is_inactive(db_session):
    """Requisito: 'associar User apenas aos utilizadores ativos' — uma
    Person criada por reconciliação nunca vem com User nem ativa por
    omissão."""
    db = db_session
    actor = _actor(db)
    reconcile_pm_names(db, payload={"projects": {"p1": {"name": "P", "pm": "PM Novo Sintético Legado"}}})
    item = db.query(PersonReconciliationItem).filter(
        PersonReconciliationItem.normalized_name == "pm novo sintético legado"
    ).one()

    resolved = resolve_person_reconciliation(db, item_id=item.id, action="create_new", actor_person_id=actor)
    assert resolved.status == "created_new"

    new_person = db.get(Person, resolved.resolved_person_id)
    assert new_person.display_name == "PM Novo Sintético Legado"
    assert new_person.is_active is False
    assert new_person.user is None


def test_resolve_ignore(db_session):
    db = db_session
    actor = _actor(db)
    reconcile_pm_names(db, payload={"projects": {"p1": {"name": "P", "pm": "PM Para Ignorar Sintético"}}})
    item = db.query(PersonReconciliationItem).filter(
        PersonReconciliationItem.normalized_name == "pm para ignorar sintético"
    ).one()

    resolved = resolve_person_reconciliation(db, item_id=item.id, action="ignore", actor_person_id=actor)
    assert resolved.status == "ignored"
    assert resolved.resolved_person_id is None


def test_resolve_rejects_non_pending_item(db_session):
    db = db_session
    actor = _actor(db)
    reconcile_pm_names(db, payload={"projects": {"p1": {"name": "P", "pm": "PM Duplo Sintético"}}})
    item = db.query(PersonReconciliationItem).filter(
        PersonReconciliationItem.normalized_name == "pm duplo sintético"
    ).one()
    resolve_person_reconciliation(db, item_id=item.id, action="ignore", actor_person_id=actor)

    with pytest.raises(ValueError, match="pendente"):
        resolve_person_reconciliation(db, item_id=item.id, action="ignore", actor_person_id=actor)


# --------------------------------------------------------------------------
# Integração com a ingestão/promoção: nunca promover silenciosamente.
# --------------------------------------------------------------------------


def test_ingest_blocks_record_with_unresolved_pm(db_session):
    db = db_session
    actor = _actor(db)
    payload = {
        "projects": {
            "synth_pm_block": {
                "name": "Instalação Sintética Bloqueada por PM",
                "pm": "PM Totalmente Desconhecido Sintético",
            }
        }
    }
    batch = ingest_export(db, payload=payload, actor_person_id=actor)
    record = db.query(StagingProjectRecord).filter(StagingProjectRecord.import_batch_id == batch.id).one()

    assert record.status == "conflict"
    assert record.conflict_reason == "pm_unresolved"
    assert record.pm_name_raw == "PM Totalmente Desconhecido Sintético"
    # A resolução do PROJETO já ficou calculada, só o PM bloqueia:
    assert record.resolved_action == "create_new"

    with pytest.raises(ValueError, match="ready_to_promote|registo pronto"):
        promote_staging_record(db, staging_record_id=record.id, actor_person_id=actor)


def test_promote_refuses_even_if_status_is_manually_forced_to_ready(db_session):
    """Defesa em profundidade: mesmo contornando a fila normal e forçando
    o estado do registo para 'ready_to_promote' diretamente, a promoção
    continua a recusar-se a avançar com um PM não resolvido."""
    db = db_session
    actor = _actor(db)
    payload = {
        "projects": {
            "synth_pm_force": {
                "name": "Instalação Sintética Forçada",
                "pm": "PM Forçado Desconhecido Sintético",
            }
        }
    }
    batch = ingest_export(db, payload=payload, actor_person_id=actor)
    record = db.query(StagingProjectRecord).filter(StagingProjectRecord.import_batch_id == batch.id).one()
    assert record.status == "conflict"

    # Contorna a via normal (resolve_conflict/retry_pm_resolution) de propósito.
    record.status = "ready_to_promote"
    db.flush()

    with pytest.raises(ValueError, match="PM"):
        promote_staging_record(db, staging_record_id=record.id, actor_person_id=actor)


def test_resolve_conflict_proceed_without_pm_unblocks_and_promotes_without_pm(db_session):
    db = db_session
    actor = _actor(db)
    payload = {
        "projects": {
            "synth_pm_proceed": {
                "name": "Instalação Sintética Sem PM Explícito",
                "pm": "PM Sem Resolução Sintético",
            }
        }
    }
    batch = ingest_export(db, payload=payload, actor_person_id=actor)
    record = db.query(StagingProjectRecord).filter(StagingProjectRecord.import_batch_id == batch.id).one()

    resolved = resolve_conflict(
        db, staging_record_id=record.id, action="proceed_without_pm", actor_person_id=actor,
        note="Decisão sintética de teste: prosseguir sem PM.",
    )
    assert resolved.status == "ready_to_promote"
    assert resolved.pm_explicitly_unassigned is True

    project = promote_staging_record(db, staging_record_id=record.id, actor_person_id=actor)
    assert project.name == "Instalação Sintética Sem PM Explícito"
    assert project.pm_person_id is None


def test_resolve_conflict_rejects_normal_actions_on_pm_unresolved(db_session):
    db = db_session
    actor = _actor(db)
    payload = {"projects": {"p1": {"name": "Projeto Sintético X", "pm": "PM Bloqueador Sintético"}}}
    batch = ingest_export(db, payload=payload, actor_person_id=actor)
    record = db.query(StagingProjectRecord).filter(StagingProjectRecord.import_batch_id == batch.id).one()

    with pytest.raises(ValueError, match="pm_unresolved|PM"):
        resolve_conflict(db, staging_record_id=record.id, action="skip", actor_person_id=actor)


def test_reconciliation_then_retry_unblocks_and_promotes_with_correct_pm(db_session):
    db = db_session
    actor = _actor(db)
    payload = {
        "projects": {
            "synth_pm_retry": {
                "name": "Instalação Sintética Reconciliada",
                "pm": "PM Legado A Reconciliar Sintético",
            }
        }
    }

    # Passo 0 (etapa explícita antes da migração): reconciliar PMs.
    reconcile_pm_names(db, payload=payload)
    queue_item = db.query(PersonReconciliationItem).filter(
        PersonReconciliationItem.normalized_name == "pm legado a reconciliar sintético"
    ).one()

    batch = ingest_export(db, payload=payload, actor_person_id=actor)
    record = db.query(StagingProjectRecord).filter(StagingProjectRecord.import_batch_id == batch.id).one()
    assert record.status == "conflict"
    assert record.conflict_reason == "pm_unresolved"

    # Resolve a reconciliação (criar pessoa nova, histórico preservado).
    resolve_person_reconciliation(db, item_id=queue_item.id, action="create_new", actor_person_id=actor)

    # Desbloqueia o registo já ingerido, sem reingestão.
    unblocked = retry_pm_resolution(db, staging_record_id=record.id)
    assert unblocked.status == "ready_to_promote"

    project = promote_staging_record(db, staging_record_id=record.id, actor_person_id=actor)
    assert project.pm_person_id is not None
    assert project.pm.display_name == "PM Legado A Reconciliar Sintético"
    assert project.pm.is_active is False


def test_ingest_recognizes_ignored_reconciliation_and_does_not_block(db_session):
    db = db_session
    actor = _actor(db)
    payload = {
        "projects": {
            "synth_pm_ignored": {
                "name": "Instalação Sintética PM Ignorado",
                "pm": "PM Marcado Para Ignorar Sintético",
            }
        }
    }
    reconcile_pm_names(db, payload=payload)
    queue_item = db.query(PersonReconciliationItem).filter(
        PersonReconciliationItem.normalized_name == "pm marcado para ignorar sintético"
    ).one()
    resolve_person_reconciliation(db, item_id=queue_item.id, action="ignore", actor_person_id=actor)

    batch = ingest_export(db, payload=payload, actor_person_id=actor)
    record = db.query(StagingProjectRecord).filter(StagingProjectRecord.import_batch_id == batch.id).one()

    # Já reconciliado como "ignorar" antes da ingestão — não bloqueia.
    assert record.status == "ready_to_promote"
    assert record.pm_explicitly_unassigned is True

    project = promote_staging_record(db, staging_record_id=record.id, actor_person_id=actor)
    assert project.pm_person_id is None
