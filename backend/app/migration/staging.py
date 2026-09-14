"""Migração em staging: ingestão → revisão de conflitos → promoção
explícita. Ver `app/models/migration.py` para o modelo de dados e
docs/DECISIONS.md (D-005, D-017) para a justificação do desenho.

Três funções fazem as três etapas exigidas, nunca misturadas:

- `ingest_export`: lê um export externo e cria registos de staging.
  NUNCA escreve em `projects`. Sempre persistente (commit imediato) — não
  há "dry run", porque não há nada arriscado a simular: nada aqui pode
  corromper dados canónicos.
- `resolve_conflict`: decisão humana sobre um registo em conflito
  (`create_new` / `link_existing` / `skip`). Só isto pode tirar um registo
  do estado `conflict`.
- `promote_staging_record`: só isto escreve em `projects`. Gera sempre
  entradas de `project_history` (nunca uma escrita silenciosa).
- `rollback_promotion`: desfaz uma promoção. Nunca apaga histórico — só
  acrescenta novas entradas que revertem os valores, e marca o registo de
  staging como pendente de nova decisão.

Nesta fase, estas funções só são exercidas com dados sintéticos
(`backend/fixtures/`, `backend/tests/test_staging_persistence.py`). Migrar
os 295 projetos reais é trabalho de uma fase futura, nunca a partir deste
repositório público — ver docs/PLAN.md.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from typing import Any, Literal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit.log import record_project_change
from app.db import new_uuid
from app.models.migration import ImportBatch, StagingProjectRecord
from app.models.people import Person
from app.models.project import Project, ProjectExternalId, ProjectHistory

SOURCE_LEGACY_JSON = "legacy_json"

ResolvedAction = Literal["create_new", "link_existing", "skip"]

# Campos canónicos que uma promoção pode escrever em `Project`, e como
# extraí-los de `mapped_fields_json`. Mantido como uma única lista para que
# `_build_canonical_fields`, a escrita de histórico, e o rollback (que
# precisa de saber que tipo reconstruir a partir do texto guardado em
# `ProjectHistory.old_value`) nunca divirjam.
_CANONICAL_TEXT_FIELDS = (
    "client_contact",
    "client_email",
    "clickup_status_mirror",
    "role",
    "equipment_notes",
    "injection_notes",
    "om_notes",
    "commercial_assumptions",
    "upac_registration",
    "m2m_card",
    "upac_connection_date_raw",
    "award_year_raw",
    "power_raw",
)
_CANONICAL_FLOAT_FIELDS = ("lat", "lon", "power_kwp")
_CANONICAL_DATE_FIELDS = ("start_date",)


# --------------------------------------------------------------------------
# Extração/normalização de campos legados (requisito: preservar o payload
# original e mapear PM, email, contacto, coordenadas, data de início, estado
# ClickUp, e os restantes campos relevantes do export legado — IDF em
# solcor-gestao.html do repositório legado).
# --------------------------------------------------------------------------

_POWER_NUMERIC_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def _parse_power_kwp(raw: Any) -> float | None:
    """O export legado guarda a potência como texto livre (ex.
    "165,56 kWp"), não um número limpo — extrai o melhor esforço numérico,
    tolerando vírgula decimal e sufixo de unidade. `power_raw` (no
    `Project`) preserva sempre o valor original, mesmo quando isto falha."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str):
        return None
    match = _POWER_NUMERIC_RE.search(raw)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def _parse_legacy_date(raw: Any) -> dt.date | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        return dt.date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _map_legacy_fields(record: dict) -> dict:
    """Extrai os campos relevantes de um registo de projeto do export
    legado (`app: "solcor-percurso"`), sem os aplicar ainda a nada — a
    aplicação ao `Project` canónico só acontece na promoção."""
    coords = record.get("coords")
    coords = coords if isinstance(coords, dict) else {}
    return {
        "name": (record.get("name") or "").strip(),
        "pm_name_raw": record.get("pm"),
        "contact": record.get("contact"),
        "email": record.get("email"),
        "lat": coords.get("lat"),
        "lon": coords.get("lon"),
        "power_raw": record.get("power"),
        "start_date_raw": record.get("startDate"),
        "clickup_status": record.get("clickupStatus"),
        "role": record.get("role"),
        "equipment_notes": record.get("equip"),
        "injection_notes": record.get("injecao"),
        "om_notes": record.get("om"),
        "commercial_assumptions": record.get("assum"),
        "upac_registration": record.get("upacRegisto"),
        "m2m_card": record.get("m2mCard"),
        "upac_connection_date_raw": record.get("upacConnDate"),
        "award_year_raw": record.get("anoAdjudicacao"),
    }


