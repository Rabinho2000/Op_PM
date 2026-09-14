"""Migração em staging: ingestão persistente de um export externo, fila de
conflitos para revisão manual, e promoção explícita para `projects`.

Substitui o desenho anterior (`SyncRun`/`SyncConflict`, Fase 0 inicial), que
decidia tudo dentro de uma única função `dry_run`/`apply` e nunca persistia
nada em modo `dry_run`. Aqui a ingestão é sempre persistente — nunca toca em
`projects`, por isso não há necessidade de um modo "experimental" — e a
escrita em `projects` só acontece na promoção, um passo explícito e
distinto. Ver `app/migration/staging.py` e docs/DECISIONS.md D-005/D-017.

Fluxo de uma `StagingProjectRecord`:

    pending_review ──(sem nome)──────────────► conflict (no_name)
                    ──(nome ambíguo/duplicado)─► conflict (ambiguous_match|duplicate)
                    ──(PM presente mas não resolvido)► conflict (pm_unresolved)
                    ──(sem candidato / já ligado, PM ok)► ready_to_promote
    conflict        ──(resolve_conflict)───────► ready_to_promote | rejected
    conflict (pm_unresolved) ──(resolve_conflict 'proceed_without_pm')──► ready_to_promote
                              ──(retry_pm_resolution, após reconciliação)──► ready_to_promote | conflict
    ready_to_promote──(promote_staging_record)──► promoted
    promoted        ──(rollback_promotion)─────► pending_review (com reverted_at preenchido)

Reconciliação de PM (ver docs/DECISIONS.md D-023 e
`app/migration/people_reconciliation.py`): um nome de PM no export legado
que não corresponda exatamente a um `Person` já conhecido nunca é
resolvido silenciosamente — nem durante a ingestão, nem durante a
promoção. Fica registado em `PersonReconciliationItem`, para revisão
humana explícita, e bloqueia a promoção do(s) projeto(s) correspondente(s)
até ser resolvido (ligar a uma pessoa existente, criar uma nova, ou marcar
como "ignorar" — decisão sempre humana).
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk


class ImportBatch(UUIDPk, TimestampMixin, Base):
    """Uma execução de ingestão de um export externo. Persistente por
    desenho — nunca escreve em `projects`, só em `staging_project_records`;
    por isso não distingue "dry run" de "apply" como a versão anterior."""

    __tablename__ = "import_batches"

    source_system: Mapped[str] = mapped_column(String(32), nullable=False)  # legacy_json | clickup | financial
    # ready_for_review (há registos por rever/promover) | closed (todos
    # os registos foram promovidos ou rejeitados)
    status: Mapped[str] = mapped_column(String(32), default="ready_for_review", nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    # Payload de origem completo, preservado verbatim para sempre — nunca
    # editado depois da ingestão. Permite re-derivar/re-auditar os campos
    # mapeados se a lógica de normalização mudar mais tarde.
    raw_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    records_seen: Mapped[int] = mapped_column(Integer, default=0)
    records_ready: Mapped[int] = mapped_column(Integer, default=0)
    records_conflicted: Mapped[int] = mapped_column(Integer, default=0)


class StagingProjectRecord(UUIDPk, TimestampMixin, Base):
    """Um projeto ainda em staging — nunca uma linha em `projects`."""

    __tablename__ = "staging_project_records"

    import_batch_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("import_batches.id"), nullable=False
    )
    source_system: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)

    # Registo de origem, preservado verbatim.
    raw_record_json: Mapped[str] = mapped_column(Text, nullable=False)
    # Campos extraídos/normalizados a partir de raw_record_json — ver
    # app/migration/staging.py:_map_legacy_fields.
    mapped_fields_json: Mapped[str] = mapped_column(Text, nullable=False)

    # pending_review | conflict | ready_to_promote | promoted | rejected
    status: Mapped[str] = mapped_column(String(32), default="pending_review", nullable=False)
    # no_name | ambiguous_match | duplicate | pm_unresolved
    conflict_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    candidate_project_ids_json: Mapped[str] = mapped_column(Text, default="[]")

    # --- Reconciliação de PM (D-023) ---
    # Nome de PM tal como veio do export legado (duplicado de
    # mapped_fields_json.pm_name_raw só para consulta direta, sem ter de
    # fazer parse do JSON). Vazio/None quando o registo não tem PM.
    pm_name_raw: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # Candidatos de Person quando conflict_reason == 'pm_unresolved'
    # (lista vazia = nome desconhecido; mais do que um = nome ambíguo).
    candidate_person_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    # True só quando um humano decidiu explicitamente prosseguir sem PM
    # (resolve_conflict 'proceed_without_pm') ou quando a reconciliação
    # marcou o nome como 'ignore'. promote_staging_record recusa-se a
    # promover um registo com pm_name_raw preenchido, sem pm resolvido, e
    # sem esta flag — nunca promove silenciosamente (ver
    # app/migration/staging.py:promote_staging_record).
    pm_explicitly_unassigned: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Decisão (humana, ou auto-resolução inequívoca na ingestão) sobre o
    # que fazer com este registo.
    resolved_action: Mapped[str | None] = mapped_column(String(32), nullable=True)  # create_new|update_existing|link_existing|skip
    resolved_target_project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("projects.id"), nullable=True
    )
    resolved_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str] = mapped_column(Text, default="")

    # Resultado da promoção explícita (app/migration/staging.py:promote_staging_record).
    promoted_project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("projects.id"), nullable=True
    )
    promoted_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    promoted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Rollback de uma promoção (app/migration/staging.py:rollback_promotion).
    # Nunca apaga as linhas de project_history já escritas — só acrescenta
    # novas, ver a função para o detalhe.
    reverted_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    reverted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reverted_reason: Mapped[str] = mapped_column(Text, default="")


class PersonReconciliationItem(UUIDPk, TimestampMixin, Base):
    """Fila de revisão para nomes de PM do export legado que não
    correspondem, sem ambiguidade, a um `Person` já conhecido — passo
    explícito ANTES da promoção de qualquer projeto (D-023). Nunca criada
    nem resolvida automaticamente: só `reconcile_pm_names` (deteção) e
    `resolve_person_reconciliation` (decisão humana) escrevem aqui.
    """

    __tablename__ = "person_reconciliation_items"

    # Nome exatamente como apareceu no export (para mostrar ao revisor).
    raw_name: Mapped[str] = mapped_column(String(256), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(256), nullable=False)
    # unknown (zero correspondências) | ambiguous (mais do que uma)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    candidate_person_ids_json: Mapped[str] = mapped_column(Text, default="[]")

    # pending | resolved (ligado a Person existente) | created_new
    # (nova Person criada) | ignored (decisão explícita de não associar)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    resolved_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    resolved_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str] = mapped_column(Text, default="")
