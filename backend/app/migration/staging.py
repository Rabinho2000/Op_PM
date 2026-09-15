"""Migração em staging: reconciliação de PM → ingestão → revisão de
conflitos → promoção explícita. Ver `app/models/migration.py` para o
modelo de dados e docs/DECISIONS.md (D-005, D-017, D-023) para a
justificação do desenho.

Etapa 0, ANTES desta: `app.migration.people_reconciliation.reconcile_pm_names`
regista, para revisão humana, qualquer nome de PM do export que não
corresponda sem ambiguidade a um `Person` conhecido. As funções abaixo
nunca resolvem isso sozinhas — usam sempre
`people_reconciliation.classify_pm_name` para saber se um PM está
resolvido, ignorado (decisão humana explícita), ou ainda por resolver.

Quatro funções fazem as etapas exigidas, nunca misturadas:

- `ingest_export`: lê um export externo e cria registos de staging.
  NUNCA escreve em `projects`. Por omissão, persistente (commit imediato)
  — a ingestão em si já não pode corromper dados canónicos. Aceita
  `dry_run=True` (usado pelo piloto de staging, `docs/STAGING_RUNBOOK.md`
  secção "Piloto") para pré-visualizar o resumo (contagens, conflitos) sem
  deixar nenhum vestígio — nem nas tabelas de staging: a transação é
  revertida (`db.rollback()`) pelo chamador depois de ler o resumo, nunca
  commitada. Aceita também `only_external_ids`/`limit` para processar só
  um subconjunto do payload (piloto de 5 a 10 projetos antes dos 295 —
  ver `app/cli/ingest_staging.py --only-ids`/`--limit`). Um registo com PM
  presente mas não resolvido fica em `conflict` (`pm_unresolved`) — nunca
  segue para promoção como se não tivesse PM.
- `resolve_conflict`: decisão humana sobre um registo em conflito
  (`create_new` / `link_existing` / `skip` para conflitos de projeto;
  `proceed_without_pm` só para `pm_unresolved`). Só isto (ou
  `retry_pm_resolution`) tira um registo do estado `conflict`.
- `retry_pm_resolution`: reclassifica o PM de um registo bloqueado por
  `pm_unresolved` — usado depois de a reconciliação de pessoas resolver o
  nome em causa, para desbloquear sem repetir a ingestão.
- `promote_staging_record`: só isto escreve em `projects`. Gera sempre
  entradas de `project_history` (nunca uma escrita silenciosa) e
  recusa-se a promover um registo com PM presente, não resolvido, e sem
  decisão explícita de prosseguir sem PM — mesmo que o estado do registo
  tenha sido manipulado diretamente (defesa em profundidade, D-023).
- `rollback_promotion`: desfaz uma promoção. Nunca apaga histórico — só
  acrescenta novas entradas que revertem os valores, e marca o registo de
  staging como pendente de nova decisão.

Nesta fase, estas funções só são exercidas com dados sintéticos
(`backend/fixtures/`, `backend/tests/test_staging_persistence.py`,
`backend/tests/test_people_reconciliation.py`). Migrar os 295 projetos
reais é trabalho de uma fase futura, nunca a partir deste repositório
público — ver docs/PLAN.md.
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
from app.migration.people_reconciliation import classify_pm_name
from app.models.migration import ImportBatch, StagingProjectRecord
from app.models.project import Project, ProjectExternalId, ProjectHistory

SOURCE_LEGACY_JSON = "legacy_json"

ResolvedAction = Literal["create_new", "link_existing", "skip", "proceed_without_pm"]

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
_CANONICAL_UUID_FIELDS = ("pm_person_id",)


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
    if field_name in _CANONICAL_UUID_FIELDS:
        try:
            return uuid.UUID(raw)
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


def resolve_candidate_project_ids(db: Session, record: StagingProjectRecord) -> set[str]:
    """Traduz `candidate_project_ids_json` para o conjunto de UUIDs de
    `Project` válidos como alvo de `link_existing` (D-030). Inclui tanto
    candidatos diretos (já eram projetos reais no momento da deteção) como
    candidatos `'batch:<external_id>'` cujo projeto entretanto foi
    promovido — um duplicado detetado dentro do mesmo lote (D-017) só
    aponta para um ID real depois de o outro registo do lote ser
    promovido; sem esta resolução, ligar a esse projeto legítimo seria
    injustamente tratado como "fora dos candidatos". Usado tanto pela
    validação em `resolve_conflict` como pela API
    (`app/api/routes_migration.py`), para nunca haver duas lógicas
    divergentes sobre o que conta como candidato válido."""
    raw_candidates = json.loads(record.candidate_project_ids_json or "[]")
    resolved: set[str] = set()
    for ref in raw_candidates:
        if ref.startswith("batch:"):
            legacy_external_id = ref[len("batch:") :]
            link = _find_external_link(db, source_system=record.source_system, external_id=legacy_external_id)
            if link is not None:
                resolved.add(str(link.project_id))
        else:
            resolved.add(ref)
    return resolved


def _finalize_status_given_pm(record: StagingProjectRecord, pm_classification) -> None:
    """Ponto único de decisão: dado que a parte de PROJETO da resolução já
    está definida em `record.resolved_action`/`resolved_target_project_id`,
    decide o status final consoante o PM. Usado tanto pela ingestão (para
    os casos sem conflito de projeto) como por `resolve_conflict` (depois
    de um conflito de projeto ser resolvido) — nunca duas lógicas
    divergentes para a mesma decisão (D-023).

    Bloqueia sempre que o PM está presente e não resolvido, mesmo que o
    conflito original do registo fosse sobre outra coisa (nome
    ambíguo/duplicado) — nunca deixa um PM por resolver passar só porque
    o problema que o trouxe a 'conflict' era outro."""
    if pm_classification.status == "unresolved" and not record.pm_explicitly_unassigned:
        record.status = "conflict"
        record.conflict_reason = "pm_unresolved"
        record.candidate_person_ids_json = json.dumps(pm_classification.candidate_person_ids)
        return
    if pm_classification.status == "ignored":
        record.pm_explicitly_unassigned = True
    record.status = "ready_to_promote"
    record.conflict_reason = None


# --------------------------------------------------------------------------
# 1) Ingestão — persistente, nunca toca em `projects`.
# --------------------------------------------------------------------------


def ingest_export(
    db: Session,
    *,
    payload: dict,
    source_system: str = SOURCE_LEGACY_JSON,
    actor_person_id: uuid.UUID | None = None,
    only_external_ids: set[str] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> ImportBatch:
    """`only_external_ids`/`limit` restringem o processamento a um
    subconjunto das chaves de `payload["projects"]` (piloto de staging —
    nunca alteram o `raw_payload_json` gravado, que preserva sempre o
    payload completo tal como recebido, mesmo quando só uma parte dele foi
    processada nesta chamada). `dry_run=True` faz tudo o resto de forma
    idêntica (incl. deteção de duplicados/conflitos contra a base de dados
    real) mas não commita — cabe ao chamador (`app/cli/ingest_staging.py`)
    chamar `db.rollback()` depois de ler o resumo, para não deixar
    nenhuma linha em `import_batches`/`staging_project_records`."""
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

    items = list(payload["projects"].items())
    if only_external_ids is not None:
        items = [(legacy_id, record) for legacy_id, record in items if str(legacy_id) in only_external_ids]
    if limit is not None:
        items = items[:limit]

    for legacy_id, record in items:
        batch.records_seen += 1
        external_id = str(legacy_id)
        mapped = _map_legacy_fields(record)
        name = mapped["name"]
        pm_classification = classify_pm_name(db, mapped.get("pm_name_raw"))

        staging = StagingProjectRecord(
            id=new_uuid(),
            import_batch_id=batch.id,
            source_system=source_system,
            external_id=external_id,
            raw_record_json=json.dumps(record, ensure_ascii=False),
            mapped_fields_json=json.dumps(mapped, ensure_ascii=False),
            pm_name_raw=mapped.get("pm_name_raw") or None,
            pm_explicitly_unassigned=(pm_classification.status == "ignored"),
        )

        existing_link = _find_external_link(db, source_system=source_system, external_id=external_id)
        if existing_link is not None:
            staging.resolved_action = "update_existing"
            staging.resolved_target_project_id = existing_link.project_id
            staging.resolved_at = now
            staging.resolution_note = "Ligação já existente por ID externo — atualização, não é conflito."
            _finalize_status_given_pm(staging, pm_classification)
            if staging.status == "conflict":
                batch.records_conflicted += 1
            else:
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
        seen_in_batch.setdefault(normalized_name, []).append(external_id)

        if candidate_refs:
            # Conflito de nome de projeto — o PM só será verificado quando
            # este conflito for resolvido (ver resolve_conflict), porque
            # ainda não se sabe se resolved_action será create_new ou
            # link_existing a outro projeto (que pode já ter PM).
            staging.status = "conflict"
            staging.conflict_reason = "ambiguous_match" if len(candidate_refs) > 1 else "duplicate"
            staging.candidate_project_ids_json = json.dumps(candidate_refs)
            batch.records_conflicted += 1
            db.add(staging)
            continue

        staging.resolved_action = "create_new"
        staging.resolved_at = now
        staging.resolution_note = "Sem candidatos — auto-resolvido para criação."
        _finalize_status_given_pm(staging, pm_classification)
        if staging.status == "conflict":
            batch.records_conflicted += 1
        else:
            batch.records_ready += 1
        db.add(staging)

    if dry_run:
        db.flush()
        db.refresh(batch)
    else:
        db.commit()
        db.refresh(batch)
    return batch


def summarize_import_batch(db: Session, batch: ImportBatch) -> dict[str, int]:
    """Contagens de um lote de ingestão, para revisão humana antes de
    resolver conflitos/promover — usado pelo comando de ingestão
    controlada (`app/cli/ingest_staging.py`) e disponível a quem quiser o
    mesmo resumo por outra via (ex. um futuro endpoint só de leitura).
    Lê sempre `mapped_fields_json` dos registos já persistidos, nunca o
    payload bruto de novo — para nunca divergir de que campos
    `_map_legacy_fields` realmente extraiu.

    Nunca inclui informação alguma sobre PROJECTS — só sobre os registos de
    STAGING deste lote, porque a ingestão nunca lê nem escreve em
    `projects` (D-005/D-017)."""
    records = db.query(StagingProjectRecord).filter(StagingProjectRecord.import_batch_id == batch.id).all()

    distinct_pm_names: set[str] = set()
    with_email = 0
    with_contact = 0
    with_coordinates = 0
    for record in records:
        mapped = json.loads(record.mapped_fields_json)
        pm_name_raw = mapped.get("pm_name_raw")
        if pm_name_raw and str(pm_name_raw).strip():
            distinct_pm_names.add(str(pm_name_raw).strip().lower())
        if mapped.get("email"):
            with_email += 1
        if mapped.get("contact"):
            with_contact += 1
        if mapped.get("lat") is not None and mapped.get("lon") is not None:
            with_coordinates += 1

    return {
        "projects_seen": batch.records_seen,
        "ready_to_promote": batch.records_ready,
        "conflicts": batch.records_conflicted,
        "distinct_pm_names": len(distinct_pm_names),
        "with_email": with_email,
        "with_contact": with_contact,
        "with_coordinates": with_coordinates,
    }


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
    allow_target_outside_candidates: bool = False,
) -> StagingProjectRecord:
    """`allow_target_outside_candidates` é uma segunda barreira, a nível de
    serviço (defesa em profundidade — D-030): a decisão de permitir isto
    ou não é do chamador (a API, que verifica
    `migration.link_arbitrary_project` e exige uma nota não vazia antes de
    sequer chegar aqui) — mas mesmo que alguém chame esta função
    diretamente sem essa verificação, o valor por omissão (`False`)
    continua a recusar ligar a um projeto que o sistema não detetou como
    candidato."""
    record = db.get(StagingProjectRecord, staging_record_id)
    if record is None:
        raise ValueError(f"registo de staging não encontrado: {staging_record_id}")
    if record.status != "conflict":
        raise ValueError(
            f"só é possível resolver um registo em conflito (estado atual: {record.status!r})"
        )

    if action == "proceed_without_pm":
        if record.conflict_reason != "pm_unresolved":
            raise ValueError(
                "a ação 'proceed_without_pm' só é válida para conflitos 'pm_unresolved' "
                f"(razão atual: {record.conflict_reason!r})"
            )
        # O resolved_action/resolved_target_project_id do PROJETO já
        # tinham sido calculados na ingestão (D-023) — só a barreira do PM
        # é levantada aqui, por decisão humana explícita.
        record.pm_explicitly_unassigned = True
        record.resolved_by_person_id = actor_person_id
        record.resolved_at = dt.datetime.now(dt.timezone.utc)
        record.resolution_note = note or "Prosseguir sem PM (decisão humana explícita)."
        record.status = "ready_to_promote"
        db.commit()
        db.refresh(record)
        return record

    if record.conflict_reason == "pm_unresolved":
        raise ValueError(
            f"registo {record.id} está bloqueado por PM não resolvido — use "
            "'proceed_without_pm' ou resolva o PM (app.migration.people_reconciliation) "
            "e chame retry_pm_resolution, não resolve_conflict com outras ações"
        )
    if action == "link_existing" and target_project_id is None:
        raise ValueError("a ação 'link_existing' exige target_project_id")

    if action == "link_existing":
        # D-030: target_project_id tem de estar entre os candidatos
        # detetados automaticamente (resolve_candidate_project_ids —
        # inclui candidatos 'batch:' já promovidos), a menos que
        # allow_target_outside_candidates=True E uma nota não vazia
        # expliquem a decisão — nunca ligar "às cegas" a um projeto
        # arbitrário sem essas duas condições.
        valid_candidate_ids = resolve_candidate_project_ids(db, record)
        if str(target_project_id) not in valid_candidate_ids:
            if not allow_target_outside_candidates:
                raise ValueError(
                    f"target_project_id {target_project_id} não está entre os candidatos "
                    f"detetados para este registo ({sorted(valid_candidate_ids) or 'nenhum'}) — "
                    "ligar a um projeto fora dos candidatos exige "
                    "allow_target_outside_candidates=True e uma nota não vazia"
                )
            if not note or not note.strip():
                raise ValueError(
                    "ligar a um projeto fora dos candidatos detetados exige uma nota não vazia "
                    "a justificar a decisão"
                )

    record.resolved_action = action
    record.resolved_target_project_id = target_project_id if action == "link_existing" else None
    record.resolved_by_person_id = actor_person_id
    record.resolved_at = dt.datetime.now(dt.timezone.utc)
    record.resolution_note = note

    if action == "skip":
        record.status = "rejected"
    else:
        # O conflito de PROJETO ficou resolvido — mas só agora é que se
        # sabe resolved_action/resolved_target_project_id, por isso o PM
        # só é verificado aqui (nunca antes) para este caminho. Reusa a
        # mesma decisão de app/migration/staging.py:_finalize_status_given_pm
        # usada na ingestão, para nunca haver duas lógicas divergentes.
        mapped = json.loads(record.mapped_fields_json)
        pm_classification = classify_pm_name(db, mapped.get("pm_name_raw"))
        _finalize_status_given_pm(record, pm_classification)

    db.commit()
    db.refresh(record)
    return record


def retry_pm_resolution(db: Session, *, staging_record_id: uuid.UUID) -> StagingProjectRecord:
    """Reclassifica o PM de um registo bloqueado por `pm_unresolved` —
    chamar depois de `people_reconciliation.resolve_person_reconciliation`
    resolver o nome em causa, para desbloquear sem repetir a ingestão."""
    record = db.get(StagingProjectRecord, staging_record_id)
    if record is None:
        raise ValueError(f"registo de staging não encontrado: {staging_record_id}")
    if record.status != "conflict" or record.conflict_reason != "pm_unresolved":
        raise ValueError(
            "só aplicável a um registo bloqueado por 'pm_unresolved' "
            f"(estado atual: {record.status!r}/{record.conflict_reason!r})"
        )

    mapped = json.loads(record.mapped_fields_json)
    classification = classify_pm_name(db, mapped.get("pm_name_raw"))

    if classification.status == "unresolved":
        record.candidate_person_ids_json = json.dumps(classification.candidate_person_ids)
        db.commit()
        db.refresh(record)
        return record  # continua em conflito — reconciliação ainda não resolveu este nome

    if classification.status == "ignored":
        record.pm_explicitly_unassigned = True

    record.status = "ready_to_promote"
    record.conflict_reason = None
    record.resolved_at = dt.datetime.now(dt.timezone.utc)
    record.resolution_note = (record.resolution_note or "") + " | PM resolvido via reconciliação."

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

    # Defesa em profundidade (D-023): mesmo que o estado do registo tenha
    # chegado aqui como 'ready_to_promote' por alguma via que não passou
    # pelas barreiras normais de ingest_export/resolve_conflict, a
    # promoção NUNCA prossegue com um PM presente e não resolvido sem uma
    # decisão explícita de prosseguir sem ele.
    pm_classification = classify_pm_name(db, mapped.get("pm_name_raw"))
    if pm_classification.status == "unresolved" and not record.pm_explicitly_unassigned:
        raise ValueError(
            f"registo {record.id} tem um PM presente ('{mapped.get('pm_name_raw')}') "
            "mas não resolvido, e não foi marcado para prosseguir sem PM — promoção "
            "bloqueada (nunca promover silenciosamente um projeto com PM conhecido "
            "mas não resolvido). Use resolve_conflict('proceed_without_pm') ou "
            "resolva o nome em app.migration.people_reconciliation e chame "
            "retry_pm_resolution."
        )
    pm_person = pm_classification.person

    if record.resolved_action == "create_new":
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


# --------------------------------------------------------------------------
# 5) Repetir a promoção de um registo revertido — nunca automático.
# --------------------------------------------------------------------------


def retry_promotion_after_rollback(
    db: Session, *, staging_record_id: uuid.UUID, actor_person_id: uuid.UUID
) -> StagingProjectRecord:
    """Prepara para promover outra vez um registo já revertido por
    `rollback_promotion` — nunca automático (um registo revertido fica
    'pending_review' de propósito, exigindo esta decisão humana explícita
    antes de voltar a 'ready_to_promote', em vez de reaparecer sozinho na
    fila de promoção como se o rollback nunca tivesse acontecido).

    Caso especial que esta função trata, e `promote_staging_record` sozinho
    não sabe tratar em segurança: se a promoção original tinha
    `resolved_action='create_new'`, o projeto **já existe** (foi criado
    nessa promoção; o rollback só o desativou, nunca o apaga — D-017).
    Promover outra vez com `resolved_action='create_new'` inalterado
    tentaria criar um SEGUNDO projeto com o mesmo `external_id`, o que
    violaria a unicidade de `ProjectExternalId` (source_system,
    external_id) e duplicaria o projeto — por isso esta função reescreve
    `resolved_action` para `'update_existing'`, apontado ao mesmo
    `promoted_project_id` de antes, e reativa explicitamente o projeto
    (`is_active=True`, com entrada de histórico própria, fonte
    `migration_retry`) antes de `promote_staging_record` reaplicar os
    campos mapeados. Para `resolved_action` já `'update_existing'`/
    `'link_existing'`, o projeto-alvo é o mesmo de sempre — só a
    reativação é feita aqui, o resto é igual a uma promoção normal.

    Reaplica a mesma verificação de PM (`_finalize_status_given_pm`) já
    usada em `ingest_export`/`resolve_conflict`/`retry_pm_resolution` —
    nunca duas lógicas divergentes sobre quando um registo está pronto
    para promoção."""
    record = db.get(StagingProjectRecord, staging_record_id)
    if record is None:
        raise ValueError(f"registo de staging não encontrado: {staging_record_id}")
    if record.status != "pending_review" or record.reverted_at is None:
        raise ValueError(
            "só é possível repetir a promoção de um registo revertido por rollback_promotion "
            f"(estado atual: {record.status!r}, reverted_at={record.reverted_at!r})"
        )
    if record.promoted_project_id is None:
        raise ValueError(f"registo {record.id} não tem promoted_project_id da promoção original — estado inconsistente")

    project = db.get(Project, record.promoted_project_id)
    if project is None:
        raise ValueError(f"projeto da promoção original não encontrado: {record.promoted_project_id}")

    if record.resolved_action == "create_new":
        record.resolved_action = "update_existing"
        record.resolved_target_project_id = record.promoted_project_id

    if not project.is_active:
        record_project_change(
            db,
            project_id=project.id,
            field_name="is_active",
            old_value="False",
            new_value="True",
            source="migration_retry",
            changed_by_person_id=actor_person_id,
            note=f"Reativação antes de repetir a promoção do registo de staging {record.id} (após rollback).",
            related_staging_record_id=record.id,
        )
        project.is_active = True

    mapped = json.loads(record.mapped_fields_json)
    pm_classification = classify_pm_name(db, mapped.get("pm_name_raw"))
    _finalize_status_given_pm(record, pm_classification)

    db.commit()
    db.refresh(record)
    return record
