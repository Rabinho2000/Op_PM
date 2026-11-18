"""Business rules for the authenticated user's request inbox."""
from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.models.identity import User
from app.models.people import Person
from app.models.user_requests import (
    REQUEST_STATUS_OPEN,
    REQUEST_STATUS_RESOLVED,
    UserRequest,
    UserRequestMessage,
)
from app.schemas.user_requests import RequestCreate, RequestMessageCreate
from app.security.permissions import AuthContext

MAX_OPEN_REQUESTS_PER_AUTHOR = 20
MAX_MESSAGE_BODY_LENGTH = 2000
MAX_MESSAGE_PREVIEW_LENGTH = 200


class UserRequestError(ValueError):
    pass


class UserRequestForbidden(UserRequestError):
    pass


class UserRequestNotFound(UserRequestError):
    pass


class UserRequestConflict(UserRequestError):
    pass


# Short aliases make the service errors convenient to import from route modules.
RequestError = UserRequestError
RequestForbidden = UserRequestForbidden
RequestNotFound = UserRequestNotFound
RequestConflict = UserRequestConflict


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _is_manager(ctx: AuthContext) -> bool:
    return ctx.has_permission("requests.manage")


def _require_create(ctx: AuthContext) -> None:
    if not ctx.has_permission("requests.create"):
        raise UserRequestForbidden("Sem permissão para criar pedidos.")


def _clean_body(value: object) -> str:
    if not isinstance(value, str):
        raise UserRequestError("O corpo tem de ser texto.")
    body = value.strip()
    if not body:
        raise UserRequestError("O corpo não pode estar vazio.")
    if len(body) > MAX_MESSAGE_BODY_LENGTH:
        raise UserRequestError("O corpo não pode exceder 2000 caracteres.")
    return body


