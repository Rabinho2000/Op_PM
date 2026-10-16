"""Serviços do Banco de Horas: regras, ledger append-only e importação."""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.people import Person
from app.models.time_bank import (
    ADJUSTMENT_KINDS,
    TimeBankAdjustment,
    TimeBankAudit,
    TimeBankEntry,
    TimeBankImportBatch,
)
from app.schemas.time_bank import EntryCreate, AdjustmentCreate
from app.security.permissions import (
    AuthContext,
    can_manage_time_bank,
    can_view_time_bank,
    can_view_time_bank_person,
)
from app.services.time_bank import TimeBankValidationError, calculate_work_seconds
from app.services.time_bank_import import PARSER_VERSION, parse_time_bank_xlsx


class TimeBankError(ValueError):
    pass


class TimeBankForbidden(TimeBankError):
    pass


class TimeBankNotFound(TimeBankError):
    pass


class TimeBankConflict(TimeBankError):
    pass


class TimeBankImportConflict(TimeBankConflict):
    pass


_IMPORT_BATCH_HASH_COLLISION_MARKERS = (
    "uq_time_bank_import_hash_version",
    "time_bank_import_batches.sha256",
    "time_bank_import_batches.sha256, time_bank_import_batches.parser_version",
)
_IMPORT_OWNED_PENDING_KEY = "time_bank_import_owned_pending"


def _require_clean_import_session(db: Session) -> None:
    """Keep import services from flushing or undoing caller-owned state."""
    owned_pending = db.info.get(_IMPORT_OWNED_PENDING_KEY, set())
    unrelated_new = [item for item in db.new if id(item) not in owned_pending]
    if unrelated_new or db.dirty or db.deleted:
        raise TimeBankError("A sessão do importador tem de estar limpa antes da operação.")


def _is_import_batch_hash_collision(exc: IntegrityError) -> bool:
    parts: list[str] = []
    current: BaseException | None = exc
    while current is not None:
        parts.append(str(current).lower())
        current = current.__cause__ or current.__context__
    detail = " ".join(parts)
    return any(marker in detail for marker in _IMPORT_BATCH_HASH_COLLISION_MARKERS)


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _require_view(ctx: AuthContext) -> None:
    if not can_view_time_bank(ctx):
        raise TimeBankForbidden("Sem permissão para consultar o Banco de Horas.")


def _require_manage(ctx: AuthContext) -> None:
    if not can_manage_time_bank(ctx):
        raise TimeBankForbidden("Sem permissão para gerir o Banco de Horas.")


def _person_or_404(db: Session, person_id: uuid.UUID) -> Person:
    person = db.get(Person, person_id)
    if person is None:
        raise TimeBankNotFound("Pessoa não encontrada.")
    return person


def _require_person_scope(ctx: AuthContext, person_id: uuid.UUID) -> None:
    _require_view(ctx)
    if not can_view_time_bank_person(ctx, person_id):
        raise TimeBankForbidden("Sem permissão para consultar os registos desta pessoa.")


