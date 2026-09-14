"""Endpoints para consultar e resolver a migração em staging: lotes de
importação, registos de projeto em staging, e a fila de reconciliação de
PM. Nunca expõe um endpoint de ingestão real aqui — `ingest_export` é uma
operação controlada, fora do âmbito de um botão de UI nesta fase (ver
docs/DECISIONS.md); os 295 projetos reais continuam por migrar.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.migration.people_reconciliation import resolve_person_reconciliation
from app.migration.staging import (
    promote_staging_record,
    resolve_candidate_project_ids,
    resolve_conflict,
    rollback_promotion,
)
from app.models.migration import ImportBatch, PersonReconciliationItem, StagingProjectRecord
from app.schemas.migration import (
    ImportBatchRead,
    PersonReconciliationItemRead,
    ResolveConflictRequest,
    ResolveReconciliationRequest,
    RollbackRequest,
    StagingProjectRecordRead,
)
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext

router = APIRouter(prefix="/api/migration", tags=["migration"])


def _require_view(ctx: AuthContext) -> None:
    if not ctx.has_permission("migration.view"):
        raise HTTPException(status_code=403, detail="Sem permissão para ver dados de migração.")


def _require_resolve(ctx: AuthContext) -> None:
    if not ctx.has_permission("migration.resolve"):
        raise HTTPException(status_code=403, detail="Sem permissão para resolver dados de migração.")


# --------------------------------------------------------------------------
# Lotes de importação e registos de staging
# --------------------------------------------------------------------------


@router.get("/import-batches", response_model=list[ImportBatchRead])
def list_import_batches(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> list[ImportBatchRead]:
    _require_view(ctx)
    batches = db.query(ImportBatch).order_by(ImportBatch.started_at.desc()).all()
    return [ImportBatchRead.model_validate(b) for b in batches]


@router.get("/import-batches/{batch_id}/records", response_model=list[StagingProjectRecordRead])
def list_staging_records(
    batch_id: uuid.UUID,
    status: str | None = Query(default=None, description="Filtra por estado (ex.: conflict)"),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[StagingProjectRecordRead]:
    _require_view(ctx)
    query = db.query(StagingProjectRecord).filter(StagingProjectRecord.import_batch_id == batch_id)
    if status:
        query = query.filter(StagingProjectRecord.status == status)
    records = query.order_by(StagingProjectRecord.created_at.asc()).all()
    return [StagingProjectRecordRead.model_validate(r) for r in records]


@router.get("/staging-records/{record_id}", response_model=StagingProjectRecordRead)
def get_staging_record(
    record_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> StagingProjectRecordRead:
    _require_view(ctx)
    record = db.get(StagingProjectRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Registo de staging não encontrado.")
    return StagingProjectRecordRead.model_validate(record)


@router.post("/staging-records/{record_id}/resolve-conflict", response_model=StagingProjectRecordRead)
def resolve_staging_conflict(
    record_id: uuid.UUID,
    body: ResolveConflictRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> StagingProjectRecordRead:
    _require_resolve(ctx)

    # D-030: ligar a um projeto fora dos candidatos detetados exige
    # migration.link_arbitrary_project + uma nota não vazia, verificado
    # aqui (mensagens de erro específicas) E outra vez em
    # app.migration.staging.resolve_conflict (defesa em profundidade,
    # nunca confia só nesta camada).
    allow_outside_candidates = False
    if body.action == "link_existing" and body.target_project_id is not None:
        record_for_check = db.get(StagingProjectRecord, record_id)
        if record_for_check is None:
            raise HTTPException(status_code=404, detail="Registo de staging não encontrado.")
        valid_candidate_ids = resolve_candidate_project_ids(db, record_for_check)
        if str(body.target_project_id) not in valid_candidate_ids:
            if not ctx.has_permission("migration.link_arbitrary_project"):
                raise HTTPException(
                    status_code=403,
                    detail="Ligar a um projeto fora dos candidatos detetados exige a permissão "
                    "'migration.link_arbitrary_project'.",
                )
            if not body.note or not body.note.strip():
                raise HTTPException(
                    status_code=400,
                    detail="Ligar a um projeto fora dos candidatos detetados exige uma nota não vazia.",
                )
            allow_outside_candidates = True

    try:
        record = resolve_conflict(
            db,
            staging_record_id=record_id,
            action=body.action,
            actor_person_id=ctx.person_id,
            target_project_id=body.target_project_id,
            note=body.note,
            allow_target_outside_candidates=allow_outside_candidates,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return StagingProjectRecordRead.model_validate(record)


@router.post("/staging-records/{record_id}/promote", response_model=StagingProjectRecordRead)
def promote_staging_record_endpoint(
    record_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> StagingProjectRecordRead:
    _require_resolve(ctx)
    try:
        promote_staging_record(db, staging_record_id=record_id, actor_person_id=ctx.person_id)
    except ValueError as exc:
        # Cobre explicitamente o caso "PM não resolvido" — nunca promove
        # silenciosamente, devolve 409 com o motivo (ver
        # app/migration/staging.py:promote_staging_record).
        raise HTTPException(status_code=409, detail=str(exc))
    record = db.get(StagingProjectRecord, record_id)
    return StagingProjectRecordRead.model_validate(record)


@router.post("/staging-records/{record_id}/rollback", response_model=StagingProjectRecordRead)
def rollback_staging_record(
    record_id: uuid.UUID,
    body: RollbackRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> StagingProjectRecordRead:
    _require_resolve(ctx)
    try:
        record = rollback_promotion(
            db, staging_record_id=record_id, actor_person_id=ctx.person_id, reason=body.reason
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return StagingProjectRecordRead.model_validate(record)


@router.post("/staging-records/{record_id}/retry-pm-resolution", response_model=StagingProjectRecordRead)
def retry_pm_resolution_endpoint(
    record_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> StagingProjectRecordRead:
    _require_resolve(ctx)
    from app.migration.staging import retry_pm_resolution

    try:
        record = retry_pm_resolution(db, staging_record_id=record_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return StagingProjectRecordRead.model_validate(record)


# --------------------------------------------------------------------------
# Fila de reconciliação de PM
# --------------------------------------------------------------------------


@router.get("/reconciliation-items", response_model=list[PersonReconciliationItemRead])
def list_reconciliation_items(
    status: str | None = Query(default="pending"),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[PersonReconciliationItemRead]:
    _require_view(ctx)
    query = db.query(PersonReconciliationItem)
    if status:
        query = query.filter(PersonReconciliationItem.status == status)
    items = query.order_by(PersonReconciliationItem.created_at.asc()).all()
    return [PersonReconciliationItemRead.model_validate(i) for i in items]


@router.post("/reconciliation-items/{item_id}/resolve", response_model=PersonReconciliationItemRead)
def resolve_reconciliation_item(
    item_id: uuid.UUID,
    body: ResolveReconciliationRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> PersonReconciliationItemRead:
    _require_resolve(ctx)
    try:
        item = resolve_person_reconciliation(
            db,
            item_id=item_id,
            action=body.action,
            actor_person_id=ctx.person_id,
            target_person_id=body.target_person_id,
            new_person_display_name=body.new_person_display_name,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return PersonReconciliationItemRead.model_validate(item)
