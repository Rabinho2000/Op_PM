"""D-030: `target_project_id` de `resolve_conflict`/`link_existing` tem de
estar entre os candidatos detetados automaticamente. Ligar a um projeto
fora desses candidatos exige a permissão `migration.link_arbitrary_project`
e uma nota não vazia — evita ligações acidentais a projetos arbitrários,
mantendo a ação sempre auditada e reversível.
"""
from __future__ import annotations

import pytest

from app.migration.staging import (
    ingest_export,
    promote_staging_record,
    resolve_candidate_project_ids,
    resolve_conflict,
    rollback_promotion,
)
from app.models.identity import User
from app.models.migration import StagingProjectRecord
from app.models.project import Project, ProjectExternalId


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _actor(db):
    return db.query(User).filter(User.email == "chefe.sintetico@example.invalid").one().person_id


def _make_unrelated_promoted_project(db, actor, *, name: str, external_id: str) -> Project:
    """Cria e promove um projeto isolado, sem qualquer relação (por nome ou
    lote) com o cenário de conflito testado a seguir — serve como "alvo
    arbitrário" fora dos candidatos detetados."""
    batch = ingest_export(db, payload={"projects": {external_id: {"name": name}}}, actor_person_id=actor)
    record = db.query(StagingProjectRecord).filter(StagingProjectRecord.import_batch_id == batch.id).one()
    return promote_staging_record(db, staging_record_id=record.id, actor_person_id=actor)


def _make_within_batch_duplicate_conflict(db, actor, *, name: str, id_a: str, id_b: str):
    """Ingerido um lote com dois registos com o mesmo nome (nunca vistos
    antes na BD) — o primeiro fica pronto a promover, o segundo fica em
    conflito com candidato `batch:<id_a>` (ainda não resolvido para um
    projeto real, porque `id_a` ainda não foi promovido)."""
    batch = ingest_export(
        db,
        payload={"projects": {id_a: {"name": name}, id_b: {"name": name}}},
        actor_person_id=actor,
    )
    records = {
        r.external_id: r
        for r in db.query(StagingProjectRecord).filter(StagingProjectRecord.import_batch_id == batch.id).all()
    }
    return records[id_a], records[id_b]


# --------------------------------------------------------------------------
# Camada de serviço: app.migration.staging.resolve_conflict
# --------------------------------------------------------------------------


def test_resolve_conflict_rejects_target_outside_candidates_by_default(db_session):
    db = db_session
    actor = _actor(db)
    unrelated = _make_unrelated_promoted_project(
        db, actor, name="Instalação Sintética D030 Alvo Arbitrário", external_id="synth_d030_arbitrary"
    )
    _, duplicate = _make_within_batch_duplicate_conflict(
        db,
        actor,
        name="Instalação Sintética D030 Duplicada",
        id_a="synth_d030_dup_a",
        id_b="synth_d030_dup_b",
    )
    assert duplicate.status == "conflict"

    with pytest.raises(ValueError, match="fora dos candidatos"):
        resolve_conflict(
            db,
            staging_record_id=duplicate.id,
            action="link_existing",
            target_project_id=unrelated.id,
            actor_person_id=actor,
            note="Tentativa sem autorização especial.",
        )


def test_resolve_conflict_allows_target_outside_candidates_with_flag_and_note(db_session):
    db = db_session
    actor = _actor(db)
    unrelated = _make_unrelated_promoted_project(
        db, actor, name="Instalação Sintética D030 Alvo Autorizado", external_id="synth_d030_authorized"
    )
    _, duplicate = _make_within_batch_duplicate_conflict(
        db,
        actor,
        name="Instalação Sintética D030 Duplicada Dois",
        id_a="synth_d030_dup2_a",
        id_b="synth_d030_dup2_b",
    )

    resolved = resolve_conflict(
        db,
        staging_record_id=duplicate.id,
        action="link_existing",
        target_project_id=unrelated.id,
        actor_person_id=actor,
        note="Confirmado manualmente como o mesmo projeto físico (fora dos candidatos automáticos).",
        allow_target_outside_candidates=True,
    )
    assert resolved.resolved_target_project_id == unrelated.id


def test_resolve_conflict_requires_non_empty_note_even_with_flag(db_session):
    db = db_session
    actor = _actor(db)
    unrelated = _make_unrelated_promoted_project(
        db, actor, name="Instalação Sintética D030 Alvo Sem Nota", external_id="synth_d030_no_note"
    )
    _, duplicate = _make_within_batch_duplicate_conflict(
        db,
        actor,
        name="Instalação Sintética D030 Duplicada Três",
        id_a="synth_d030_dup3_a",
        id_b="synth_d030_dup3_b",
    )

    with pytest.raises(ValueError, match="nota"):
        resolve_conflict(
            db,
            staging_record_id=duplicate.id,
            action="link_existing",
            target_project_id=unrelated.id,
            actor_person_id=actor,
            note="   ",
            allow_target_outside_candidates=True,
        )


