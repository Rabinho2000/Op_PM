"""Importação em staging do export legado (`atribuicoes.json`-shaped).

Regras obrigatórias desta fase (ver docs/PLAN.md, "Estratégia de migração"):
- NUNCA importa diretamente para produção — todo o caminho passa por aqui,
  que só decide "criar"/"atualizar"/"conflito", nunca aplica sem que o
  chamador peça `mode='apply'` explicitamente.
- Gera um ID interno (UUID) permanente por projeto — nunca reaproveita nem
  depende do "nome" como chave.
- Cada projeto de origem fica ligado por `ProjectExternalId` (source_system
  fixo, ex. 'legacy_json'), preservando o ID/slug antigo só para
  rastreabilidade.
- Duplicados/correspondências ambíguas (mais do que um projeto existente
  com nome igual/semelhante) vão para `SyncConflict`, nunca são resolvidos
  automaticamente.
- Campos incompletos (`pm`, `email`, `coords`, `contact` em falta) são
  preservados tal como estão — nunca inventados nem usados para excluir o
  registo.
- Cada execução gera um `SyncRun` com contagens, checksum do payload de
  origem, e um relatório (`report_json`) com uma linha por registo
  processado — para auditoria e para o "dry-run antes de apply".

Nesta fase (Fase 0), esta função só é exercida sobre dados sintéticos (ver
`backend/fixtures/synthetic_legacy_export.json` e
`backend/tests/test_staging_migration.py`). Migrar os 295 projetos reais é
trabalho da Fase 1 do roadmap, feito manualmente e com revisão humana da
fila de conflitos — não por esta função a correr sem supervisão.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import new_uuid
from app.models.project import Project, ProjectExternalId
from app.models.sync import SyncConflict, SyncRun

SOURCE_LEGACY_JSON = "legacy_json"


@dataclass
class StagingImportResult:
    sync_run: SyncRun
    conflicts: list[SyncConflict]


def _checksum(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _find_by_external_id(db: Session, *, source_system: str, external_id: str) -> ProjectExternalId | None:
    return (
        db.query(ProjectExternalId)
        .filter(
            ProjectExternalId.source_system == source_system,
            ProjectExternalId.external_id == external_id,
        )
        .one_or_none()
    )


def _find_candidates_by_name(db: Session, *, name: str) -> list[Project]:
    normalized = name.strip().lower()
    return (
        db.query(Project)
        .filter(func.lower(func.trim(Project.name)) == normalized)
        .all()
    )


def run_staging_import(
    db: Session,
    *,
    payload: dict,
    source_system: str = SOURCE_LEGACY_JSON,
    mode: Literal["dry_run", "apply"] = "dry_run",
) -> StagingImportResult:
    if "projects" not in payload or not isinstance(payload["projects"], dict):
        raise ValueError("payload inválido: esperado um objeto com a chave 'projects'")

    # Construído com ID explícito e, em modo dry_run, NUNCA adicionado à
    # sessão — evita que um `rollback()` no final invalide/expire o objeto
    # que devolvemos ao chamador (um objeto transiente sobrevive a rollback,
    # um objeto persistente na sessão não).
    sync_run = SyncRun(
        id=new_uuid(),
        source_system=source_system,
        mode=mode,
        status="running",
        started_at=dt.datetime.now(dt.timezone.utc),
        checksum=_checksum(payload),
        # Valores explícitos: os `default=0` a nível de coluna só se aplicam
        # no INSERT — um objeto nunca adicionado à sessão (caso do dry_run)
        # ficaria com estes campos a None sem isto.
        records_seen=0,
        records_created=0,
        records_updated=0,
        records_conflicted=0,
    )
    if mode == "apply":
        db.add(sync_run)
        db.flush()

    report: list[dict] = []
    conflicts: list[SyncConflict] = []
    created = updated = conflicted = 0

    # Nomes já "criados" (ou "criar-se-iam", em dry_run) por ESTA execução.
    # Necessário porque, em dry_run, nenhuma escrita chega à base de dados a
    # meio da função — sem isto, dois registos do mesmo lote com o mesmo
    # nome (ex. synth_p001/synth_p003 na fixture sintética) não seriam
    # detetados como ambíguos num dry-run, só num apply. Em apply, isto é
    # redundante com `_find_candidates_by_name` (que já vê as escritas
    # anteriores do mesmo run porque cada criação é `flush()`ada de
    # imediato), mas mantém o comportamento idêntico em ambos os modos.
    seen_in_this_run: dict[str, list[str]] = {}

    for legacy_id, record in payload["projects"].items():
        sync_run.records_seen += 1
        name = (record.get("name") or "").strip()

        existing_link = _find_by_external_id(db, source_system=source_system, external_id=legacy_id)
        if existing_link is not None:
            # Já mapeado em execuções anteriores: seria uma atualização.
            updated += 1
            report.append({"legacy_id": legacy_id, "action": "would_update" if mode == "dry_run" else "updated",
                            "project_id": str(existing_link.project_id)})
            continue

        if not name:
            conflicted += 1
            conflict = SyncConflict(
                id=new_uuid(),
                sync_run_id=sync_run.id,
                source_system=source_system,
                external_id=legacy_id,
                reason="no_match",
                candidate_project_ids_json="[]",
                payload_json=json.dumps(record, ensure_ascii=False),
                status="pending",
            )
            conflicts.append(conflict)
            report.append({"legacy_id": legacy_id, "action": "conflict_no_name"})
            continue

        normalized_name = name.lower()
        db_candidates = _find_candidates_by_name(db, name=name)
        batch_candidates = seen_in_this_run.get(normalized_name, [])
        candidate_refs = [str(c.id) for c in db_candidates] + [f"batch:{ref}" for ref in batch_candidates]

        if candidate_refs:
            conflicted += 1
            reason = "ambiguous_match" if len(candidate_refs) > 1 else "duplicate"
            conflict = SyncConflict(
                id=new_uuid(),
                sync_run_id=sync_run.id,
                source_system=source_system,
                external_id=legacy_id,
                reason=reason,
                candidate_project_ids_json=json.dumps(candidate_refs),
                payload_json=json.dumps(record, ensure_ascii=False),
                status="pending",
            )
            conflicts.append(conflict)
            report.append({"legacy_id": legacy_id, "action": f"conflict_{reason}", "candidates": len(candidate_refs)})
            seen_in_this_run.setdefault(normalized_name, []).append(legacy_id)
            continue

        # Nenhum candidato (nem na base de dados, nem já visto neste lote):
        # criação limpa.
        seen_in_this_run.setdefault(normalized_name, []).append(legacy_id)
        created += 1
        if mode == "apply":
            project = Project(
                name=name,
                client_name=record.get("contact") or None,
                client_contact=record.get("contact") or None,
                client_email=record.get("email") or None,
                address=None,
                lat=(record.get("coords") or {}).get("lat") if record.get("coords") else None,
                lon=(record.get("coords") or {}).get("lon") if record.get("coords") else None,
                power_kwp=record.get("power"),
                is_active=True,
            )
            db.add(project)
            db.flush()
            db.add(
                ProjectExternalId(
                    project_id=project.id,
                    source_system=source_system,
                    external_id=legacy_id,
                    sync_status="ok",
                    synced_at=dt.datetime.now(dt.timezone.utc),
                )
            )
            report.append({"legacy_id": legacy_id, "action": "created", "project_id": str(project.id)})
        else:
            report.append({"legacy_id": legacy_id, "action": "would_create"})

    sync_run.records_created = created
    sync_run.records_updated = updated
    sync_run.records_conflicted = conflicted
    sync_run.finished_at = dt.datetime.now(dt.timezone.utc)
    sync_run.status = "completed"
    sync_run.report_json = json.dumps(report, ensure_ascii=False)

    if mode == "apply":
        db.add(sync_run)
        for conflict in conflicts:
            db.add(conflict)
        db.commit()
    else:
        # dry-run: nada foi adicionado à sessão (nem sync_run, nem
        # conflitos, nem projetos) — `rollback()` aqui é só defensivo, para
        # o caso de alguma leitura ter deixado estado pendente.
        db.rollback()

    return StagingImportResult(sync_run=sync_run, conflicts=conflicts)