def _build_canonical_fields(mapped: dict) -> dict:
    """Traduz os campos mapeados (texto livre do export legado) para os
    tipos/nomes de coluna canónicos do `Project`. Nunca inventa um valor
    para um campo em falta — fica `None`, preservando a incompletude real
    dos dados (ver docs/DECISIONS.md e a nota em app/models/project.py)."""
    return {
        "name": mapped["name"],
        "client_contact": mapped.get("contact") or None,
        "client_email": mapped.get("email") or None,
        "lat": mapped.get("lat"),
        "lon": mapped.get("lon"),
        "power_kwp": _parse_power_kwp(mapped.get("power_raw")),
        "power_raw": str(mapped["power_raw"]) if mapped.get("power_raw") is not None else None,
        "start_date": _parse_legacy_date(mapped.get("start_date_raw")),
        "clickup_status_mirror": mapped.get("clickup_status") or None,
        "role": mapped.get("role") or None,
        "equipment_notes": mapped.get("equipment_notes") or None,
        "injection_notes": mapped.get("injection_notes") or None,
        "om_notes": mapped.get("om_notes") or None,
        "commercial_assumptions": mapped.get("commercial_assumptions") or None,
        "upac_registration": mapped.get("upac_registration") or None,
        "m2m_card": mapped.get("m2m_card") or None,
        "upac_connection_date_raw": mapped.get("upac_connection_date_raw") or None,
        "award_year_raw": mapped.get("award_year_raw") or None,
    }


def _resolve_pm_person(db: Session, pm_name_raw: Any) -> Person | None:
    """Tenta ligar o nome de PM do export legado a um `Person` existente,
    por nome exato normalizado. Nunca cria uma pessoa nova aqui, e nunca
    liga quando o nome é ambíguo (mais do que uma pessoa com o mesmo nome)
    — nesse caso o projeto fica sem PM atribuído, para correção manual, em
    vez de adivinhar."""
    if not pm_name_raw or not isinstance(pm_name_raw, str):
        return None
    normalized = pm_name_raw.strip().lower()
    if not normalized:
        return None
    candidates = db.query(Person).filter(func.lower(func.trim(Person.display_name)) == normalized).all()
    if len(candidates) == 1:
        return candidates[0]
    return None


def _string_to_field_value(field_name: str, raw: str | None) -> Any:
    """Inverso (best-effort) da conversão texto->valor usada ao escrever
    `ProjectHistory.old_value`/`new_value`. Usado só pelo rollback, para
    reconstruir o tipo Python correto a partir do texto guardado."""
    if raw is None:
        return None
    if field_name in _CANONICAL_FLOAT_FIELDS:
        try:
            return float(raw)
        except ValueError:
            return None
    if field_name in _CANONICAL_DATE_FIELDS:
        try:
            return dt.date.fromisoformat(raw)
        except ValueError:
            return None
    return raw


def _checksum(payload: dict) -> str:
    import hashlib

    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _find_external_link(db: Session, *, source_system: str, external_id: str) -> ProjectExternalId | None:
    return (
        db.query(ProjectExternalId)
        .filter(
            ProjectExternalId.source_system == source_system,
            ProjectExternalId.external_id == external_id,
        )
        .one_or_none()
    )


def _find_project_candidates_by_name(db: Session, *, name: str) -> list[Project]:
    normalized = name.strip().lower()
    return db.query(Project).filter(func.lower(func.trim(Project.name)) == normalized).all()


# --------------------------------------------------------------------------
# 1) Ingestão — persistente, nunca toca em `projects`.
# --------------------------------------------------------------------------