def _lock_person(db: Session, person_id: uuid.UUID) -> Person:
    """Lock the canonical person row before reading or writing ledger rows."""
    person = _person_or_404(db, person_id)
    if db.get_bind().dialect.name == "postgresql":
        row = db.execute(select(Person).where(Person.id == person_id).with_for_update()).scalar_one_or_none()
        if row is None:
            raise TimeBankNotFound("Pessoa não encontrada.")
        person = row
    else:
        result = db.execute(
            update(Person).where(Person.id == person_id).values(updated_at=Person.updated_at).execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise TimeBankNotFound("Pessoa não encontrada.")
        db.flush()
        person = db.query(Person).execution_options(populate_existing=True).filter(Person.id == person_id).one()
    return person


def _lock_entry(db: Session, entry_id: uuid.UUID) -> TimeBankEntry:
    if db.get_bind().dialect.name == "postgresql":
        entry = db.execute(
            select(TimeBankEntry).where(TimeBankEntry.id == entry_id).with_for_update()
        ).scalar_one_or_none()
    else:
        db.execute(
            update(TimeBankEntry)
            .where(TimeBankEntry.id == entry_id)
            .values(updated_at=TimeBankEntry.updated_at)
            .execution_options(synchronize_session=False)
        )
        db.flush()
        entry = db.query(TimeBankEntry).execution_options(populate_existing=True).filter(TimeBankEntry.id == entry_id).one_or_none()
    if entry is None:
        raise TimeBankNotFound("Lançamento não encontrado.")
    return entry


def _lock_adjustment(db: Session, adjustment_id: uuid.UUID) -> TimeBankAdjustment:
    if db.get_bind().dialect.name == "postgresql":
        adjustment = db.execute(
            select(TimeBankAdjustment).where(TimeBankAdjustment.id == adjustment_id).with_for_update()
        ).scalar_one_or_none()
    else:
        db.execute(
            update(TimeBankAdjustment)
            .where(TimeBankAdjustment.id == adjustment_id)
            .values(updated_at=TimeBankAdjustment.updated_at)
            .execution_options(synchronize_session=False)
        )
        db.flush()
        adjustment = db.query(TimeBankAdjustment).execution_options(populate_existing=True).filter(TimeBankAdjustment.id == adjustment_id).one_or_none()
    if adjustment is None:
        raise TimeBankNotFound("Ajuste não encontrado.")
    return adjustment


def _lock_batch(db: Session, batch_id: uuid.UUID) -> TimeBankImportBatch:
    if db.get_bind().dialect.name == "postgresql":
        batch = db.execute(
            select(TimeBankImportBatch).where(TimeBankImportBatch.id == batch_id).with_for_update()
        ).scalar_one_or_none()
    else:
        db.execute(
            update(TimeBankImportBatch)
            .where(TimeBankImportBatch.id == batch_id)
            .values(status=TimeBankImportBatch.status)
            .execution_options(synchronize_session=False)
        )
        db.flush()
        batch = db.query(TimeBankImportBatch).execution_options(populate_existing=True).filter(TimeBankImportBatch.id == batch_id).one_or_none()
    if batch is None:
        raise TimeBankNotFound("Lote de importação não encontrado.")
    return batch


def _audit(db: Session, ctx: AuthContext, *, action: str, entity_id: uuid.UUID, data: dict[str, Any]) -> TimeBankAudit:
    audit = TimeBankAudit(
        actor_user_id=ctx.user.id,
        action=action,
        entity_id=entity_id,
        data=data,
        occurred_at=_now_utc(),
    )
    db.add(audit)
    if action.startswith("import."):
        db.info.setdefault(_IMPORT_OWNED_PENDING_KEY, set()).add(id(audit))
    return audit


def list_people(db: Session, ctx: AuthContext) -> list[Person]:
    _require_view(ctx)
    if ctx.has_permission("time_bank.view_all"):
        return db.query(Person).order_by(Person.display_name.asc(), Person.id.asc()).all()
    else:
        person = db.get(Person, ctx.person_id)
        return [person] if person is not None else []
    raise TimeBankForbidden("Sem permissão para consultar o Banco de Horas.")


def _resolve_list_person_id(ctx: AuthContext, person_id: uuid.UUID | None) -> uuid.UUID | None:
    """Resolve omitted list scope without widening a reader's visibility."""
    if person_id is not None or ctx.has_permission("time_bank.view_all"):
        return person_id
    if ctx.has_permission("time_bank.view_own"):
        return ctx.person_id
    raise TimeBankForbidden("Indique uma pessoa ou use uma permissão global.")


def _apply_entry_filters(query: Any, *, person_id: uuid.UUID | None, from_date: dt.date | None, to_date: dt.date | None) -> Any:
    if person_id is not None:
        query = query.filter(TimeBankEntry.person_id == person_id)
    if from_date is not None:
        query = query.filter(TimeBankEntry.work_date >= from_date)
    if to_date is not None:
        query = query.filter(TimeBankEntry.work_date <= to_date)
    return query


def list_entries(
    db: Session,
    ctx: AuthContext,
    *,
    person_id: uuid.UUID | None,
    from_date: dt.date | None,
    to_date: dt.date | None,
    limit: int,
    offset: int,
) -> tuple[list[TimeBankEntry], int]:
    _require_view(ctx)
    selected = _resolve_list_person_id(ctx, person_id)
    if selected is not None:
        _require_person_scope(ctx, selected)
        _person_or_404(db, selected)
    query = _apply_entry_filters(db.query(TimeBankEntry), person_id=selected, from_date=from_date, to_date=to_date)
    total = query.count()
    items = query.order_by(TimeBankEntry.work_date.asc(), TimeBankEntry.occurred_at.asc(), TimeBankEntry.id.asc()).offset(offset).limit(limit).all()
    return items, total


def list_adjustments(
    db: Session,
    ctx: AuthContext,
    *,
    person_id: uuid.UUID | None,
    from_date: dt.date | None,
    to_date: dt.date | None,
    limit: int,
    offset: int,
) -> tuple[list[TimeBankAdjustment], int]:
    _require_view(ctx)
    selected = _resolve_list_person_id(ctx, person_id)
    if selected is not None:
        _require_person_scope(ctx, selected)
        _person_or_404(db, selected)
    query = db.query(TimeBankAdjustment)
    if selected is not None:
        query = query.filter(TimeBankAdjustment.person_id == selected)
    if from_date is not None:
        query = query.filter(TimeBankAdjustment.effective_date >= from_date)
    if to_date is not None:
        query = query.filter(TimeBankAdjustment.effective_date <= to_date)
    total = query.count()
    items = query.order_by(TimeBankAdjustment.effective_date.asc(), TimeBankAdjustment.occurred_at.asc(), TimeBankAdjustment.id.asc()).offset(offset).limit(limit).all()
    return items, total


def create_entry(db: Session, ctx: AuthContext, body: EntryCreate) -> TimeBankEntry:
    _require_manage(ctx)
    _lock_person(db, body.person_id)
    try:
        calculated = calculate_work_seconds(
            work_date=body.work_date,
            start_minute=body.start_minute,
            end_minute=body.end_minute,
            lunch_taken=body.lunch_taken,
            calculation_mode=body.calculation_mode,
            manual_balance_seconds=body.manual_balance_seconds,
            reason=body.reason,
        )
    except TimeBankValidationError as exc:
        raise TimeBankError(str(exc)) from exc
    if body.calculation_mode == "manual":
        balance = body.manual_balance_seconds
        calculated_seconds = None
    else:
        balance = calculated
        calculated_seconds = calculated
    if balance is None:
        raise TimeBankError("Não foi possível calcular o lançamento.")
    entry = TimeBankEntry(
        person_id=body.person_id,
        work_date=body.work_date,
        start_minute=body.start_minute,
        end_minute=body.end_minute,
        lunch_taken=body.lunch_taken,
        balance_seconds=balance,
        calculated_seconds=calculated_seconds,
        calculation_mode=body.calculation_mode,
        reason=body.reason.strip() if body.reason else None,
        needs_review=False,
        review_flags={},
        provenance={"source": "api"},
        created_by_user_id=ctx.user.id,
        occurred_at=_now_utc(),
    )
    db.add(entry)
    db.flush()
    _audit(db, ctx, action="entry.create", entity_id=entry.id, data={"person_id": str(body.person_id), "balance_seconds": balance})
    return entry


def reverse_entry(db: Session, ctx: AuthContext, entry_id: uuid.UUID, reason: str) -> TimeBankEntry:
    _require_manage(ctx)
    clean_reason = reason.strip()
    if not clean_reason:
        raise TimeBankError("O motivo da anulação é obrigatório.")
    target = db.get(TimeBankEntry, entry_id)
    if target is None:
        raise TimeBankNotFound("Lançamento não encontrado.")
    _lock_person(db, target.person_id)
    target = _lock_entry(db, entry_id)
    if target.reversal_of_id is not None:
        raise TimeBankConflict("Uma compensação não pode ser anulada novamente.")
    existing = db.query(TimeBankEntry).filter(TimeBankEntry.reversal_of_id == target.id).first()
    if existing is not None:
        raise TimeBankConflict("Este lançamento já tem uma compensação.")
    compensation = TimeBankEntry(
        person_id=target.person_id,
        work_date=target.work_date,
        start_minute=target.start_minute,
        end_minute=target.end_minute,
        lunch_taken=target.lunch_taken,
        balance_seconds=-target.balance_seconds,
        calculated_seconds=-target.calculated_seconds if target.calculated_seconds is not None else None,
        calculation_mode="manual",
        reason=clean_reason,
        needs_review=target.needs_review,
        review_flags={"reversal_of_id": str(target.id)},
        provenance={"source": "reversal", "reversal_of_id": str(target.id)},
        created_by_user_id=ctx.user.id,
        occurred_at=_now_utc(),
        reversal_of_id=target.id,
    )
    db.add(compensation)
    db.flush()
    _audit(db, ctx, action="entry.reverse", entity_id=compensation.id, data={"reversal_of_id": str(target.id), "balance_seconds": compensation.balance_seconds})
    return compensation


def create_adjustment(db: Session, ctx: AuthContext, body: AdjustmentCreate) -> TimeBankAdjustment:
    _require_manage(ctx)
    _lock_person(db, body.person_id)
    if body.kind not in ADJUSTMENT_KINDS - {"opening"}:
        raise TimeBankError("Tipo de ajuste inválido.")
    if body.kind == "consumption" and body.delta_seconds >= 0:
        raise TimeBankError("Um consumo tem de ser negativo.")
    clean_reason = body.reason.strip()
    if not clean_reason:
        raise TimeBankError("O motivo do ajuste é obrigatório.")
    adjustment = TimeBankAdjustment(
        person_id=body.person_id,
        effective_date=body.effective_date,
        delta_seconds=body.delta_seconds,
        kind=body.kind,
        reason=clean_reason,
        provenance={"source": "api"},
        created_by_user_id=ctx.user.id,
        occurred_at=_now_utc(),
    )
    db.add(adjustment)
    db.flush()
    _audit(db, ctx, action="adjustment.create", entity_id=adjustment.id, data={"person_id": str(body.person_id), "delta_seconds": body.delta_seconds, "kind": body.kind})
    return adjustment


def reverse_adjustment(db: Session, ctx: AuthContext, adjustment_id: uuid.UUID, reason: str) -> TimeBankAdjustment:
    _require_manage(ctx)
    clean_reason = reason.strip()
    if not clean_reason:
        raise TimeBankError("O motivo da anulação é obrigatório.")
    target = db.get(TimeBankAdjustment, adjustment_id)
    if target is None:
        raise TimeBankNotFound("Ajuste não encontrado.")
    _lock_person(db, target.person_id)
    target = _lock_adjustment(db, adjustment_id)
    if target.reversal_of_id is not None:
        raise TimeBankConflict("Uma compensação não pode ser anulada novamente.")
    if db.query(TimeBankAdjustment).filter(TimeBankAdjustment.reversal_of_id == target.id).first() is not None:
        raise TimeBankConflict("Este ajuste já tem uma compensação.")
    compensation = TimeBankAdjustment(
        person_id=target.person_id,
        effective_date=target.effective_date,
        delta_seconds=-target.delta_seconds,
        kind="correction",
        reason=clean_reason,
        provenance={"source": "reversal", "reversal_of_id": str(target.id)},
        created_by_user_id=ctx.user.id,
        occurred_at=_now_utc(),
        reversal_of_id=target.id,
    )
    db.add(compensation)
    db.flush()
    _audit(db, ctx, action="adjustment.reverse", entity_id=compensation.id, data={"reversal_of_id": str(target.id), "delta_seconds": compensation.delta_seconds})
    return compensation


def _period(year: int, month: int | None) -> tuple[dt.date, dt.date]:
    if year < 1900 or year > 2200:
        raise TimeBankError("Ano inválido.")
    if month is None:
        return dt.date(year, 1, 1), dt.date(year, 12, 31)
    if month < 1 or month > 12:
        raise TimeBankError("Mês inválido.")
    start = dt.date(year, month, 1)
    end = dt.date(year + (month == 12), 1 if month == 12 else month + 1, 1) - dt.timedelta(days=1)
    return start, end


def _summary_for_person(db: Session, person: Person, *, year: int, month: int | None) -> dict[str, Any]:
    start, end = _period(year, month)
    entries = (
        db.query(TimeBankEntry)
        .filter(TimeBankEntry.person_id == person.id, TimeBankEntry.work_date <= end)
        .order_by(TimeBankEntry.work_date.asc(), TimeBankEntry.id.asc())
        .all()
    )
    adjustments = (
        db.query(TimeBankAdjustment)
        .filter(TimeBankAdjustment.person_id == person.id, TimeBankAdjustment.effective_date <= end)
        .order_by(TimeBankAdjustment.effective_date.asc(), TimeBankAdjustment.id.asc())
        .all()
    )
    all_rows: list[tuple[dt.date, int, bool, uuid.UUID, uuid.UUID | None]] = [
        (row.work_date, row.balance_seconds, row.needs_review, row.id, row.reversal_of_id) for row in entries
    ] + [
        (row.effective_date, row.delta_seconds, False, row.id, row.reversal_of_id) for row in adjustments
    ]
    balance = sum(delta for date, delta, _review, _id, _rev in all_rows)
    period_rows = [row for row in all_rows if start <= row[0] <= end]
    period_seconds = sum(row[1] for row in period_rows)
    opening = balance - period_seconds

    reversed_ids = {row[4] for row in all_rows if row[4] is not None}
    gross_rows = [row for row in period_rows if row[3] not in reversed_ids and row[4] is None]
    credited = sum(max(row[1], 0) for row in gross_rows)
    debited = sum(max(-row[1], 0) for row in gross_rows)
    review_count = sum(1 for row in period_rows if row[2])

    warnings: list[dict[str, str]] = []
    normal_entries = [
        row for row in entries
        if start <= row.work_date <= end and row.id not in reversed_ids and row.reversal_of_id is None
    ]
    daily: defaultdict[dt.date, int] = defaultdict(int)
    weekly: defaultdict[tuple[int, int], int] = defaultdict(int)
    for row in normal_entries:
        if row.balance_seconds > 0:
            daily[row.work_date] += row.balance_seconds
            iso = row.work_date.isocalendar()
            weekly[(iso.year, iso.week)] += row.balance_seconds
    if any(value > 2 * 3600 for value in daily.values()):
        warnings.append({"code": "daily_threshold", "message": "Há dias com mais de 2 horas positivas de Banco de Horas."})
    if any(value > 4 * 3600 for value in weekly.values()):
        warnings.append({"code": "weekly_threshold", "message": "Há semanas ISO com mais de 4 horas positivas de Banco de Horas."})
    year_start = dt.date(year, 1, 1)
    annual_positive = sum(
        row.balance_seconds for row in entries
        if year_start <= row.work_date <= end and row.balance_seconds > 0 and row.id not in reversed_ids and row.reversal_of_id is None
    )
    if annual_positive > 175 * 3600:
        warnings.append({"code": "annual_threshold", "message": "As horas positivas acumuladas no ano excedem 175 horas."})
    if balance > 8 * 3600:
        warnings.append({"code": "month_balance_threshold", "message": "O saldo acumulado no fim do período excede 8 horas."})
    if review_count:
        warnings.append({"code": "needs_review", "message": "Existem lançamentos importados que requerem revisão."})
    return {
        "person_id": person.id,
        "display_name": person.display_name,
        "opening_seconds": opening,
        "credited_seconds": credited,
        "debited_seconds": debited,
        "balance_seconds": balance,
        "period_seconds": period_seconds,
        "needs_review_count": review_count,
        "warnings": warnings,
    }


def summary(db: Session, ctx: AuthContext, *, person_id: uuid.UUID | None, year: int, month: int | None) -> list[dict[str, Any]]:
    _require_view(ctx)
    if person_id is not None:
        _require_person_scope(ctx, person_id)
        persons = [_person_or_404(db, person_id)]
    elif ctx.has_permission("time_bank.view_all"):
        persons = db.query(Person).order_by(Person.display_name.asc(), Person.id.asc()).all()
    elif ctx.has_permission("time_bank.view_own"):
        persons = [_person_or_404(db, ctx.person_id)]
    else:
        raise TimeBankForbidden("Sem permissão para consultar o Banco de Horas.")
    _period(year, month)
    return [_summary_for_person(db, person, year=year, month=month) for person in persons]


def _normalise_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def import_candidates(db: Session, source_label: str) -> list[Person]:
    normalised = _normalise_name(source_label)
    all_people = db.query(Person).order_by(Person.display_name.asc(), Person.id.asc()).all()
    exact = [person for person in all_people if _normalise_name(person.display_name) == normalised]
    if exact:
        return exact
    first = normalised.split(" ", 1)[0]
    return [person for person in all_people if _normalise_name(person.display_name).split(" ", 1)[0] == first]


def preview_import(db: Session, ctx: AuthContext, content: bytes) -> TimeBankImportBatch:
    _require_clean_import_session(db)
    _require_manage(ctx)
    parsed = parse_time_bank_xlsx(content)
    file_hash = parsed["source_hash"]
    existing = db.query(TimeBankImportBatch).filter(
        TimeBankImportBatch.sha256 == file_hash,
        TimeBankImportBatch.parser_version == PARSER_VERSION,
    ).one_or_none()
    if existing is not None:
        return existing
    batch = TimeBankImportBatch(
        sha256=file_hash,
        parser_version=PARSER_VERSION,
        status="pending",
        source_year=parsed["source_year"],
        parsed_payload=parsed,
        resolutions={},
        created_by_user_id=ctx.user.id,
        created_at=_now_utc(),
    )
    try:
        # Begin the savepoint before adding the candidate.  SQLAlchemy flushes
        # pending state when a nested transaction starts, so adding first would
        # place the unique insert outside the collision boundary.
        with db.begin_nested():
            db.add(batch)
            db.flush()
    except IntegrityError as exc:
        if not _is_import_batch_hash_collision(exc):
            raise
        winner = db.query(TimeBankImportBatch).filter(
            TimeBankImportBatch.sha256 == file_hash,
            TimeBankImportBatch.parser_version == PARSER_VERSION,
        ).one_or_none()
        if winner is None:
            raise TimeBankConflict("Não foi possível obter o lote de importação concorrente.") from exc
        return winner
    _audit(db, ctx, action="import.preview", entity_id=batch.id, data={"sha256": file_hash, "entries": parsed["counts"]["entries"]})
    return batch


def _batch_payload(batch: TimeBankImportBatch) -> dict[str, Any]:
    payload = batch.parsed_payload
    if not isinstance(payload, dict):
        raise TimeBankConflict("Payload de importação inválido.")
    return payload


def _resolution_map(batch: TimeBankImportBatch) -> dict[str, uuid.UUID]:
    raw = batch.resolutions if isinstance(batch.resolutions, dict) else {}
    result: dict[str, uuid.UUID] = {}
    for key, value in raw.items():
        try:
            result[str(key)] = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        except (TypeError, ValueError) as exc:
            raise TimeBankConflict("Mapeamento de pessoa inválido no lote.") from exc
    return result


def import_read(db: Session, batch: TimeBankImportBatch) -> dict[str, Any]:
    payload = _batch_payload(batch)
    resolutions = _resolution_map(batch)
    people = []
    issues = list(payload.get("issues") or [])
    labels = list(payload.get("people") or [])
    for label in labels:
        mapped = resolutions.get(label)
        candidates = import_candidates(db, label)
        if mapped is None:
            issues.append({"code": "person_unresolved", "message": "Pessoa de origem sem mapeamento explícito.", "blocking": True, "sheet": None, "row": None})
        elif db.get(Person, mapped) is None:
            issues.append({"code": "person_reference_invalid", "message": "Mapeamento aponta para uma pessoa inexistente.", "blocking": True, "sheet": None, "row": None})
        people.append({
            "source_label": label,
            "person_id": mapped,
            "candidates": [{"id": person.id, "display_name": person.display_name} for person in candidates],
        })
    result = {
        "id": batch.id,
        "status": batch.status,
        "sha256": batch.sha256,
        "source_year": batch.source_year,
        "counts": payload.get("counts", {"entries": 0, "openings": 0, "needs_review": 0}),
        "people": people,
        "issues": issues,
        "applied_counts": payload.get("counts", {}).get("entries", 0) if batch.status == "applied" else None,
    }
    if batch.status == "applied":
        result["applied_counts"] = {"entries": payload.get("counts", {}).get("entries", 0), "openings": payload.get("counts", {}).get("openings", 0)}
    else:
        result["applied_counts"] = None
    return result


def resolve_import(db: Session, ctx: AuthContext, batch_id: uuid.UUID, mapping: dict[str, uuid.UUID]) -> TimeBankImportBatch:
    _require_clean_import_session(db)
    _require_manage(ctx)
    batch = _lock_batch(db, batch_id)
    if batch.status != "pending":
        raise TimeBankConflict("Um lote aplicado já não pode ser remapeado.")
    payload = _batch_payload(batch)
    labels = set(payload.get("people") or [])
    if set(mapping) - labels:
        raise TimeBankConflict("O mapeamento contém um rótulo que não pertence ao lote.")
    for label, person_id in mapping.items():
        _person_or_404(db, person_id)
        if not isinstance(label, str) or not label.strip():
            raise TimeBankConflict("O rótulo de origem não pode ficar vazio.")
    batch.resolutions = {**_resolution_map(batch), **{label: str(person_id) for label, person_id in mapping.items()}}
    db.flush()
    _audit(db, ctx, action="import.resolve", entity_id=batch.id, data={"mapped_count": len(mapping)})
    return batch


def _existing_entry_by_source(db: Session, source_key: str) -> TimeBankEntry | None:
    return db.query(TimeBankEntry).filter(TimeBankEntry.source_key == source_key).one_or_none()


def _existing_adjustment_by_source(db: Session, source_key: str) -> TimeBankAdjustment | None:
    return db.query(TimeBankAdjustment).filter(TimeBankAdjustment.source_key == source_key).one_or_none()


def apply_import(db: Session, ctx: AuthContext, batch_id: uuid.UUID) -> TimeBankImportBatch:
    _require_clean_import_session(db)
    _require_manage(ctx)
    batch = _lock_batch(db, batch_id)
    if batch.status == "applied":
        return batch
    payload = _batch_payload(batch)
    blocking = [issue for issue in payload.get("issues", []) if issue.get("blocking")]
    resolutions = _resolution_map(batch)
    labels = list(payload.get("people") or [])
    if blocking:
        raise TimeBankImportConflict("O lote contém anomalias bloqueantes que exigem correção da fonte.")
    if any(label not in resolutions for label in labels):
        raise TimeBankImportConflict("Todas as pessoas de origem têm de ser resolvidas antes da aplicação.")
    for label, person_id in resolutions.items():
        _person_or_404(db, person_id)

    applied_entries = 0
    for row in payload.get("entries", []):
        source_key = row.get("source_key")
        balance = row.get("balance_seconds")
        if not source_key or isinstance(balance, bool) or not isinstance(balance, int):
            raise TimeBankImportConflict("Um lançamento importado não tem valor inteiro recuperável.")
        person_id = resolutions[row["source_label"]]
        existing = _existing_entry_by_source(db, source_key)
        if existing is not None:
            if existing.person_id != person_id or existing.balance_seconds != balance:
                raise TimeBankImportConflict("A chave de origem já existe com valores divergentes.")
            continue
        person = _lock_person(db, person_id)
        del person
        entry = TimeBankEntry(
            person_id=person_id,
            work_date=dt.date.fromisoformat(row["work_date"]),
            start_minute=row.get("start_minute"),
            end_minute=row.get("end_minute"),
            lunch_taken=row.get("lunch_taken"),
            balance_seconds=balance,
            calculated_seconds=row.get("calculated_seconds"),
            calculation_mode="imported",
            reason=row.get("reason"),
            needs_review=bool(row.get("needs_review")),
            review_flags=row.get("review_flags") or {},
            provenance=row.get("provenance") or {},
            source_key=source_key,
            created_by_user_id=batch.created_by_user_id,
            occurred_at=_now_utc(),
        )
        db.add(entry)
        db.flush()
        _audit(db, ctx, action="import.entry", entity_id=entry.id, data={"batch_id": str(batch.id), "source_key": source_key})
        applied_entries += 1

    applied_openings = 0
    for row in payload.get("openings", []):
        source_key = row.get("source_key")
        delta = row.get("delta_seconds")
        if not source_key or isinstance(delta, bool) or not isinstance(delta, int):
            raise TimeBankImportConflict("Um saldo transitado importado não tem valor inteiro recuperável.")
        person_id = resolutions[row["source_label"]]
        existing = _existing_adjustment_by_source(db, source_key)
        if existing is not None:
            if existing.person_id != person_id or existing.delta_seconds != delta:
                raise TimeBankImportConflict("A chave de origem já existe com valores divergentes.")
            continue
        _lock_person(db, person_id)
        adjustment = TimeBankAdjustment(
            person_id=person_id,
            effective_date=dt.date.fromisoformat(row["effective_date"]),
            delta_seconds=delta,
            kind="opening",
            reason=row.get("reason") or "Saldo transitado importado.",
            provenance=row.get("provenance") or {},
            source_key=source_key,
            created_by_user_id=batch.created_by_user_id,
            occurred_at=_now_utc(),
        )
        db.add(adjustment)
        db.flush()
        _audit(db, ctx, action="import.opening", entity_id=adjustment.id, data={"batch_id": str(batch.id), "source_key": source_key})
        applied_openings += 1

    batch.status = "applied"
    batch.applied_at = _now_utc()
    batch.resolutions = {label: str(person_id) for label, person_id in resolutions.items()}
    db.flush()
    _audit(db, ctx, action="import.apply", entity_id=batch.id, data={"entries": applied_entries, "openings": applied_openings})
    return batch
