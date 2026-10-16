from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.time_bank import TimeBankImportBatch
from app.schemas.time_bank import (
    AdjustmentCreate,
    AdjustmentPage,
    AdjustmentRead,
    AdjustmentReverse,
    AppliedCounts,
    EntryCreate,
    EntryPage,
    EntryRead,
    EntryReverse,
    ImportRead,
    ImportResolve,
    TimeBankPersonRead,
    TimeBankSummary,
)
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext
from app.services.time_bank_ledger import (
    TimeBankConflict,
    TimeBankError,
    TimeBankForbidden,
    TimeBankNotFound,
    apply_import,
    create_adjustment,
    create_entry,
    import_read,
    list_adjustments,
    list_entries,
    list_people,
    preview_import,
    resolve_import,
    reverse_adjustment,
    reverse_entry,
    summary,
)
from app.services.time_bank_import import MAX_UPLOAD_BYTES, TimeBankImportError

router = APIRouter(prefix="/api/time-bank", tags=["time-bank"])


def _raise(exc: Exception) -> HTTPException:
    if isinstance(exc, TimeBankForbidden):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, TimeBankNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, TimeBankConflict):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


_EXPECTED_CONFLICT_MARKERS = (
    "uq_time_bank_entry_source_key",
    "uq_time_bank_adjustment_source_key",
    "uq_time_bank_entry_one_reversal",
    "uq_time_bank_adjustment_one_reversal",
    "uq_time_bank_import_hash_version",
    "time_bank_entries.source_key",
    "time_bank_adjustments.source_key",
    "time_bank_entries.reversal_of_id",
    "time_bank_adjustments.reversal_of_id",
)


def _is_expected_integrity_collision(exc: IntegrityError) -> bool:
    parts: list[str] = []
    current: BaseException | None = exc
    while current is not None:
        parts.append(str(current).lower())
        current = current.__cause__ or current.__context__
    detail = " ".join(parts)
    return any(marker in detail for marker in _EXPECTED_CONFLICT_MARKERS)


def _storage_http_exception(exc: SQLAlchemyError) -> HTTPException:
    if isinstance(exc, IntegrityError) and _is_expected_integrity_collision(exc):
        return HTTPException(status_code=409, detail="A operação entra em conflito com um lançamento existente.")
    return HTTPException(status_code=503, detail="Não foi possível concluir a operação de Banco de Horas.")


def _safe_rollback_before_commit(db: Session, committed: bool) -> None:
    if committed:
        return
    try:
        db.rollback()
    except SQLAlchemyError:
        # The original storage error is the useful outcome; never replace it
        # with raw rollback/driver details.
        pass


def _commit(db: Session) -> None:
    db.commit()


def _validate_range(from_date: dt.date | None, to_date: dt.date | None) -> None:
    if from_date is not None and to_date is not None and to_date < from_date:
        raise HTTPException(status_code=422, detail="to_date não pode ser anterior a from_date.")


