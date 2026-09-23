"""Pedidos de material a fornecedores (D-067). Toda a regra vive em
`app/services/material_requests.py` (máquina de estados, permissões por ação,
histórico); as rotas só resolvem o projeto/âmbito e traduzem erros. O sistema
nunca envia email: `email-draft` devolve texto para uma pessoa copiar.
"""
from __future__ import annotations

import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.inventory import InventoryItem, MaterialRequest, MaterialRequestItem
from app.models.people import Person
from app.models.project import Project
from app.models.supplier import Supplier
from app.schemas.material_requests import (
    EmailDraftRead,
    MaterialRequestActionBody,
    MaterialRequestCreate,
    MaterialRequestHistoryRead,
    MaterialRequestLineRead,
    MaterialRequestRead,
    MaterialRequestUpdate,
)
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, PermissionDenied, can_view_project
from app.services.material_requests import (
    LineInput,
    MaterialRequestError,
    allowed_actions,
    apply_action,
    build_email_draft,
    create_request,
    list_history,
    line_total,
    list_requests,
    request_total,
    update_draft,
)

router = APIRouter(prefix="/api/material-requests", tags=["material-requests"])


def _require_view(ctx: AuthContext) -> None:
    if not ctx.has_permission("inventory.view"):
        raise HTTPException(status_code=403, detail="Sem permissão para ver pedidos de material.")


def _visible_request(db: Session, ctx: AuthContext, request_id: uuid.UUID) -> tuple[MaterialRequest, Project]:
    """404 (nunca 403) quando o pedido não existe OU o projeto está fora do
    âmbito — não revela a existência de pedidos alheios."""
    _require_view(ctx)
    request = db.get(MaterialRequest, request_id)
    project = db.get(Project, request.project_id) if request else None
    if request is None or project is None or not can_view_project(ctx, project):
        raise HTTPException(status_code=404, detail="Pedido de material não encontrado.")
    return request, project


def _lines(db: Session, request_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[MaterialRequestItem]]:
    by_request: dict[uuid.UUID, list[MaterialRequestItem]] = defaultdict(list)
    if not request_ids:
        return by_request
    rows = (
        db.query(MaterialRequestItem)
        .filter(MaterialRequestItem.request_id.in_(request_ids))
        .order_by(MaterialRequestItem.position.asc(), MaterialRequestItem.id.asc())
        .all()
    )
    for row in rows:
        by_request[row.request_id].append(row)
    return by_request


def _to_reads(
    db: Session, ctx: AuthContext, requests: list[MaterialRequest], *, with_history: bool = False
) -> list[MaterialRequestRead]:
    """Número de queries fixo, independente do número de pedidos."""
    if not requests:
        return []
    lines_by_request = _lines(db, [r.id for r in requests])
    projects = {p.id: p for p in db.query(Project).filter(Project.id.in_({r.project_id for r in requests})).all()}
    supplier_ids = {r.supplier_id for r in requests if r.supplier_id}
    suppliers = (
        {s.id: s for s in db.query(Supplier).filter(Supplier.id.in_(supplier_ids)).all()} if supplier_ids else {}
    )
    item_ids = {line.item_id for lines in lines_by_request.values() for line in lines if line.item_id}
    units = {i.id: i.unit for i in db.query(InventoryItem).filter(InventoryItem.id.in_(item_ids)).all()} if item_ids else {}

    history_by_request: dict[uuid.UUID, list] = {}
    person_ids = {r.created_by_person_id for r in requests} | {r.approved_by_person_id for r in requests}
    if with_history:
        for r in requests:
            history_by_request[r.id] = list_history(db, r.id)
        person_ids |= {h.changed_by_person_id for hs in history_by_request.values() for h in hs}
    person_ids.discard(None)
    names = {p.id: p.display_name for p in db.query(Person).filter(Person.id.in_(person_ids)).all()} if person_ids else {}

    reads: list[MaterialRequestRead] = []
    for r in requests:
        items = lines_by_request.get(r.id, [])
        project = projects[r.project_id]
        reads.append(
            MaterialRequestRead(
                id=r.id,
                project_id=r.project_id,
                project_name=project.name,
                supplier_id=r.supplier_id,
                supplier_name=suppliers[r.supplier_id].name if r.supplier_id in suppliers else None,
                status=r.status,
                notes=r.notes,
                created_by_display_name=names.get(r.created_by_person_id),
                approved_by_display_name=names.get(r.approved_by_person_id),
                created_at=r.created_at,
                updated_at=r.updated_at,
                lines=[
                    MaterialRequestLineRead(
                        id=i.id,
                        item_id=i.item_id,
                        description=i.description,
                        quantity=i.quantity,
                        unit=units.get(i.item_id) if i.item_id else None,
                        unit_price=i.unit_price,
                        line_total=line_total(i),
                    )
                    for i in items
                ],
                total=request_total(items),
                allowed_actions=allowed_actions(ctx, r, project),
                history=[
                    MaterialRequestHistoryRead(
                        action=h.action,
                        from_status=h.from_status,
                        to_status=h.to_status,
                        changed_by_display_name=names.get(h.changed_by_person_id),
                        note=h.note,
                        changed_at=h.changed_at,
                    )
                    for h in history_by_request.get(r.id, [])
                ],
            )
        )
    return reads


