"""Endpoints de importação de notas iniciais. Toda a escrita passa por
`app/services/imports_notes.py` — nunca escreve em `Project`/dados
satélite fora do `apply`. Ver docs/DATA_IMPORTS.md.
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.imports import FieldImportBatch, FieldImportConflict, FieldImportRecord
from app.schemas.imports import (
    ApplyImportRequest,
    ApplyImportResult,
    FieldImportBatchRead,
    FieldImportConflictRead,
    FieldImportDocumentRead,
    FieldImportRecordRead,
    ResolveImportConflictRequest,
)
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, can_import_notes
from app.services.imports_notes import (
    DuplicateImportError,
    NotesImportError,
    apply_notes_import,
    preview_notes_import,
    resolve_conflict as resolve_conflict_service,
)

router = APIRouter(prefix="/api/imports", tags=["imports"])


def _require_import_notes(ctx: AuthContext) -> None:
    if not can_import_notes(ctx):
        raise HTTPException(status_code=403, detail="Sem permissão para importar notas iniciais.")


def _record_to_read(record: FieldImportRecord) -> FieldImportRecordRead:
    data = FieldImportRecordRead.model_validate(record)
    data.candidate_projects = [{"id": pid} for pid in json.loads(record.candidate_project_ids_json or "[]")]
    data.mapped_fields = json.loads(record.mapped_fields_json or "{}")
    data.conflicts = [FieldImportConflictRead.model_validate(c) for c in record.conflicts]
    return data


def _batch_to_read(batch: FieldImportBatch) -> FieldImportBatchRead:
    data = FieldImportBatchRead.model_validate(batch)
    data.records = [_record_to_read(r) for r in batch.records]
    return data


@router.post("/notes/preview", response_model=FieldImportBatchRead, status_code=201)
async def preview_notes_endpoint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> FieldImportBatchRead:
    _require_import_notes(ctx)
    content = await file.read()
    try:
        batch = preview_notes_import(
            db, filename=file.filename or "ficheiro", content=content, uploaded_by_person_id=ctx.person_id
        )
    except DuplicateImportError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except NotesImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _batch_to_read(batch)


@router.get("/{batch_id}", response_model=FieldImportBatchRead)
def get_batch_endpoint(
    batch_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> FieldImportBatchRead:
    _require_import_notes(ctx)
    batch = db.get(FieldImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Lote de importação não encontrado.")
    return _batch_to_read(batch)


@router.get("/{batch_id}/document", response_model=FieldImportDocumentRead)
def get_batch_document_endpoint(
    batch_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> FieldImportDocumentRead:
    """Devolve o documento original submetido (HTML/JSON), tal como foi
    carregado — nunca só o payload já extraído. Auditoria/rastreabilidade:
    quem reve uma importação consegue sempre confirmar contra a fonte."""
    _require_import_notes(ctx)
    batch = db.get(FieldImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Lote de importação não encontrado.")
    return FieldImportDocumentRead(filename=batch.source_filename, content=batch.raw_document_text)


@router.get("/{batch_id}/conflicts", response_model=list[FieldImportConflictRead])
def list_conflicts_endpoint(
    batch_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> list[FieldImportConflictRead]:
    _require_import_notes(ctx)
    batch = db.get(FieldImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Lote de importação não encontrado.")
    conflicts: list[FieldImportConflict] = []
    for record in batch.records:
        conflicts.extend(record.conflicts)
    return [FieldImportConflictRead.model_validate(c) for c in conflicts]


@router.post("/conflicts/{conflict_id}/resolve", response_model=FieldImportConflictRead)
def resolve_conflict_endpoint(
    conflict_id: uuid.UUID,
    body: ResolveImportConflictRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> FieldImportConflictRead:
    _require_import_notes(ctx)
    conflict = db.get(FieldImportConflict, conflict_id)
    if conflict is None:
        raise HTTPException(status_code=404, detail="Conflito não encontrado.")
    try:
        updated = resolve_conflict_service(
            db, conflict=conflict, resolution=body.resolution, resolved_by_person_id=ctx.person_id
        )
    except NotesImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return FieldImportConflictRead.model_validate(updated)


@router.post("/notes/apply", response_model=ApplyImportResult)
def apply_notes_endpoint(
    body: ApplyImportRequest, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> ApplyImportResult:
    _require_import_notes(ctx)
    if not body.confirm:
        raise HTTPException(status_code=400, detail="É necessário confirmar explicitamente ('confirm': true).")
    batch = db.get(FieldImportBatch, body.batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Lote de importação não encontrado.")
    record = batch.records[0] if batch.records else None
    try:
        project = apply_notes_import(
            db,
            batch=batch,
            target_project_id=body.target_project_id,
            applied_by_person_id=ctx.person_id,
        )
    except NotesImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ApplyImportResult(
        project_id=project.id,
        project_name=project.name,
        created_new_project=bool(record and record.is_new_project and body.target_project_id is None),
    )
