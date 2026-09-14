"""Execuções de sincronização e fila de conflitos para revisão manual.

Nenhuma sincronização externa (ClickUp, Financial, migração legada) escreve
diretamente em `projects` sem passar por aqui quando há ambiguidade — ver
`app/migration/staging_import.py`.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk


class SyncRun(UUIDPk, TimestampMixin, Base):
    __tablename__ = "sync_runs"

    source_system: Mapped[str] = mapped_column(String(32), nullable=False)  # clickup|financial|legacy_json
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # dry_run | apply
    status: Mapped[str] = mapped_column(String(32), default="running")  # running|completed|failed
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    records_seen: Mapped[int] = mapped_column(Integer, default=0)
    records_created: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    records_conflicted: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    report_json: Mapped[str] = mapped_column(Text, default="{}")


class SyncConflict(UUIDPk, TimestampMixin, Base):
    __tablename__ = "sync_conflicts"

    sync_run_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("sync_runs.id"), nullable=False)
    source_system: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)  # duplicate|ambiguous_match|no_match|field_conflict
    candidate_project_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|resolved|rejected
    resolved_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    resolution_note: Mapped[str] = mapped_column(Text, default="")
