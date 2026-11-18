"""Transactional service for project-scoped cable dimensioning studies."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import string
import uuid
from collections.abc import Mapping
from typing import Any, NoReturn

from sqlalchemy.orm import Session

from app.models.cable_designs import (
    CABLE_DESIGN_STATUS_APPROVED,
    CABLE_DESIGN_STATUS_DRAFT,
    CABLE_REVISION_STATUS_APPROVED,
    CABLE_REVISION_STATUS_DRAFT,
    CableDesign,
    CableDesignHistory,
    CableDesignRevision,
)
from app.models.project import Project
from app.schemas.cable_designs import (
    CABLE_JSON_MAX_BYTES,
    _json_object,
)
from app.security.permissions import AuthContext, can_edit_project, can_view_project


class CableDesignPermissionError(PermissionError):
    """The account lacks the capability for the requested operation."""


class CableDesignNotFoundError(LookupError):
    """The study or its project is absent or outside the actor's scope."""


class CableDesignValidationError(ValueError):
    """A cable-design payload or state transition violates the contract."""


class CableDesignConflictError(ValueError):
    """The optimistic version or approval precondition is not satisfied."""


class CableDesignLockedError(ValueError):
    """The current approved revision is immutable."""


class CableDesignPayloadTooLargeError(ValueError):
    """A JSON payload exceeds the per-field size limit."""


class CableDesignStorageError(RuntimeError):
    """A database/audit failure while persisting study state."""


_DEFAULT_INPUT: dict[str, Any] = {"format": 1}
_DEFAULT_RESULT: dict[str, Any] = {}

# The browser engine remains the source of calculations for now.  These limits
# only bound the shape accepted as approvable content; they are not a claim
# that the backend independently reproduced the electrical calculation.
_MAX_APPROVABLE_CIRCUITS = 10_000
_MAX_APPROVABLE_TEXT = 256
_MAX_APPROVABLE_NOTE = 2_048
_MAX_APPROVABLE_KW_AC = 1_000_000.0
_APPROVABLE_RESULT_FAILURE = "O resultado guardado não está pronto para aprovação."


def require_cable_design_view_permission(ctx: AuthContext) -> None:
    if not ctx.has_permission("cable_design.view"):
        raise CableDesignPermissionError("Sem permissão para consultar estudos de cabos.")


def require_cable_design_edit_permission(ctx: AuthContext) -> None:
    if not ctx.has_permission("cable_design.edit"):
        raise CableDesignPermissionError("Sem permissão para editar estudos de cabos.")


def _project_in_scope(
    db: Session, ctx: AuthContext, project_id: uuid.UUID, *, edit: bool
) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise CableDesignNotFoundError("Projeto não encontrado.")
    allowed = can_edit_project(ctx, project) if edit else can_view_project(ctx, project)
    if not allowed:
        # Keep missing and out-of-scope projects indistinguishable.
        raise CableDesignNotFoundError("Projeto não encontrado.")
    return project


def _get_design_scoped(
    db: Session, ctx: AuthContext, design_id: uuid.UUID, *, edit: bool
) -> CableDesign:
    row = (
        db.query(CableDesign)
        .filter(CableDesign.id == design_id, CableDesign.is_active.is_(True))
        .one_or_none()
    )
    if row is None:
        raise CableDesignNotFoundError("Estudo de cabos não encontrado.")
    _project_in_scope(db, ctx, row.project_id, edit=edit)
    return row


