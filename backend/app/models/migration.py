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
                    ──(sem candidato / já ligado)► ready_to_promote
    conflict        ──(resolve_conflict)───────► ready_to_promote | rejected
    ready_to_promote──(promote_staging_record)──► promoted
    promoted        ──(rollback_promotion)─────► pending_review (com reverted_at preenchido)
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
    conflict_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)  # no_name|ambiguous_match|duplicate
    candidate_project_ids_json: Mapped[str] = mapped_column(Text, default="[]")

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
