"""Endpoints de importação de notas iniciais. Toda a escrita passa por
`app/services/imports_notes.py` — nunca escreve em `Project`/dados
satélite fora do `apply`. Ver docs/DATA_IMPORTS.md.
"""
from __future__ import annotations

import json
import uuid
from typing import cast

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
    MAX_UPLOAD_BYTES,
    SENSITIVE_DATA_OMITTED_PLACEHOLDER,
    DuplicateImportError,
    ImportPendingStateError,
    NotesImportError,
    _SensitiveValueBudgetExceeded,
    SENSITIVE_FIELD_PLACEHOLDER,
    SENSITIVE_VALUE_PLACEHOLDER,
    _SensitiveValueMatcher,
    _collect_sensitive_values,
    _ensure_clean_import_session,
    _is_sensitive_label,
    _redact_text,
    _sanitize_payload,
    _sanitize_value,
    apply_notes_import,
    preview_notes_import,
    sanitize_document_for_read,
)
from app.services.imports_notes import resolve_conflict as resolve_conflict_service

router = APIRouter(prefix="/api/imports", tags=["imports"])


def _require_import_notes(ctx: AuthContext) -> None:
    if not can_import_notes(ctx):
        raise HTTPException(status_code=403, detail="Sem permissão para importar notas iniciais.")


def _staging_omission(default: object) -> object:
    if isinstance(default, dict):
        return {SENSITIVE_DATA_OMITTED_PLACEHOLDER: SENSITIVE_DATA_OMITTED_PLACEHOLDER}
    if isinstance(default, list):
        return [SENSITIVE_DATA_OMITTED_PLACEHOLDER]
    return SENSITIVE_DATA_OMITTED_PLACEHOLDER


def _parse_staging_json(raw_value: object, *, default: object) -> object:
    try:
        parsed = json.loads(raw_value or json.dumps(default)) if isinstance(raw_value, str) else default
    except (json.JSONDecodeError, ValueError, OverflowError, RecursionError, TypeError) as exc:
        raise NotesImportError("Dados de staging inválidos — o lote não pode ser devolvido.") from exc
    if not isinstance(parsed, type(default)):
        raise NotesImportError("Dados de staging inválidos — o lote não pode ser devolvido.")
    return parsed


def _staging_json_to_read(raw_value: object, *, default: object) -> object:
    parsed = _parse_staging_json(raw_value, default=default)
    try:
        sanitized = _sanitize_payload(parsed)
    except _SensitiveValueBudgetExceeded:
        return _staging_omission(default)
    if not isinstance(sanitized, type(default)):
        raise NotesImportError("Dados de staging inválidos — o lote não pode ser devolvido.")
    return sanitized


def _omitted_conflict_to_read(conflict: FieldImportConflict) -> FieldImportConflictRead:
    return FieldImportConflictRead(
        id=conflict.id,
        target_entity=SENSITIVE_DATA_OMITTED_PLACEHOLDER,
        field_name=SENSITIVE_DATA_OMITTED_PLACEHOLDER,
        old_value=SENSITIVE_DATA_OMITTED_PLACEHOLDER if conflict.old_value is not None else None,
        new_value=SENSITIVE_DATA_OMITTED_PLACEHOLDER if conflict.new_value is not None else None,
        resolution=conflict.resolution,
        resolved_by_person_id=conflict.resolved_by_person_id,
        resolved_at=conflict.resolved_at,
    )


def _conflict_to_read(
    conflict: FieldImportConflict, *, matcher: _SensitiveValueMatcher | None = None, omit: bool = False
) -> FieldImportConflictRead:
    if omit:
        return _omitted_conflict_to_read(conflict)
    if matcher is None:
        try:
            matcher = _SensitiveValueMatcher(
                _collect_sensitive_values(
                    {conflict.field_name: {"old_value": conflict.old_value, "new_value": conflict.new_value}}
                )
            )
        except _SensitiveValueBudgetExceeded:
            return _omitted_conflict_to_read(conflict)
    sensitive = _is_sensitive_label(conflict.field_name)
    field_name = SENSITIVE_FIELD_PLACEHOLDER if sensitive else _redact_text(conflict.field_name, matcher)

    def safe_value(value: str | None) -> str | None:
        if value is None:
            return None
        return SENSITIVE_VALUE_PLACEHOLDER if sensitive else _redact_text(value, matcher)

    return FieldImportConflictRead(
        id=conflict.id,
        target_entity=_redact_text(conflict.target_entity, matcher),
        field_name=field_name,
        old_value=safe_value(conflict.old_value),
        new_value=safe_value(conflict.new_value),
        resolution=conflict.resolution,
        resolved_by_person_id=conflict.resolved_by_person_id,
        resolved_at=conflict.resolved_at,
    )


def _record_to_read(
    record: FieldImportRecord,
    *,
    inherited_payload: object | None = None,
    force_omit: bool = False,
) -> FieldImportRecordRead:
    data = FieldImportRecordRead.model_validate(record)
    candidate_ids = cast(list, _staging_json_to_read(record.candidate_project_ids_json, default=[]))
    mapped_raw = _parse_staging_json(record.mapped_fields_json, default={})
    context: dict[str, object] = {
        "mapped": mapped_raw,
        "conflicts": [
            {"field_name": c.field_name, "old_value": c.old_value, "new_value": c.new_value}
            for c in record.conflicts
        ],
    }
    if inherited_payload is not None:
        context["payload"] = inherited_payload
    matcher: _SensitiveValueMatcher | None = None
    if not force_omit:
        try:
            matcher = _SensitiveValueMatcher(_collect_sensitive_values(context))
            mapped_fields = _sanitize_value(mapped_raw, matcher)
        except _SensitiveValueBudgetExceeded:
            force_omit = True
    if force_omit:
        mapped_fields = _staging_omission({})
    data.candidate_projects = [{"id": pid} for pid in candidate_ids]
    data.mapped_fields = cast(dict, mapped_fields)
    data.conflicts = [
        _conflict_to_read(c, matcher=matcher, omit=force_omit) for c in record.conflicts
    ]
    return data