def ingest_export(
    db: Session,
    *,
    payload: dict,
    source_system: str = SOURCE_LEGACY_JSON,
    actor_person_id: uuid.UUID | None = None,
) -> ImportBatch:
    if "projects" not in payload or not isinstance(payload["projects"], dict):
        raise ValueError("payload inválido: esperado um objeto com a chave 'projects'")

    now = dt.datetime.now(dt.timezone.utc)
    batch = ImportBatch(
        id=new_uuid(),
        source_system=source_system,
        status="ready_for_review",
        started_at=now,
        finished_at=now,
        started_by_person_id=actor_person_id,
        checksum=_checksum(payload),
        raw_payload_json=json.dumps(payload, ensure_ascii=False),
        records_seen=0,
        records_ready=0,
        records_conflicted=0,
    )
    db.add(batch)
    db.flush()

    # Deteção de duplicados DENTRO deste lote — necessária porque a
    # ingestão nunca escreve em `projects` a meio da execução, logo uma
    # consulta a `projects` não veria os registos anteriores deste mesmo
    # lote. Âmbito conhecido: não deteta duplicados ENTRE lotes diferentes
    # ainda não promovidos — ver docs/DECISIONS.md.
    seen_in_batch: dict[str, list[str]] = {}

    for legacy_id, record in payload["projects"].items():
        batch.records_seen += 1
        external_id = str(legacy_id)
        mapped = _map_legacy_fields(record)
        name = mapped["name"]

        staging = StagingProjectRecord(
            id=new_uuid(),
            import_batch_id=batch.id,
            source_system=source_system,
            external_id=external_id,
            raw_record_json=json.dumps(record, ensure_ascii=False),
            mapped_fields_json=json.dumps(mapped, ensure_ascii=False),
        )

        existing_link = _find_external_link(db, source_system=source_system, external_id=external_id)
        if existing_link is not None:
            staging.status = "ready_to_promote"
            staging.resolved_action = "update_existing"
            staging.resolved_target_project_id = existing_link.project_id
            staging.resolved_at = now
            staging.resolution_note = "Ligação já existente por ID externo — atualização, não é conflito."
            batch.records_ready += 1
            db.add(staging)
            continue

        if not name:
            staging.status = "conflict"
            staging.conflict_reason = "no_name"
            batch.records_conflicted += 1
            db.add(staging)
            continue

        normalized_name = name.lower()
        db_candidates = _find_project_candidates_by_name(db, name=name)
        batch_candidates = seen_in_batch.get(normalized_name, [])
        candidate_refs = [str(c.id) for c in db_candidates] + [f"batch:{ref}" for ref in batch_candidates]

        if candidate_refs:
            staging.status = "conflict"
            staging.conflict_reason = "ambiguous_match" if len(candidate_refs) > 1 else "duplicate"
            staging.candidate_project_ids_json = json.dumps(candidate_refs)
            batch.records_conflicted += 1
            seen_in_batch.setdefault(normalized_name, []).append(external_id)
            db.add(staging)
            continue

        staging.status = "ready_to_promote"
        staging.resolved_action = "create_new"
        staging.resolved_at = now
        staging.resolution_note = "Sem candidatos — auto-resolvido para criação."
        batch.records_ready += 1
        seen_in_batch.setdefault(normalized_name, []).append(external_id)
        db.add(staging)

    db.commit()
    db.refresh(batch)
    return batch


# --------------------------------------------------------------------------
# 2) Revisão de conflitos — só isto tira um registo de `conflict`.
# --------------------------------------------------------------------------


def resolve_conflict(
    db: Session,
    *,
    staging_record_id: uuid.UUID,
    action: ResolvedAction,
    actor_person_id: uuid.UUID,
    target_project_id: uuid.UUID | None = None,
    note: str = "",
) -> StagingProjectRecord:
    record = db.get(StagingProjectRecord, staging_record_id)
    if record is None:
        raise ValueError(f"registo de staging não encontrado: {staging_record_id}")
    if record.status != "conflict":
        raise ValueError(
            f"só é possível resolver um registo em conflito (estado atual: {record.status!r})"
        )
    if action == "link_existing" and target_project_id is None:
        raise ValueError("a ação 'link_existing' exige target_project_id")

    record.resolved_action = action
    record.resolved_target_project_id = target_project_id if action == "link_existing" else None
    record.resolved_by_person_id = actor_person_id
    record.resolved_at = dt.datetime.now(dt.timezone.utc)
    record.resolution_note = note
    record.status = "rejected" if action == "skip" else "ready_to_promote"

    db.commit()
    db.refresh(record)
    return record


# --------------------------------------------------------------------------
# 3) Promoção explícita — só isto escreve em `projects`.
# --------------------------------------------------------------------------


