"""Modelos append-only do Banco de Horas.

Os valores contabilizados são segundos inteiros.  Correções e anulações são
novas linhas ligadas à origem; nenhum lançamento histórico é editado ou
apagado pelo domínio.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import GUID, Base
from app.models.base import TimestampMixin, UUIDPk

ENTRY_MODES = frozenset({"standard", "saturday", "manual", "imported"})
ADJUSTMENT_KINDS = frozenset({"opening", "correction", "consumption"})
IMPORT_BATCH_STATUSES = frozenset({"pending", "applied"})


class TimeBankEntry(UUIDPk, TimestampMixin, Base):
    __tablename__ = "time_bank_entries"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_time_bank_entry_source_key"),
        UniqueConstraint("reversal_of_id", name="uq_time_bank_entry_one_reversal"),
        Index("ix_time_bank_entries_person_date", "person_id", "work_date"),
    )

    person_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("people.id"), nullable=False)
    work_date: Mapped[dt.date] = mapped_column(Date(), nullable=False)
    start_minute: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    end_minute: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    lunch_taken: Mapped[bool | None] = mapped_column(Boolean(), nullable=True)
    balance_seconds: Mapped[int] = mapped_column(Integer(), nullable=False)
    calculated_seconds: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    calculation_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
    review_flags: Mapped[dict] = mapped_column(JSON(), default=dict, nullable=False)
    provenance: Mapped[dict] = mapped_column(JSON(), default=dict, nullable=False)
    source_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("time_bank_entries.id"), nullable=True
    )

    person = relationship("Person", foreign_keys=[person_id])
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])
    reversal_of = relationship("TimeBankEntry", remote_side="TimeBankEntry.id", foreign_keys=[reversal_of_id])


class TimeBankAdjustment(UUIDPk, TimestampMixin, Base):
    __tablename__ = "time_bank_adjustments"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_time_bank_adjustment_source_key"),
        UniqueConstraint("reversal_of_id", name="uq_time_bank_adjustment_one_reversal"),
        Index("ix_time_bank_adjustments_person_date", "person_id", "effective_date"),
    )

    person_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("people.id"), nullable=False)
    effective_date: Mapped[dt.date] = mapped_column(Date(), nullable=False)
    delta_seconds: Mapped[int] = mapped_column(Integer(), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    provenance: Mapped[dict] = mapped_column(JSON(), default=dict, nullable=False)
    source_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("time_bank_adjustments.id"), nullable=True
    )

    person = relationship("Person", foreign_keys=[person_id])
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])
    reversal_of = relationship("TimeBankAdjustment", remote_side="TimeBankAdjustment.id", foreign_keys=[reversal_of_id])


class TimeBankAudit(UUIDPk, Base):
    __tablename__ = "time_bank_audit"

    actor_user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    data: Mapped[dict] = mapped_column(JSON(), default=dict, nullable=False)
    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TimeBankImportBatch(UUIDPk, Base):
    __tablename__ = "time_bank_import_batches"
    __table_args__ = (
        UniqueConstraint("sha256", "parser_version", name="uq_time_bank_import_hash_version"),
    )

    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    source_year: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    parsed_payload: Mapped[dict] = mapped_column(JSON(), default=dict, nullable=False)
    resolutions: Mapped[dict] = mapped_column(JSON(), default=dict, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    applied_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by_user = relationship("User", foreign_keys=[created_by_user_id])