def _batch_to_read(batch: FieldImportBatch) -> FieldImportBatchRead:
    # Validate/sanitize legacy raw payloads even though the public batch schema
    # exposes only the mapped view. A budget failure is represented by an
    # omission marker and is propagated to records/conflicts below.
    raw_payload = _parse_staging_json(batch.raw_payload_json, default={})
    raw_payload_omitted = False
    try:
        _sanitize_payload(raw_payload)
    except _SensitiveValueBudgetExceeded:
        raw_payload_omitted = True
    data = FieldImportBatchRead.model_validate(batch)
    data.source_filename = _redact_text(batch.source_filename)
    data.records = [
        _record_to_read(
            r,
            inherited_payload=None if raw_payload_omitted else raw_payload,
            force_omit=raw_payload_omitted,
        )
        for r in batch.records
    ]
    return data


@router.post("/notes/preview", response_model=FieldImportBatchRead, status_code=201)
async def preview_notes_endpoint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> FieldImportBatchRead:
    _require_import_notes(ctx)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Ficheiro demasiado grande (máximo {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).",
        )
    try:
        batch = preview_notes_import(
            db, filename=file.filename or "ficheiro", content=content, uploaded_by_person_id=ctx.person_id
        )
    except DuplicateImportError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except NotesImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        response = _batch_to_read(batch)
        db.commit()
        return response
    except NotesImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{batch_id}", response_model=FieldImportBatchRead)
def get_batch_endpoint(
    batch_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> FieldImportBatchRead:
    _require_import_notes(ctx)
    batch = db.query(FieldImportBatch).populate_existing().filter(FieldImportBatch.id == batch_id).one_or_none()
    if batch is None:
        raise HTTPException(status_code=404, detail="Lote de importação não encontrado.")
    db.expire(batch, ["records"])
    for record in batch.records:
        db.expire(record, ["conflicts"])
    try:
        return _batch_to_read(batch)
    except NotesImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{batch_id}/document", response_model=FieldImportDocumentRead)
def get_batch_document_endpoint(
    batch_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> FieldImportDocumentRead:
    """Devolve a representação JSON determinística do payload extraído.

    O upload HTML nunca é devolvido: a resposta contém apenas texto
    estruturado produzido pelo parser e sanitizado antes do staging.
    """
    _require_import_notes(ctx)
    batch = db.query(FieldImportBatch).populate_existing().filter(FieldImportBatch.id == batch_id).one_or_none()
    if batch is None:
        raise HTTPException(status_code=404, detail="Lote de importação não encontrado.")
    return FieldImportDocumentRead(
        filename=_redact_text(batch.source_filename),
        content=sanitize_document_for_read(
            filename=batch.source_filename,
            raw_document_text=batch.raw_document_text,
        ),
    )


@router.get("/{batch_id}/conflicts", response_model=list[FieldImportConflictRead])
def list_conflicts_endpoint(
    batch_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> list[FieldImportConflictRead]:
    _require_import_notes(ctx)
    batch = db.query(FieldImportBatch).populate_existing().filter(FieldImportBatch.id == batch_id).one_or_none()
    if batch is None:
        raise HTTPException(status_code=404, detail="Lote de importação não encontrado.")
    db.expire(batch, ["records"])
    for record in batch.records:
        db.expire(record, ["conflicts"])
    try:
        safe_batch = _batch_to_read(batch)
    except NotesImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return [conflict for record in safe_batch.records for conflict in record.conflicts]


@router.post("/conflicts/{conflict_id}/resolve", response_model=FieldImportConflictRead)
def resolve_conflict_endpoint(
    conflict_id: uuid.UUID,
    body: ResolveImportConflictRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> FieldImportConflictRead:
    _require_import_notes(ctx)
    try:
        _ensure_clean_import_session(db)
    except NotesImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    conflict = (
        db.query(FieldImportConflict)
        .populate_existing()
        .filter(FieldImportConflict.id == conflict_id)
        .one_or_none()
    )
    if conflict is None:
        raise HTTPException(status_code=404, detail="Conflito não encontrado.")
    try:
        updated = resolve_conflict_service(
            db, conflict=conflict, resolution=body.resolution, resolved_by_person_id=ctx.person_id
        )
    except NotesImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    response = _conflict_to_read(updated)
    db.commit()
    return response


@router.post("/notes/apply", response_model=ApplyImportResult)
def apply_notes_endpoint(
    body: ApplyImportRequest, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> ApplyImportResult:
    _require_import_notes(ctx)
    try:
        _ensure_clean_import_session(db)
    except NotesImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not body.confirm:
        raise HTTPException(status_code=400, detail="É necessário confirmar explicitamente ('confirm': true).")
    batch = db.get(FieldImportBatch, body.batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Lote de importação não encontrado.")
    try:
        project = apply_notes_import(
            db,
            batch=batch,
            target_project_id=body.target_project_id,
            applied_by_person_id=ctx.person_id,
        )
        db.commit()
        current_record = (
            db.query(FieldImportRecord)
            .populate_existing()
            .filter(FieldImportRecord.batch_id == body.batch_id)
            .one_or_none()
        )
    except ImportPendingStateError as exc:
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc))
    except NotesImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ApplyImportResult(
        project_id=project.id,
        project_name=project.name,
        created_new_project=bool(current_record and current_record.is_new_project and body.target_project_id is None),
    )