def promote_staging_record(
    db: Session,
    *,
    staging_record_id: uuid.UUID,
    actor_person_id: uuid.UUID,
) -> Project:
    record = db.get(StagingProjectRecord, staging_record_id)
    if record is None:
        raise ValueError(f"registo de staging não encontrado: {staging_record_id}")
    if record.status != "ready_to_promote":
        raise ValueError(
            f"só é possível promover um registo pronto (estado atual: {record.status!r})"
        )

    mapped = json.loads(record.mapped_fields_json)
    canonical = _build_canonical_fields(mapped)
    now = dt.datetime.now(dt.timezone.utc)

    if record.resolved_action == "create_new":
        pm_person = _resolve_pm_person(db, mapped.get("pm_name_raw"))
        project = Project(id=new_uuid(), is_active=True, **canonical)
        project.pm_person_id = pm_person.id if pm_person else None
        db.add(project)
        db.flush()
        db.add(
            ProjectExternalId(
                id=new_uuid(),
                project_id=project.id,
                source_system=record.source_system,
                external_id=record.external_id,
                sync_status="ok",
                synced_at=now,
            )
        )
        for field_name, value in {**canonical, "pm_person_id": project.pm_person_id}.items():
            if value is None:
                continue
            record_project_change(
                db,
                project_id=project.id,
                field_name=field_name,
                old_value=None,
                new_value=str(value),
                source="import_legacy",
                changed_by_person_id=actor_person_id,
                note=f"Criação por promoção do registo de staging {record.id}.",
                related_staging_record_id=record.id,
            )
        target_project = project

    elif record.resolved_action in ("update_existing", "link_existing"):
        target_project_id = record.resolved_target_project_id
        if target_project_id is None:
            raise ValueError(f"registo {record.id} não tem resolved_target_project_id definido")
        project = db.get(Project, target_project_id)
        if project is None:
            raise ValueError(f"projeto alvo não encontrado: {target_project_id}")

        pm_person = _resolve_pm_person(db, mapped.get("pm_name_raw"))
        fields_to_apply = dict(canonical)
        if pm_person is not None:
            fields_to_apply["pm_person_id"] = pm_person.id

        for field_name, new_value in fields_to_apply.items():
            old_value = getattr(project, field_name)
            if old_value == new_value:
                continue
            record_project_change(
                db,
                project_id=project.id,
                field_name=field_name,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None,
                source="import_legacy",
                changed_by_person_id=actor_person_id,
                note=f"Atualização por promoção do registo de staging {record.id}.",
                related_staging_record_id=record.id,
            )
            setattr(project, field_name, new_value)

        if _find_external_link(db, source_system=record.source_system, external_id=record.external_id) is None:
            db.add(
                ProjectExternalId(
                    id=new_uuid(),
                    project_id=project.id,
                    source_system=record.source_system,
                    external_id=record.external_id,
                    sync_status="ok",
                    synced_at=now,
                )
            )
        target_project = project

    else:
        raise ValueError(f"ação de resolução inesperada para promoção: {record.resolved_action!r}")

    record.status = "promoted"
    record.promoted_project_id = target_project.id
    record.promoted_by_person_id = actor_person_id
    record.promoted_at = now

    db.commit()
    db.refresh(target_project)
    return target_project


# --------------------------------------------------------------------------
# Rollback — nunca apaga histórico; só acrescenta entradas que revertem.
# --------------------------------------------------------------------------


def rollback_promotion(
    db: Session,
    *,
    staging_record_id: uuid.UUID,
    actor_person_id: uuid.UUID,
    reason: str,
) -> StagingProjectRecord:
    record = db.get(StagingProjectRecord, staging_record_id)
    if record is None:
        raise ValueError(f"registo de staging não encontrado: {staging_record_id}")
    if record.status != "promoted":
        raise ValueError(
            f"só é possível reverter um registo promovido (estado atual: {record.status!r})"
        )
    if record.promoted_project_id is None:
        raise ValueError(f"registo {record.id} está 'promoted' mas sem promoted_project_id — estado inconsistente")

    project = db.get(Project, record.promoted_project_id)
    if project is None:
        raise ValueError(f"projeto promovido não encontrado: {record.promoted_project_id}")

    if record.resolved_action == "create_new":
        # A promoção criou este projeto de raiz: reverter significa
        # inativá-lo — nunca apagar, preserva todo o histórico já escrito.
        old_active = str(project.is_active)
        project.is_active = False
        record_project_change(
            db,
            project_id=project.id,
            field_name="is_active",
            old_value=old_active,
            new_value="False",
            source="migration_rollback",
            changed_by_person_id=actor_person_id,
            note=f"Rollback da promoção (criação) do registo de staging {record.id}: {reason}",
            related_staging_record_id=record.id,
        )
    else:
        # A promoção só atualizou um projeto já existente: reaplica o
        # valor anterior de cada campo que essa promoção específica alterou
        # (identificados por related_staging_record_id, nunca por texto),
        # gerando uma NOVA entrada de histórico por campo revertido.
        changed_entries = (
            db.query(ProjectHistory)
            .filter(
                ProjectHistory.project_id == project.id,
                ProjectHistory.related_staging_record_id == record.id,
                ProjectHistory.source == "import_legacy",
            )
            .order_by(ProjectHistory.changed_at.asc())
            .all()
        )
        for entry in changed_entries:
            restored_value = _string_to_field_value(entry.field_name, entry.old_value)
            current_value = getattr(project, entry.field_name, None)
            if current_value == restored_value:
                continue
            record_project_change(
                db,
                project_id=project.id,
                field_name=entry.field_name,
                old_value=str(current_value) if current_value is not None else None,
                new_value=str(restored_value) if restored_value is not None else None,
                source="migration_rollback",
                changed_by_person_id=actor_person_id,
                note=f"Rollback da promoção (atualização) do registo de staging {record.id}: {reason}",
                related_staging_record_id=record.id,
            )
            setattr(project, entry.field_name, restored_value)

    record.status = "pending_review"
    record.reverted_by_person_id = actor_person_id
    record.reverted_at = dt.datetime.now(dt.timezone.utc)
    record.reverted_reason = reason

    db.commit()
    db.refresh(record)
    return record
