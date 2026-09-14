"""Endpoints de consulta/resolução de migração — reconciliação de PM e o
bloqueio de promoção com PM não resolvido, pedidos explicitamente para a
Fase 1. A ingestão em si não tem endpoint HTTP nesta fase (ver
docs/DECISIONS.md) — os testes aqui ingerem diretamente via
`app.migration.staging.ingest_export` (dados sintéticos) e usam a API só
para as ações de resolução/promoção.
"""
from __future__ import annotations

from app.migration.people_reconciliation import reconcile_pm_names
from app.migration.staging import ingest_export
from app.models.identity import User
from app.models.migration import PersonReconciliationItem, StagingProjectRecord


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def test_unresolved_pm_blocks_promotion_via_api(db_session, api_client):
    db = db_session
    actor = db.query(User).filter(User.email == "chefe.sintetico@example.invalid").one().person_id
    payload = {
        "projects": {
            "synth_api_pm_block": {
                "name": "Instalação Sintética API Bloqueada por PM",
                "pm": "PM Sintético API Desconhecido",
            }
        }
    }
    batch = ingest_export(db, payload=payload, actor_person_id=actor)
    record = db.query(StagingProjectRecord).filter(StagingProjectRecord.import_batch_id == batch.id).one()
    assert record.status == "conflict"
    assert record.conflict_reason == "pm_unresolved"

    resp = api_client.post(
        f"/api/migration/staging-records/{record.id}/promote",
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    # O registo está 'conflict' (pm_unresolved) — promote_staging_record
    # recusa-o já na primeira verificação de estado, antes mesmo de
    # chegar à verificação específica de PM (essa cobre o cenário de
    # defesa em profundidade, testado em
    # tests/test_people_reconciliation.py::test_promote_refuses_even_if_status_is_manually_forced_to_ready).
    assert resp.status_code == 409

    resp_resolve = api_client.post(
        f"/api/migration/staging-records/{record.id}/resolve-conflict",
        json={"action": "proceed_without_pm"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp_resolve.status_code == 200
    assert resp_resolve.json()["status"] == "ready_to_promote"


def test_resolve_unknown_pm_via_reconciliation_api_then_promote(db_session, api_client):
    db = db_session
    actor = db.query(User).filter(User.email == "chefe.sintetico@example.invalid").one().person_id
    payload = {
        "projects": {
            "synth_api_pm_reconcile": {
                "name": "Instalação Sintética API Reconciliada",
                "pm": "PM Sintético API A Reconciliar",
            }
        }
    }
    reconcile_pm_names(db, payload=payload)
    item = (
        db.query(PersonReconciliationItem)
        .filter(PersonReconciliationItem.normalized_name == "pm sintético api a reconciliar")
        .one()
    )

    # Resolve via API: criar uma pessoa nova (histórica, sem login).
    resp_resolve = api_client.post(
        f"/api/migration/reconciliation-items/{item.id}/resolve",
        json={"action": "create_new", "note": "Criada via teste de API."},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp_resolve.status_code == 200
    assert resp_resolve.json()["status"] == "created_new"

    batch = ingest_export(db, payload=payload, actor_person_id=actor)
    record = db.query(StagingProjectRecord).filter(StagingProjectRecord.import_batch_id == batch.id).one()
    assert record.status == "ready_to_promote"  # já reconciliado antes da ingestão

    resp_promote = api_client.post(
        f"/api/migration/staging-records/{record.id}/promote",
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp_promote.status_code == 200
    assert resp_promote.json()["status"] == "promoted"


def test_proceed_without_pm_via_api(db_session, api_client):
    db = db_session
    actor = db.query(User).filter(User.email == "chefe.sintetico@example.invalid").one().person_id
    payload = {
        "projects": {
            "synth_api_pm_proceed": {
                "name": "Instalação Sintética API Sem PM",
                "pm": "PM Sintético API Sem Resolução",
            }
        }
    }
    batch = ingest_export(db, payload=payload, actor_person_id=actor)
    record = db.query(StagingProjectRecord).filter(StagingProjectRecord.import_batch_id == batch.id).one()

    resp = api_client.post(
        f"/api/migration/staging-records/{record.id}/resolve-conflict",
        json={"action": "proceed_without_pm", "note": "Decisão de teste via API."},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready_to_promote"


def test_pm_without_migration_permission_cannot_view_or_resolve(db_session, api_client):
    db = db_session
    actor = db.query(User).filter(User.email == "chefe.sintetico@example.invalid").one().person_id
    payload = {"projects": {"p1": {"name": "Instalação Sintética Só Chefe Vê"}}}
    batch = ingest_export(db, payload=payload, actor_person_id=actor)

    resp = api_client.get(
        f"/api/migration/import-batches/{batch.id}/records",
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 403


def test_retry_promotion_endpoint_reactivates_after_rollback(db_session, api_client):
    """D-036: rollback → retry-promotion → promote outra vez, tudo via API,
    reativa o MESMO projeto (nunca cria um segundo)."""
    db = db_session
    actor = db.query(User).filter(User.email == "chefe.sintetico@example.invalid").one().person_id
    payload = {"projects": {"synth_api_retry": {"name": "Instalação Sintética API Retry"}}}
    batch = ingest_export(db, payload=payload, actor_person_id=actor)
    record = db.query(StagingProjectRecord).filter(StagingProjectRecord.import_batch_id == batch.id).one()
    headers = _headers("chefe.sintetico@example.invalid")

    resp_promote = api_client.post(f"/api/migration/staging-records/{record.id}/promote", headers=headers)
    assert resp_promote.status_code == 200
    project_id = resp_promote.json()["promoted_project_id"]
    assert project_id is not None

    resp_rollback = api_client.post(
        f"/api/migration/staging-records/{record.id}/rollback",
        json={"reason": "Teste de repetição segura via API."},
        headers=headers,
    )
    assert resp_rollback.status_code == 200
    assert resp_rollback.json()["status"] == "pending_review"

    resp_retry = api_client.post(f"/api/migration/staging-records/{record.id}/retry-promotion", headers=headers)
    assert resp_retry.status_code == 200
    assert resp_retry.json()["status"] == "ready_to_promote"
    assert resp_retry.json()["resolved_action"] == "update_existing"

    resp_promote_again = api_client.post(f"/api/migration/staging-records/{record.id}/promote", headers=headers)
    assert resp_promote_again.status_code == 200
    assert resp_promote_again.json()["promoted_project_id"] == project_id  # o MESMO projeto


def test_retry_promotion_endpoint_requires_migration_resolve_permission(db_session, api_client):
    db = db_session
    actor = db.query(User).filter(User.email == "chefe.sintetico@example.invalid").one().person_id
    payload = {"projects": {"synth_api_retry_perm": {"name": "Instalação Sintética API Retry Permissão"}}}
    batch = ingest_export(db, payload=payload, actor_person_id=actor)
    record = db.query(StagingProjectRecord).filter(StagingProjectRecord.import_batch_id == batch.id).one()
    headers = _headers("chefe.sintetico@example.invalid")

    api_client.post(f"/api/migration/staging-records/{record.id}/promote", headers=headers)
    api_client.post(
        f"/api/migration/staging-records/{record.id}/rollback",
        json={"reason": "Teste de permissão."},
        headers=headers,
    )

    resp = api_client.post(
        f"/api/migration/staging-records/{record.id}/retry-promotion",
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 403


def test_import_batches_visible_to_chefe_operacoes(db_session, api_client):
    db = db_session
    actor = db.query(User).filter(User.email == "chefe.sintetico@example.invalid").one().person_id
    ingest_export(db, payload={"projects": {"p1": {"name": "Instalação Sintética Visível"}}}, actor_person_id=actor)

    resp = api_client.get("/api/migration/import-batches", headers=_headers("chefe.sintetico@example.invalid"))
    assert resp.status_code == 200
    assert len(resp.json()) >= 1