def test_resolve_candidate_project_ids_resolves_promoted_batch_sibling(db_session):
    """Regressão: um candidato 'batch:<id>' só se torna um UUID real depois
    de o registo irmão ser promovido — resolve_candidate_project_ids tem de
    o traduzir corretamente, sem exigir a permissão especial."""
    db = db_session
    actor = _actor(db)
    original, duplicate = _make_within_batch_duplicate_conflict(
        db,
        actor,
        name="Instalação Sintética D030 Resolução De Lote",
        id_a="synth_d030_resolve_a",
        id_b="synth_d030_resolve_b",
    )
    assert original.status == "ready_to_promote"
    canonical = promote_staging_record(db, staging_record_id=original.id, actor_person_id=actor)

    db.refresh(duplicate)
    valid_targets = resolve_candidate_project_ids(db, duplicate)
    assert str(canonical.id) in valid_targets

    # E resolve_conflict aceita este alvo sem allow_target_outside_candidates.
    resolved = resolve_conflict(
        db,
        staging_record_id=duplicate.id,
        action="link_existing",
        target_project_id=canonical.id,
        actor_person_id=actor,
        note="Ligação normal a candidato já resolvido (sem autorização especial).",
    )
    assert resolved.resolved_target_project_id == canonical.id


# --------------------------------------------------------------------------
# Camada de API: app.api.routes_migration.resolve_staging_conflict
# --------------------------------------------------------------------------


def test_api_chefe_without_special_permission_cannot_link_arbitrary_project(db_session, api_client):
    db = db_session
    actor = _actor(db)
    unrelated = _make_unrelated_promoted_project(
        db, actor, name="Instalação Sintética D030 API Alvo", external_id="synth_d030_api_arbitrary"
    )
    _, duplicate = _make_within_batch_duplicate_conflict(
        db,
        actor,
        name="Instalação Sintética D030 API Duplicada",
        id_a="synth_d030_api_dup_a",
        id_b="synth_d030_api_dup_b",
    )

    resp = api_client.post(
        f"/api/migration/staging-records/{duplicate.id}/resolve-conflict",
        json={
            "action": "link_existing",
            "target_project_id": str(unrelated.id),
            "note": "Tentativa de ligação arbitrária sem permissão.",
        },
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 403
    assert "migration.link_arbitrary_project" in resp.json()["detail"]


def test_api_admin_with_permission_still_requires_note(db_session, api_client):
    db = db_session
    actor = _actor(db)
    unrelated = _make_unrelated_promoted_project(
        db, actor, name="Instalação Sintética D030 API Sem Nota Admin", external_id="synth_d030_api_admin_no_note"
    )
    _, duplicate = _make_within_batch_duplicate_conflict(
        db,
        actor,
        name="Instalação Sintética D030 API Duplicada Admin Sem Nota",
        id_a="synth_d030_api_admin_a",
        id_b="synth_d030_api_admin_b",
    )

    resp = api_client.post(
        f"/api/migration/staging-records/{duplicate.id}/resolve-conflict",
        json={"action": "link_existing", "target_project_id": str(unrelated.id)},
        headers=_headers("admin.sintetico@example.invalid"),
    )
    assert resp.status_code == 400


def test_api_admin_with_permission_and_note_can_link_arbitrary_project(db_session, api_client):
    db = db_session
    actor = _actor(db)
    unrelated = _make_unrelated_promoted_project(
        db, actor, name="Instalação Sintética D030 API Alvo Autorizado", external_id="synth_d030_api_admin_ok"
    )
    _, duplicate = _make_within_batch_duplicate_conflict(
        db,
        actor,
        name="Instalação Sintética D030 API Duplicada Admin Ok",
        id_a="synth_d030_api_admin_ok_a",
        id_b="synth_d030_api_admin_ok_b",
    )

    resp = api_client.post(
        f"/api/migration/staging-records/{duplicate.id}/resolve-conflict",
        json={
            "action": "link_existing",
            "target_project_id": str(unrelated.id),
            "note": "Confirmado pelo administrador como o mesmo projeto físico.",
        },
        headers=_headers("admin.sintetico@example.invalid"),
    )
    assert resp.status_code == 200
    assert resp.json()["resolved_target_project_id"] == str(unrelated.id)

    # A ação continua auditada (via app.migration.people_reconciliation/
    # staging — o próprio registo de staging guarda a resolução) e
    # reversível: promover e depois reverter continua a funcionar
    # normalmente para esta ligação "fora dos candidatos".
    resp_promote = api_client.post(
        f"/api/migration/staging-records/{duplicate.id}/promote",
        headers=_headers("admin.sintetico@example.invalid"),
    )
    assert resp_promote.status_code == 200
    assert resp_promote.json()["promoted_project_id"] == str(unrelated.id)

    link = (
        db.query(ProjectExternalId)
        .filter(
            ProjectExternalId.project_id == unrelated.id,
            ProjectExternalId.external_id == "synth_d030_api_admin_ok_b",
        )
        .one()
    )
    assert link is not None

    reverted = rollback_promotion(
        db,
        staging_record_id=duplicate.id,
        actor_person_id=actor,
        reason="Teste D030: reversão de ligação arbitrária.",
    )
    assert reverted.status == "pending_review"
    assert reverted.reverted_at is not None
