from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict


class FieldImportConflictRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_entity: str
    field_name: str
    old_value: str | None
    new_value: str | None
    resolution: str
    resolved_by_person_id: uuid.UUID | None
    resolved_at: dt.datetime | None


class FieldImportRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_project_id: uuid.UUID | None
    is_new_project: bool
    match_strategy: str
    status: str
    promoted_project_id: uuid.UUID | None

    candidate_projects: list[dict] = []
    mapped_fields: dict = {}
    conflicts: list[FieldImportConflictRead] = []


class FieldImportDocumentRead(BaseModel):
    filename: str
    content: str


class FieldImportBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_type: str
    source_filename: str
    form_version: str | None
    status: str
    started_by_person_id: uuid.UUID | None
    started_at: dt.datetime
    applied_by_person_id: uuid.UUID | None
    applied_at: dt.datetime | None

    records: list[FieldImportRecordRead] = []


class ResolveImportConflictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: str  # use_new | keep_old


class ApplyImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: uuid.UUID
    target_project_id: uuid.UUID | None = None
    confirm: bool = False


class ApplyImportResult(BaseModel):
    project_id: uuid.UUID
    project_name: str
    created_new_project: bool
