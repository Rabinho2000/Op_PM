"""Schemas Pydantic para os endpoints de consulta/resolução de migração —
lotes de importação, registos de staging, e fila de reconciliação de PM.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ImportBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_system: str
    status: str
    started_at: dt.datetime
    finished_at: dt.datetime | None
    started_by_person_id: uuid.UUID | None
    checksum: str
    records_seen: int
    records_ready: int
    records_conflicted: int


class StagingProjectRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    import_batch_id: uuid.UUID
    source_system: str
    external_id: str
    status: str
    conflict_reason: str | None
    candidate_project_ids_json: str
    pm_name_raw: str | None
    candidate_person_ids_json: str
    pm_explicitly_unassigned: bool
    resolved_action: str | None
    resolved_target_project_id: uuid.UUID | None
    resolution_note: str
    promoted_project_id: uuid.UUID | None
    promoted_at: dt.datetime | None
    reverted_at: dt.datetime | None
    reverted_reason: str
    created_at: dt.datetime
    updated_at: dt.datetime
    # Só no detalhe (não na listagem) — pedido explícito, evita respostas
    # grandes na listagem por omissão.
    mapped_fields_json: str | None = None
    raw_record_json: str | None = None


class ResolveConflictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["create_new", "link_existing", "skip", "proceed_without_pm"]
    target_project_id: uuid.UUID | None = None
    note: str = ""


class RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)


class PersonReconciliationItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    raw_name: str
    normalized_name: str
    reason: str
    candidate_person_ids_json: str
    status: str
    resolved_person_id: uuid.UUID | None
    resolved_by_person_id: uuid.UUID | None
    resolved_at: dt.datetime | None
    resolution_note: str
    created_at: dt.datetime


class ResolveReconciliationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["link_existing", "create_new", "ignore"]
    target_person_id: uuid.UUID | None = None
    new_person_display_name: str | None = None
    note: str = ""