def _lock_design(db: Session, design_id: uuid.UUID) -> CableDesign:
    """Lock and explicitly refresh the design before deriving old values.

    PostgreSQL applies ``FOR UPDATE``. SQLite's application engine starts write
    transactions with ``BEGIN IMMEDIATE``; ``populate_existing`` is still
    required so a long-lived test/session identity map cannot supply a stale
    version or revision to the audit entry.
    """
    row = (
        db.query(CableDesign)
        .filter(CableDesign.id == design_id, CableDesign.is_active.is_(True))
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        raise CableDesignNotFoundError("Estudo de cabos não encontrado.")
    return row


def _current_revision(db: Session, design: CableDesign) -> CableDesignRevision:
    revision = (
        db.query(CableDesignRevision)
        .filter(
            CableDesignRevision.design_id == design.id,
            CableDesignRevision.rev == design.current_revision,
        )
        .populate_existing()
        .one_or_none()
    )
    if revision is None:
        raise CableDesignStorageError("A revisão corrente do estudo não está disponível.")
    return revision


def _canonical_json(value: object, *, field_name: str, require_format: bool = False) -> str:
    try:
        validated = _json_object(value, field_name=field_name, require_format=require_format)
        encoded = json.dumps(
            validated,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except ValueError as exc:
        if "excede o limite" in str(exc):
            raise CableDesignPayloadTooLargeError(str(exc)) from exc
        raise CableDesignValidationError(str(exc)) from exc
    if len(encoded) > CABLE_JSON_MAX_BYTES:
        raise CableDesignPayloadTooLargeError(f"{field_name} excede o limite de 2 MiB.")
    return encoded.decode("utf-8")


def _content_values(
    input_value: object, result_value: object
) -> tuple[str, str, str, int]:
    input_text = _canonical_json(input_value, field_name="input", require_format=True)
    result_text = _canonical_json(result_value, field_name="result")
    digest = hashlib.sha256((input_text + result_text).encode("utf-8")).hexdigest()
    try:
        result_object = json.loads(result_text)
    except json.JSONDecodeError as exc:  # pragma: no cover - canonical JSON above
        raise CableDesignValidationError("result não é JSON válido.") from exc
    circuits = result_object.get("circuits")
    unresolved = (
        sum(1 for circuit in circuits if isinstance(circuit, dict) and circuit.get("review") is True)
        if isinstance(circuits, list)
        else 0
    )
    return input_text, result_text, digest, unresolved


def _approval_failure() -> NoReturn:
    raise CableDesignConflictError(_APPROVABLE_RESULT_FAILURE)


def _approval_text(value: object, *, max_length: int, allow_empty: bool = False) -> str:
    if type(value) is not str:
        _approval_failure()
    assert isinstance(value, str)  # narrowed for type checkers; JSON is exact
    if any(ord(char) < 0x20 for char in value):
        _approval_failure()
    normalised = value.strip()
    if not allow_empty and not normalised:
        _approval_failure()
    if len(normalised) > max_length:
        _approval_failure()
    return normalised


def _approval_nonnegative_int(value: object) -> int:
    if type(value) is not int or value < 0:
        _approval_failure()
    assert type(value) is int
    return value


def _approval_input_inverter_count(input_object: dict[str, Any]) -> int | None:
    """Return native-state inverter count, or None for the D-100 legacy shape.

    D-100 predates the native editor and used a non-empty ``input.circuits``
    marker.  Keep that shape readable/approvable when the result is otherwise
    canonical, while rejecting the empty ``{"format": 1}`` placeholder.
    """
    state = input_object.get("state")
    if state is not None:
        if type(state) is not dict or not state:
            _approval_failure()
        invs = state.get("invs")
        percs = state.get("percs")
        if type(invs) is not list or type(percs) is not list:
            _approval_failure()
        if not invs and not percs:
            _approval_failure()
        if not all(isinstance(item, Mapping) for item in [*invs, *percs]):
            _approval_failure()
        return len(invs)

    legacy_circuits = input_object.get("circuits")
    if (
        type(legacy_circuits) is list
        and legacy_circuits
        and all(isinstance(item, Mapping) for item in legacy_circuits)
    ):
        return None
    _approval_failure()


def _validate_approvable_result(
    input_object: dict[str, Any],
    result_object: dict[str, Any],
    *,
    revision_engine_version: str,
) -> int:
    """Validate the browser persisted-result envelope before approval.

    This is deliberately a confidence boundary, not a calculation verifier:
    the browser engine still supplies the numerical result until an
    authoritative server-side runtime is introduced.
    """
    if type(result_object.get("format")) is not int or result_object.get("format") != 1:
        _approval_failure()
    result_engine_version = _approval_text(
        result_object.get("engine_version"), max_length=_MAX_APPROVABLE_TEXT
    )
    if result_engine_version != revision_engine_version:
        _approval_failure()

    circuits = result_object.get("circuits")
    if type(circuits) is not list or not circuits:
        _approval_failure()
    if len(circuits) > _MAX_APPROVABLE_CIRCUITS:
        _approval_failure()

    review_count = 0
    for circuit in circuits:
        if type(circuit) is not dict:
            _approval_failure()
        _approval_text(circuit.get("code"), max_length=_MAX_APPROVABLE_TEXT)
        _approval_text(circuit.get("name"), max_length=_MAX_APPROVABLE_TEXT)
        if type(circuit.get("review")) is not bool:
            _approval_failure()
        if circuit["review"] is True:
            review_count += 1
        if "note" in circuit:
            _approval_text(
                circuit["note"], max_length=_MAX_APPROVABLE_NOTE, allow_empty=True
            )

    totals = result_object.get("totals")
    if type(totals) is not dict:
        _approval_failure()
    circuits_total = _approval_nonnegative_int(totals.get("circuits"))
    review_total = _approval_nonnegative_int(totals.get("review"))
    inverters_total = _approval_nonnegative_int(totals.get("inverters"))
    if circuits_total != len(circuits) or review_total != review_count:
        _approval_failure()
    if inverters_total > circuits_total or inverters_total > _MAX_APPROVABLE_CIRCUITS:
        _approval_failure()
    if "kw_ac" in totals:
        kw_ac = totals["kw_ac"]
        if isinstance(kw_ac, bool):
            _approval_failure()
        elif type(kw_ac) is int:
            if kw_ac < 0 or kw_ac > _MAX_APPROVABLE_KW_AC:
                _approval_failure()
        elif type(kw_ac) is float:
            if (
                not math.isfinite(kw_ac)
                or kw_ac < 0
                or kw_ac > _MAX_APPROVABLE_KW_AC
            ):
                _approval_failure()
        else:
            _approval_failure()

    state_inverters = _approval_input_inverter_count(input_object)
    if state_inverters is not None and inverters_total != state_inverters:
        _approval_failure()
    return review_count


def _validate_persisted_revision_for_approval(
    revision: CableDesignRevision,
) -> int:
    """Re-read and validate persisted content; never trust the counter alone."""
    try:
        input_object = _decode_object(revision.input_json, field_name="input_json")
        result_object = _decode_object(revision.result_json, field_name="result_json")
        review_count = _validate_approvable_result(
            input_object,
            result_object,
            revision_engine_version=revision.engine_version,
        )
        input_text = _canonical_json(input_object, field_name="input", require_format=True)
        result_text = _canonical_json(result_object, field_name="result")
    except CableDesignConflictError:
        raise
    except (CableDesignPayloadTooLargeError, CableDesignStorageError, CableDesignValidationError) as exc:
        raise CableDesignConflictError(_APPROVABLE_RESULT_FAILURE) from exc

    digest = hashlib.sha256((input_text + result_text).encode("utf-8")).hexdigest()
    if digest != revision.content_sha256:
        raise CableDesignConflictError(_APPROVABLE_RESULT_FAILURE)
    if type(revision.unresolved_circuits) is not int or revision.unresolved_circuits != review_count:
        raise CableDesignConflictError(_APPROVABLE_RESULT_FAILURE)
    return review_count


def _decode_object(value: str, *, field_name: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise CableDesignStorageError(f"O conteúdo persistido de {field_name} é inválido.") from exc
    if not isinstance(decoded, dict):
        raise CableDesignStorageError(f"O conteúdo persistido de {field_name} é inválido.")
    return decoded


def _short_state(design: CableDesign, revision: CableDesignRevision) -> str:
    """Small audit state: never include input/result JSON."""
    return json.dumps(
        {
            "title": design.title,
            "status": design.status,
            "current_revision": design.current_revision,
            "version": design.version,
            "revision_status": revision.status,
            "engine_version": revision.engine_version,
            "content_sha256": revision.content_sha256,
            "unresolved_circuits": revision.unresolved_circuits,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _append_history(
    db: Session,
    *,
    design: CableDesign,
    actor_person_id: uuid.UUID,
    action: str,
    rev: str,
    old_value: str | None,
    new_value: str | None,
) -> CableDesignHistory:
    if action not in {"created", "saved", "submitted", "approved", "new_revision", "deactivated"}:
        raise CableDesignValidationError("Ação de histórico inválida.")
    entry = CableDesignHistory(
        design_id=design.id,
        actor_person_id=actor_person_id,
        action=action,
        rev=rev,
        old_value=old_value,
        new_value=new_value,
        created_at=dt.datetime.now(dt.timezone.utc),
    )
    db.add(entry)
    return entry


def _commit(db: Session, *, failure_message: str) -> None:
    try:
        db.flush()
        db.commit()
    except Exception as exc:
        db.rollback()
        raise CableDesignStorageError(failure_message) from exc


def _normalise_title(value: object) -> str:
    if not isinstance(value, str):
        raise CableDesignValidationError("title tem de ser texto.")
    title = value.strip()
    if not title or len(title) > 256:
        raise CableDesignValidationError("title tem de ter entre 1 e 256 caracteres.")
    if any(ord(char) < 0x20 for char in title):
        raise CableDesignValidationError("title contém caracteres de controlo.")
    return title


def _normalise_engine_version(value: object) -> str:
    if not isinstance(value, str):
        raise CableDesignValidationError("engine_version tem de ser texto.")
    engine_version = value.strip()
    if not engine_version or len(engine_version) > 64:
        raise CableDesignValidationError("engine_version tem de ter entre 1 e 64 caracteres.")
    if any(ord(char) < 0x20 for char in engine_version):
        raise CableDesignValidationError("engine_version contém caracteres de controlo.")
    return engine_version


def _check_expected_version(design: CableDesign, expected_version: int) -> None:
    if type(expected_version) is not int or expected_version < 1:
        raise CableDesignValidationError("expected_version tem de ser um inteiro positivo.")
    if design.version != expected_version:
        raise CableDesignConflictError("A versão do estudo está desatualizada.")


def _design_read_payload(db: Session, design: CableDesign) -> dict[str, object]:
    revision = _current_revision(db, design)
    return {
        "id": design.id,
        "project_id": design.project_id,
        "title": design.title,
        "status": design.status,
        "current_revision": design.current_revision,
        "version": design.version,
        "updated_at": design.updated_at,
        "unresolved_circuits": revision.unresolved_circuits,
        "is_active": design.is_active,
        "created_by_person_id": design.created_by_person_id,
        "created_at": design.created_at,
        "revision": _revision_read_payload(revision),
    }


def _design_list_payload(db: Session, design: CableDesign) -> dict[str, object]:
    revision = _current_revision(db, design)
    return {
        "id": design.id,
        "project_id": design.project_id,
        "title": design.title,
        "status": design.status,
        "current_revision": design.current_revision,
        "version": design.version,
        "updated_at": design.updated_at,
        "unresolved_circuits": revision.unresolved_circuits,
    }


def _revision_read_payload(revision: CableDesignRevision) -> dict[str, object]:
    return {
        "id": revision.id,
        "design_id": revision.design_id,
        "rev": revision.rev,
        "input_json": _decode_object(revision.input_json, field_name="input_json"),
        "result_json": _decode_object(revision.result_json, field_name="result_json"),
        "engine_version": revision.engine_version,
        "content_sha256": revision.content_sha256,
        "unresolved_circuits": revision.unresolved_circuits,
        "status": revision.status,
        "approved_by_person_id": revision.approved_by_person_id,
        "approved_at": revision.approved_at,
        "created_by_person_id": revision.created_by_person_id,
        "created_at": revision.created_at,
        "updated_at": revision.updated_at,
    }


def _history_value(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise CableDesignStorageError("O histórico persistido é inválido.") from exc
    if not isinstance(decoded, dict):
        raise CableDesignStorageError("O histórico persistido é inválido.")
    return decoded


def _history_read_payload(entry: CableDesignHistory) -> dict[str, object]:
    return {
        "id": entry.id,
        "design_id": entry.design_id,
        "action": entry.action,
        "actor_person_id": entry.actor_person_id,
        "rev": entry.rev,
        "old_value": _history_value(entry.old_value),
        "new_value": _history_value(entry.new_value),
        "created_at": entry.created_at,
    }


def list_cable_designs(
    db: Session, ctx: AuthContext, project_id: uuid.UUID
) -> list[dict[str, object]]:
    require_cable_design_view_permission(ctx)
    _project_in_scope(db, ctx, project_id, edit=False)
    rows = (
        db.query(CableDesign)
        .filter(CableDesign.project_id == project_id, CableDesign.is_active.is_(True))
        .order_by(CableDesign.title.asc(), CableDesign.id.asc())
        .all()
    )
    return [_design_list_payload(db, row) for row in rows]


def create_cable_design(
    db: Session,
    ctx: AuthContext,
    project_id: uuid.UUID,
    *,
    title: object,
    input_json: object | None,
    engine_version: object,
) -> dict[str, object]:
    require_cable_design_edit_permission(ctx)
    _project_in_scope(db, ctx, project_id, edit=True)
    normalised_title = _normalise_title(title)
    normalised_engine_version = _normalise_engine_version(engine_version)
    input_value = _DEFAULT_INPUT if input_json is None else input_json
    input_text, result_text, digest, unresolved = _content_values(input_value, _DEFAULT_RESULT)

    design = CableDesign(
        project_id=project_id,
        title=normalised_title,
        status=CABLE_DESIGN_STATUS_DRAFT,
        current_revision="A",
        version=1,
        is_active=True,
        created_by_person_id=ctx.person_id,
    )
    revision = CableDesignRevision(
        design=design,
        rev="A",
        input_json=input_text,
        result_json=result_text,
        engine_version=normalised_engine_version,
        content_sha256=digest,
        unresolved_circuits=unresolved,
        status=CABLE_REVISION_STATUS_DRAFT,
        created_by_person_id=ctx.person_id,
    )
    db.add_all([design, revision])
    try:
        db.flush()
        _append_history(
            db,
            design=design,
            actor_person_id=ctx.person_id,
            action="created",
            rev="A",
            old_value=None,
            new_value=_short_state(design, revision),
        )
        db.flush()
        db.commit()
        db.refresh(design)
        db.refresh(revision)
        return _design_read_payload(db, design)
    except CableDesignStorageError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise CableDesignStorageError("Não foi possível criar o estudo de cabos.") from exc


def get_cable_design(
    db: Session, ctx: AuthContext, design_id: uuid.UUID
) -> dict[str, object]:
    require_cable_design_view_permission(ctx)
    design = _get_design_scoped(db, ctx, design_id, edit=False)
    return _design_read_payload(db, design)


def update_current_cable_design_revision(
    db: Session,
    ctx: AuthContext,
    design_id: uuid.UUID,
    *,
    expected_version: int,
    title: object | None,
    input_value: object,
    result_value: object,
    engine_version: object,
) -> dict[str, object]:
    require_cable_design_edit_permission(ctx)
    _get_design_scoped(db, ctx, design_id, edit=True)
    design = _lock_design(db, design_id)
    _check_expected_version(design, expected_version)
    revision = _current_revision(db, design)
    if design.status == CABLE_DESIGN_STATUS_APPROVED or revision.status == CABLE_REVISION_STATUS_APPROVED:
        raise CableDesignLockedError("A revisão aprovada é imutável.")

    old_value = _short_state(design, revision)
    normalised_title = design.title if title is None else _normalise_title(title)
    normalised_engine_version = _normalise_engine_version(engine_version)
    input_text, result_text, digest, unresolved = _content_values(input_value, result_value)
    design.title = normalised_title
    design.version += 1
    revision.input_json = input_text
    revision.result_json = result_text
    revision.engine_version = normalised_engine_version
    revision.content_sha256 = digest
    revision.unresolved_circuits = unresolved
    try:
        _append_history(
            db,
            design=design,
            actor_person_id=ctx.person_id,
            action="saved",
            rev=revision.rev,
            old_value=old_value,
            new_value=_short_state(design, revision),
        )
        _commit(db, failure_message="Não foi possível guardar o estudo de cabos.")
        db.refresh(design)
        db.refresh(revision)
        return _design_read_payload(db, design)
    except (CableDesignValidationError, CableDesignConflictError, CableDesignLockedError):
        raise
    except CableDesignStorageError:
        raise
    except Exception as exc:
        db.rollback()
        raise CableDesignStorageError("Não foi possível guardar o estudo de cabos.") from exc


def approve_cable_design(
    db: Session, ctx: AuthContext, design_id: uuid.UUID, *, expected_version: int
) -> dict[str, object]:
    require_cable_design_edit_permission(ctx)
    _get_design_scoped(db, ctx, design_id, edit=True)
    design = _lock_design(db, design_id)
    _check_expected_version(design, expected_version)
    revision = _current_revision(db, design)
    if design.status == CABLE_DESIGN_STATUS_APPROVED or revision.status == CABLE_REVISION_STATUS_APPROVED:
        raise CableDesignLockedError("A revisão aprovada é imutável.")
    review_count = _validate_persisted_revision_for_approval(revision)
    if review_count > 0:
        raise CableDesignConflictError("O estudo tem circuitos a rever.")

    old_value = _short_state(design, revision)
    revision.status = CABLE_REVISION_STATUS_APPROVED
    revision.approved_by_person_id = ctx.person_id
    revision.approved_at = dt.datetime.now(dt.timezone.utc)
    design.status = CABLE_DESIGN_STATUS_APPROVED
    design.version += 1
    try:
        _append_history(
            db,
            design=design,
            actor_person_id=ctx.person_id,
            action="approved",
            rev=revision.rev,
            old_value=old_value,
            new_value=_short_state(design, revision),
        )
        _commit(db, failure_message="Não foi possível aprovar o estudo de cabos.")
        db.refresh(design)
        db.refresh(revision)
        return _design_read_payload(db, design)
    except CableDesignStorageError:
        raise
    except Exception as exc:
        db.rollback()
        raise CableDesignStorageError("Não foi possível aprovar o estudo de cabos.") from exc


def _next_revision(rev: str) -> str:
    if not rev or any(char not in string.ascii_uppercase for char in rev):
        raise CableDesignValidationError("A revisão corrente tem um identificador inválido.")
    chars = list(rev)
    position = len(chars) - 1
    while position >= 0 and chars[position] == "Z":
        chars[position] = "A"
        position -= 1
    if position < 0:
        chars.insert(0, "A")
    else:
        chars[position] = chr(ord(chars[position]) + 1)
    next_rev = "".join(chars)
    if len(next_rev) > 8:
        raise CableDesignValidationError("O limite de revisões do estudo foi atingido.")
    return next_rev


def new_cable_design_revision(
    db: Session, ctx: AuthContext, design_id: uuid.UUID, *, expected_version: int
) -> dict[str, object]:
    require_cable_design_edit_permission(ctx)
    _get_design_scoped(db, ctx, design_id, edit=True)
    design = _lock_design(db, design_id)
    _check_expected_version(design, expected_version)
    current = _current_revision(db, design)
    if design.status != CABLE_DESIGN_STATUS_APPROVED or current.status != CABLE_REVISION_STATUS_APPROVED:
        raise CableDesignConflictError("Só é possível criar uma revisão a partir de um estudo aprovado.")

    next_rev = _next_revision(current.rev)
    old_value = _short_state(design, current)
    revision = CableDesignRevision(
        design_id=design.id,
        rev=next_rev,
        input_json=current.input_json,
        result_json=current.result_json,
        engine_version=current.engine_version,
        content_sha256=current.content_sha256,
        unresolved_circuits=current.unresolved_circuits,
        status=CABLE_REVISION_STATUS_DRAFT,
        approved_by_person_id=None,
        approved_at=None,
        created_by_person_id=ctx.person_id,
    )
    design.current_revision = next_rev
    design.status = CABLE_DESIGN_STATUS_DRAFT
    design.version += 1
    db.add(revision)
    try:
        db.flush()
        _append_history(
            db,
            design=design,
            actor_person_id=ctx.person_id,
            action="new_revision",
            rev=next_rev,
            old_value=old_value,
            new_value=_short_state(design, revision),
        )
        _commit(db, failure_message="Não foi possível criar a nova revisão do estudo.")
        db.refresh(design)
        db.refresh(revision)
        return _design_read_payload(db, design)
    except CableDesignStorageError:
        raise
    except Exception as exc:
        db.rollback()
        raise CableDesignStorageError("Não foi possível criar a nova revisão do estudo.") from exc


def list_cable_design_revisions(
    db: Session, ctx: AuthContext, design_id: uuid.UUID
) -> list[dict[str, object]]:
    require_cable_design_view_permission(ctx)
    design = _get_design_scoped(db, ctx, design_id, edit=False)
    rows = (
        db.query(CableDesignRevision)
        .filter(CableDesignRevision.design_id == design.id)
        .order_by(CableDesignRevision.rev.asc(), CableDesignRevision.id.asc())
        .all()
    )
    return [_revision_read_payload(row) for row in rows]


def list_cable_design_history(
    db: Session, ctx: AuthContext, design_id: uuid.UUID
) -> list[dict[str, object]]:
    require_cable_design_view_permission(ctx)
    design = _get_design_scoped(db, ctx, design_id, edit=False)
    rows = (
        db.query(CableDesignHistory)
        .filter(CableDesignHistory.design_id == design.id)
        .order_by(CableDesignHistory.created_at.asc(), CableDesignHistory.id.asc())
        .all()
    )
    return [_history_read_payload(row) for row in rows]


def deactivate_cable_design(
    db: Session, ctx: AuthContext, design_id: uuid.UUID, *, expected_version: int
) -> None:
    require_cable_design_edit_permission(ctx)
    _get_design_scoped(db, ctx, design_id, edit=True)
    design = _lock_design(db, design_id)
    _check_expected_version(design, expected_version)
    revision = _current_revision(db, design)
    old_value = _short_state(design, revision)
    design.is_active = False
    design.version += 1
    try:
        _append_history(
            db,
            design=design,
            actor_person_id=ctx.person_id,
            action="deactivated",
            rev=revision.rev,
            old_value=old_value,
            new_value=_short_state(design, revision),
        )
        _commit(db, failure_message="Não foi possível desativar o estudo de cabos.")
    except CableDesignStorageError:
        raise
    except Exception as exc:
        db.rollback()
        raise CableDesignStorageError("Não foi possível desativar o estudo de cabos.") from exc