@router.get("/people", response_model=list[TimeBankPersonRead])
def people_endpoint(
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[TimeBankPersonRead]:
    try:
        return [TimeBankPersonRead.model_validate(person) for person in list_people(db, ctx)]
    except TimeBankError as exc:
        raise _raise(exc)
    except SQLAlchemyError as exc:
        raise _storage_http_exception(exc) from exc


@router.get("/entries", response_model=EntryPage)
def entries_endpoint(
    person_id: uuid.UUID | None = None,
    from_date: dt.date | None = None,
    to_date: dt.date | None = None,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> EntryPage:
    _validate_range(from_date, to_date)
    try:
        items, total = list_entries(
            db, ctx, person_id=person_id, from_date=from_date, to_date=to_date, limit=limit, offset=offset
        )
    except TimeBankError as exc:
        raise _raise(exc)
    except SQLAlchemyError as exc:
        raise _storage_http_exception(exc) from exc
    return EntryPage(items=[EntryRead.model_validate(item) for item in items], total=total)


@router.post("/entries", response_model=EntryRead, status_code=201)
def create_entry_endpoint(
    body: EntryCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> EntryRead:
    committed = False
    try:
        entry = create_entry(db, ctx, body)
        response = EntryRead.model_validate(entry)
        _commit(db)
        committed = True
        return response
    except TimeBankError as exc:
        _safe_rollback_before_commit(db, committed)
        raise _raise(exc)
    except SQLAlchemyError as exc:
        _safe_rollback_before_commit(db, committed)
        raise _storage_http_exception(exc) from exc


@router.post("/entries/{entry_id}/reverse", response_model=EntryRead)
def reverse_entry_endpoint(
    entry_id: uuid.UUID,
    body: EntryReverse,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> EntryRead:
    committed = False
    try:
        entry = reverse_entry(db, ctx, entry_id, body.reason)
        response = EntryRead.model_validate(entry)
        _commit(db)
        committed = True
        return response
    except TimeBankError as exc:
        _safe_rollback_before_commit(db, committed)
        raise _raise(exc)
    except SQLAlchemyError as exc:
        _safe_rollback_before_commit(db, committed)
        raise _storage_http_exception(exc) from exc


@router.get("/adjustments", response_model=AdjustmentPage)
def adjustments_endpoint(
    person_id: uuid.UUID | None = None,
    from_date: dt.date | None = None,
    to_date: dt.date | None = None,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> AdjustmentPage:
    _validate_range(from_date, to_date)
    try:
        items, total = list_adjustments(
            db, ctx, person_id=person_id, from_date=from_date, to_date=to_date, limit=limit, offset=offset
        )
    except TimeBankError as exc:
        raise _raise(exc)
    except SQLAlchemyError as exc:
        raise _storage_http_exception(exc) from exc
    return AdjustmentPage(items=[AdjustmentRead.model_validate(item) for item in items], total=total)


@router.post("/adjustments", response_model=AdjustmentRead, status_code=201)
def create_adjustment_endpoint(
    body: AdjustmentCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> AdjustmentRead:
    committed = False
    try:
        adjustment = create_adjustment(db, ctx, body)
        response = AdjustmentRead.model_validate(adjustment)
        _commit(db)
        committed = True
        return response
    except TimeBankError as exc:
        _safe_rollback_before_commit(db, committed)
        raise _raise(exc)
    except SQLAlchemyError as exc:
        _safe_rollback_before_commit(db, committed)
        raise _storage_http_exception(exc) from exc


@router.post("/adjustments/{adjustment_id}/reverse", response_model=AdjustmentRead)
def reverse_adjustment_endpoint(
    adjustment_id: uuid.UUID,
    body: AdjustmentReverse,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> AdjustmentRead:
    committed = False
    try:
        adjustment = reverse_adjustment(db, ctx, adjustment_id, body.reason)
        response = AdjustmentRead.model_validate(adjustment)
        _commit(db)
        committed = True
        return response
    except TimeBankError as exc:
        _safe_rollback_before_commit(db, committed)
        raise _raise(exc)
    except SQLAlchemyError as exc:
        _safe_rollback_before_commit(db, committed)
        raise _storage_http_exception(exc) from exc


@router.get("/summary", response_model=TimeBankSummary)
def summary_endpoint(
    person_id: uuid.UUID | None = None,
    year: int = Query(default=2026, ge=1900, le=2200),
    month: int | None = Query(default=None, ge=1, le=12),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> TimeBankSummary:
    try:
        return TimeBankSummary.model_validate({"people": summary(db, ctx, person_id=person_id, year=year, month=month)})
    except TimeBankError as exc:
        raise _raise(exc)
    except SQLAlchemyError as exc:
        raise _storage_http_exception(exc) from exc


@router.post("/imports/preview", response_model=ImportRead)
async def import_preview_endpoint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ImportRead:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    committed = False
    try:
        batch = preview_import(db, ctx, content)
        response = ImportRead(**import_read(db, batch))
        _commit(db)
        committed = True
        return response
    except TimeBankError as exc:
        _safe_rollback_before_commit(db, committed)
        raise _raise(exc)
    except TimeBankImportError as exc:
        _safe_rollback_before_commit(db, committed)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        _safe_rollback_before_commit(db, committed)
        raise _storage_http_exception(exc) from exc


@router.get("/imports/{batch_id}", response_model=ImportRead)
def import_get_endpoint(
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ImportRead:
    try:
        if not ctx.has_permission("time_bank.manage_all"):
            raise TimeBankForbidden("Sem permissão para consultar lotes de importação.")
        batch = db.get(TimeBankImportBatch, batch_id)
        if batch is None:
            raise TimeBankNotFound("Lote de importação não encontrado.")
        return ImportRead(**import_read(db, batch))
    except TimeBankError as exc:
        raise _raise(exc)
    except SQLAlchemyError as exc:
        raise _storage_http_exception(exc) from exc


@router.post("/imports/{batch_id}/resolve", response_model=ImportRead)
def import_resolve_endpoint(
    batch_id: uuid.UUID,
    body: ImportResolve,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ImportRead:
    committed = False
    try:
        batch = resolve_import(db, ctx, batch_id, body.person_mapping)
        response = ImportRead(**import_read(db, batch))
        _commit(db)
        committed = True
        return response
    except TimeBankError as exc:
        _safe_rollback_before_commit(db, committed)
        raise _raise(exc)
    except SQLAlchemyError as exc:
        _safe_rollback_before_commit(db, committed)
        raise _storage_http_exception(exc) from exc


@router.post("/imports/{batch_id}/apply", response_model=ImportRead)
def import_apply_endpoint(
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ImportRead:
    committed = False
    try:
        batch = apply_import(db, ctx, batch_id)
        response = ImportRead(**import_read(db, batch))
        _commit(db)
        committed = True
        return response
    except TimeBankError as exc:
        _safe_rollback_before_commit(db, committed)
        raise _raise(exc)
    except SQLAlchemyError as exc:
        _safe_rollback_before_commit(db, committed)
        raise _storage_http_exception(exc) from exc
