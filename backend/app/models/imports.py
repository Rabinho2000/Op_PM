"""Importação de dados de campo (notas iniciais, Excel de licenciamento) —
distinto de `app/models/migration.py` (`ImportBatch`/`StagingProjectRecord`),
que é específico da migração de projetos legados inteiros. Aqui o
conflito é por campo, não por projeto inteiro. Ver docs/DATA_IMPORTS.md.

Mesmos princípios de `app/migration/staging.py`: nunca escrever direto em
`Project`/dados satélite — sempre ingestão → conflitos → confirmação
explícita → aplicação, com auditoria completa e o payload original
sempre preservado.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk

SOURCE_TYPE_NOTES_HTML = "notes_html"
SOURCE_TYPE_NOTES_JSON = "notes_json"
SOURCE_TYPE_LICENSING_EXCEL = "licensing_excel"
SOURCE_TYPES: frozenset[str] = frozenset(
    {SOURCE_TYPE_NOTES_HTML, SOURCE_TYPE_NOTES_JSON, SOURCE_TYPE_LICENSING_EXCEL}
)

BATCH_STATUS_PENDING_CONFIRMATION = "pending_confirmation"
BATCH_STATUS_APPLIED = "applied"
BATCH_STATUS_REJECTED = "rejected"
BATCH_STATUSES: frozenset[str] = frozenset(
    {BATCH_STATUS_PENDING_CONFIRMATION, BATCH_STATUS_APPLIED, BATCH_STATUS_REJECTED}
)

RECORD_STATUS_PENDING = "pending"
RECORD_STATUS_APPLIED = "applied"
RECORD_STATUS_REJECTED = "rejected"

CONFLICT_RESOLUTION_PENDING = "pending"
CONFLICT_RESOLUTION_USE_NEW = "use_new"
CONFLICT_RESOLUTION_KEEP_OLD = "keep_old"
CONFLICT_RESOLUTIONS: frozenset[str] = frozenset(
    {CONFLICT_RESOLUTION_PENDING, CONFLICT_RESOLUTION_USE_NEW, CONFLICT_RESOLUTION_KEEP_OLD}
)


class FieldImportBatch(UUIDPk, TimestampMixin, Base):
    """Um por ficheiro submetido. `source_file_hash` impede reimportar o
    mesmo ficheiro (dedução de duplicados)."""

    __tablename__ = "field_import_batches"
    __table_args__ = (UniqueConstraint("source_file_hash", name="uq_field_import_source_hash"),)

    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    form_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Payload extraído (nunca o HTML/Excel original em si — só o JSON/dados
    # normalizados) — preservado tal como veio, mesmo que a normalização
    # de campos falhe parcialmente.
    raw_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=BATCH_STATUS_PENDING_CONFIRMATION, nullable=False)
    started_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    applied_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    applied_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    records: Mapped[list["FieldImportRecord"]] = relationship(back_populates="batch")


class FieldImportRecord(UUIDPk, TimestampMixin, Base):
    """Uma entidade-alvo detetada dentro de um lote (hoje: sempre um
    projeto, novo ou existente — um lote de notas iniciais tem
    tipicamente um só registo; o Excel de licenciamento pode ter muitos)."""

    __tablename__ = "field_import_records"

    batch_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("field_import_batches.id"), nullable=False)
    target_project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=True)
    is_new_project: Mapped[bool] = mapped_column(default=False, nullable=False)
    # email | phone | address | none | ambiguous | manual
    match_strategy: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    # Candidatos detetados quando a correspondência é ambígua (JSON de
    # UUIDs) — nunca liga automaticamente, exige escolha explícita em apply.
    candidate_project_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    mapped_fields_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=RECORD_STATUS_PENDING, nullable=False)
    promoted_project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=True)

    batch: Mapped["FieldImportBatch"] = relationship(back_populates="records")
    conflicts: Mapped[list["FieldImportConflict"]] = relationship(back_populates="record")


class FieldImportConflict(UUIDPk, TimestampMixin, Base):
    """Um valor divergente do já existente, por campo — nunca substituído
    em silêncio (D-005 aplicado a nível de campo, não de projeto)."""

    __tablename__ = "field_import_conflicts"

    record_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("field_import_records.id"), nullable=False)
    # project | installation | licensing | communication | surplus_contract
    target_entity: Mapped[str] = mapped_column(String(32), nullable=False)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution: Mapped[str] = mapped_column(String(16), default=CONFLICT_RESOLUTION_PENDING, nullable=False)
    resolved_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    record: Mapped["FieldImportRecord"] = relationship(back_populates="conflicts")


__all__ = ["FieldImportBatch", "FieldImportRecord", "FieldImportConflict"]