def _lines_input(body_lines) -> list[LineInput]:
    return [LineInput(quantity=l.quantity, item_id=l.item_id, description=l.description) for l in body_lines]


def _one(db: Session, ctx: AuthContext, request: MaterialRequest) -> MaterialRequestRead:
    return _to_reads(db, ctx, [request], with_history=True)[0]


@router.get("", response_model=list[MaterialRequestRead])
def list_requests_endpoint(
    project_id: uuid.UUID | None = Query(default=None),
    supplier_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[MaterialRequestRead]:
    _require_view(ctx)
    return _to_reads(db, ctx, list_requests(db, ctx, project_id=project_id, supplier_id=supplier_id, status=status))


@router.post("", response_model=MaterialRequestRead, status_code=201)
def create_request_endpoint(
    body: MaterialRequestCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> MaterialRequestRead:
    project = db.get(Project, body.project_id)
    if project is None or not can_view_project(ctx, project):
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")
    try:
        request = create_request(
            db,
            ctx,
            project=project,
            supplier_id=body.supplier_id,
            lines=_lines_input(body.lines),
            notes=body.notes,
        )
    except PermissionDenied:
        raise HTTPException(status_code=403, detail="Sem permissão para criar pedidos de material neste projeto.")
    except MaterialRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _one(db, ctx, request)


@router.get("/{request_id}", response_model=MaterialRequestRead)
def get_request_endpoint(
    request_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> MaterialRequestRead:
    request, _project = _visible_request(db, ctx, request_id)
    return _one(db, ctx, request)


@router.patch("/{request_id}", response_model=MaterialRequestRead)
def update_request_endpoint(
    request_id: uuid.UUID,
    body: MaterialRequestUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> MaterialRequestRead:
    request, project = _visible_request(db, ctx, request_id)
    changes = body.model_dump(exclude_unset=True)
    kwargs: dict = {}
    if "supplier_id" in changes:
        kwargs["supplier_id"] = changes["supplier_id"]
    if "notes" in changes:
        kwargs["notes"] = changes["notes"]
    if "lines" in changes and changes["lines"] is not None:
        kwargs["lines"] = _lines_input(body.lines or [])
    try:
        request = update_draft(db, ctx, request, project, **kwargs)
    except PermissionDenied:
        raise HTTPException(status_code=403, detail="Sem permissão para editar este pedido.")
    except MaterialRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _one(db, ctx, request)


@router.post("/{request_id}/actions", response_model=MaterialRequestRead)
def apply_action_endpoint(
    request_id: uuid.UUID,
    body: MaterialRequestActionBody,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> MaterialRequestRead:
    request, project = _visible_request(db, ctx, request_id)
    prices = {p.line_id: p.unit_price for p in body.prices}
    if len(prices) != len(body.prices):
        raise HTTPException(status_code=400, detail="Há linhas repetidas no orçamento.")
    try:
        request = apply_action(db, ctx, request, project, action=body.action, note=body.note, prices=prices)
    except PermissionDenied:
        raise HTTPException(status_code=403, detail="Sem permissão para esta ação neste pedido.")
    except MaterialRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _one(db, ctx, request)


@router.get("/{request_id}/email-draft", response_model=EmailDraftRead)
def email_draft_endpoint(
    request_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> EmailDraftRead:
    """Texto para uma pessoa rever, copiar e enviar — o sistema nunca envia (D-010)."""
    request, project = _visible_request(db, ctx, request_id)
    supplier = db.get(Supplier, request.supplier_id) if request.supplier_id else None
    items = _lines(db, [request.id]).get(request.id, [])
    unit_ids = {i.item_id for i in items if i.item_id}
    units = {i.id: i.unit for i in db.query(InventoryItem).filter(InventoryItem.id.in_(unit_ids)).all()} if unit_ids else {}
    draft = build_email_draft(request, items, supplier, project, units)
    return EmailDraftRead(to=draft.to, subject=draft.subject, body=draft.body)