def _request_or_404(db: Session, request_id: uuid.UUID) -> UserRequest:
    if not isinstance(request_id, uuid.UUID):
        try:
            request_id = uuid.UUID(str(request_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise UserRequestNotFound("Pedido não encontrado.") from exc
    request = db.get(UserRequest, request_id)
    if request is None:
        raise UserRequestNotFound("Pedido não encontrado.")
    return request


def _can_access(request: UserRequest, ctx: AuthContext) -> bool:
    return request.created_by_user_id == ctx.user.id or _is_manager(ctx)


def _require_access(request: UserRequest, ctx: AuthContext) -> None:
    if not _can_access(request, ctx):
        raise UserRequestNotFound("Pedido não encontrado.")


def _display_names(db: Session, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not user_ids:
        return {}
    rows = (
        db.query(User.id, Person.display_name)
        .outerjoin(Person, Person.id == User.person_id)
        .filter(User.id.in_(user_ids))
        .all()
    )
    return {user_id: display_name or "Utilizador" for user_id, display_name in rows}


def _messages_by_request(
    db: Session, request_ids: set[uuid.UUID]
) -> dict[uuid.UUID, list[UserRequestMessage]]:
    if not request_ids:
        return {}
    messages = (
        db.query(UserRequestMessage)
        .filter(UserRequestMessage.request_id.in_(request_ids))
        .order_by(
            UserRequestMessage.created_at.asc(),
            UserRequestMessage.id.asc(),
        )
        .all()
    )
    by_request: dict[uuid.UUID, list[UserRequestMessage]] = defaultdict(list)
    for message in messages:
        by_request[message.request_id].append(message)
    return by_request


def _preview(body: str) -> str:
    if len(body) <= MAX_MESSAGE_PREVIEW_LENGTH:
        return body
    return body[: MAX_MESSAGE_PREVIEW_LENGTH - 1] + "…"


def _message_payload(
    message: UserRequestMessage,
    ctx: AuthContext,
    names: dict[uuid.UUID, str],
) -> dict[str, Any]:
    return {
        "id": message.id,
        "author_name": names.get(message.author_user_id, "Utilizador"),
        "is_staff_reply": bool(message.is_staff_reply),
        "is_mine": message.author_user_id == ctx.user.id,
        "body": message.body,
        "created_at": message.created_at,
    }


def _detail_payload(
    db: Session,
    request: UserRequest,
    ctx: AuthContext,
) -> dict[str, Any]:
    messages = _messages_by_request(db, {request.id}).get(request.id, [])
    user_ids = {request.created_by_user_id}
    user_ids.update(message.author_user_id for message in messages)
    names = _display_names(db, user_ids)
    return {
        "id": request.id,
        "status": request.status,
        "page_path": request.page_path,
        "created_at": request.created_at,
        "updated_at": request.updated_at,
        "author_name": names.get(request.created_by_user_id, "Utilizador"),
        "messages": [_message_payload(message, ctx, names) for message in messages],
    }


def create_request(db: Session, ctx: AuthContext, body: RequestCreate) -> UserRequest:
    """Create a request and its first message in the current transaction."""
    _require_create(ctx)
    open_count = (
        db.query(UserRequest)
        .filter(
            UserRequest.created_by_user_id == ctx.user.id,
            UserRequest.status == REQUEST_STATUS_OPEN,
        )
        .count()
    )
    if open_count >= MAX_OPEN_REQUESTS_PER_AUTHOR:
        raise UserRequestConflict("Não pode ter mais de 20 pedidos abertos.")

    now = _now_utc()
    request = UserRequest(
        created_by_user_id=ctx.user.id,
        status=REQUEST_STATUS_OPEN,
        page_path=body.page_path,
        created_at=now,
        updated_at=now,
    )
    db.add(request)
    db.flush()

    message = UserRequestMessage(
        request_id=request.id,
        author_user_id=ctx.user.id,
        is_staff_reply=_is_manager(ctx),
        body=_clean_body(body.body),
        created_at=now,
    )
    db.add(message)
    db.flush()
    return request


def list_requests(
    db: Session,
    ctx: AuthContext,
    *,
    scope: str | None,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    effective_scope = scope or ("all" if _is_manager(ctx) else "mine")
    if effective_scope not in {"mine", "all"}:
        raise UserRequestError("Âmbito inválido.")
    if effective_scope == "all" and not _is_manager(ctx):
        raise UserRequestForbidden("Sem permissão para consultar todos os pedidos.")
    if status not in {None, "open", "resolved", "all"}:
        raise UserRequestError("Estado inválido.")

    query = db.query(UserRequest)
    if effective_scope == "mine":
        query = query.filter(UserRequest.created_by_user_id == ctx.user.id)
    if status not in (None, "all"):
        query = query.filter(UserRequest.status == status)

    total = query.count()
    requests = (
        query.order_by(UserRequest.updated_at.desc(), UserRequest.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    request_ids = {request.id for request in requests}
    messages_by_request = _messages_by_request(db, request_ids)
    user_ids = {request.created_by_user_id for request in requests}
    for messages in messages_by_request.values():
        user_ids.update(message.author_user_id for message in messages)
    names = _display_names(db, user_ids)

    items: list[dict[str, Any]] = []
    for request in requests:
        messages = messages_by_request.get(request.id, [])
        last_message = messages[-1] if messages else None
        items.append(
            {
                "id": request.id,
                "status": request.status,
                "page_path": request.page_path,
                "created_at": request.created_at,
                "updated_at": request.updated_at,
                "author_name": names.get(request.created_by_user_id, "Utilizador"),
                "message_count": len(messages),
                "last_message_preview": _preview(last_message.body) if last_message else None,
                "last_message_is_staff": bool(last_message.is_staff_reply) if last_message else None,
            }
        )
    return items, total


def get_request_detail(db: Session, ctx: AuthContext, request_id: uuid.UUID) -> dict[str, Any]:
    request = _request_or_404(db, request_id)
    _require_access(request, ctx)
    return _detail_payload(db, request, ctx)


def summarize_requests(db: Session, ctx: AuthContext) -> int:
    query = db.query(UserRequest).filter(UserRequest.status == REQUEST_STATUS_OPEN)
    if not _is_manager(ctx):
        query = query.filter(UserRequest.created_by_user_id == ctx.user.id)
    return query.count()


def add_message(
    db: Session,
    ctx: AuthContext,
    request_id: uuid.UUID,
    body: RequestMessageCreate,
) -> dict[str, Any]:
    request = _request_or_404(db, request_id)
    _require_access(request, ctx)
    clean_body = _clean_body(body.body)
    is_staff_reply = _is_manager(ctx)
    now = _now_utc()

    if request.status == REQUEST_STATUS_RESOLVED and not is_staff_reply:
        request.status = REQUEST_STATUS_OPEN
        request.resolved_at = None
        request.resolved_by_user_id = None
    request.updated_at = now
    message = UserRequestMessage(
        request_id=request.id,
        author_user_id=ctx.user.id,
        is_staff_reply=is_staff_reply,
        body=clean_body,
        created_at=now,
    )
    db.add(message)
    db.flush()
    names = _display_names(db, {ctx.user.id})
    return _message_payload(message, ctx, names)


def change_status(
    db: Session,
    ctx: AuthContext,
    request_id: uuid.UUID,
    status: str,
) -> dict[str, Any]:
    if not _is_manager(ctx):
        raise UserRequestForbidden("Sem permissão para alterar o estado dos pedidos.")
    if status not in {REQUEST_STATUS_OPEN, REQUEST_STATUS_RESOLVED}:
        raise UserRequestError("Estado inválido.")

    request = _request_or_404(db, request_id)
    now = _now_utc()
    request.status = status
    request.updated_at = now
    if status == REQUEST_STATUS_RESOLVED:
        request.resolved_at = now
        request.resolved_by_user_id = ctx.user.id
    else:
        request.resolved_at = None
        request.resolved_by_user_id = None
    db.flush()
    return _detail_payload(db, request, ctx)


def request_detail_for_response(
    db: Session, ctx: AuthContext, request: UserRequest
) -> dict[str, Any]:
    """Build the full thread after a create, before the route commits."""
    return _detail_payload(db, request, ctx)
