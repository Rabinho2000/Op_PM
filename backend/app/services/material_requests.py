"""Pedidos de material a fornecedores (Fase F, D-067).

Máquina de estados aplicada **no servidor** — o cliente nunca decide uma
transição. Cada passo exige a permissão certa e fica registado em
`MaterialRequestHistory` (append-only). Regras herdadas de decisões anteriores:

- O sistema **nunca envia email real** (D-010). "Enviar" (`send`) só regista que
  uma pessoa autorizada aprovou o envio e o fez fora do sistema; o texto do
  email é um rascunho para copiar (`build_email_draft`).
- **Adjudicação sempre por ação humana** (`material_request.adjudicate`); não
  existe nenhum outro caminho (nem automático, nem por IA) até `adjudicado`.
- Valores monetários em `Decimal`/`Numeric`, nunca `float` (D-018).

Estados: `rascunho → pedido_enviado → orcamento_recebido → aprovado →
adjudicado`, mais `cancelado`. `enviado_financeiro` e `pago` existem no modelo
mas **não têm transição** aqui: dependem da integração Financial (por decidir).
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.models.inventory import InventoryItem, MaterialRequest, MaterialRequestHistory, MaterialRequestItem
from app.models.project import Project
from app.models.supplier import Supplier
from app.security.permissions import AuthContext, PermissionDenied, can_edit_project, can_view_project
from app.services.projects import visible_projects_query

STATUS_RASCUNHO = "rascunho"
STATUS_PEDIDO_ENVIADO = "pedido_enviado"
STATUS_ORCAMENTO_RECEBIDO = "orcamento_recebido"
STATUS_APROVADO = "aprovado"
STATUS_ADJUDICADO = "adjudicado"
STATUS_CANCELADO = "cancelado"

ACTION_CREATE = "create"
ACTION_SEND = "send"
ACTION_RECORD_QUOTE = "record_quote"
ACTION_APPROVE = "approve"
ACTION_ADJUDICATE = "adjudicate"
ACTION_CANCEL = "cancel"

# ação -> estado seguinte, por estado de origem. `record_quote` também é válida
# em `orcamento_recebido` (corrigir preços antes de aprovar).
TRANSITIONS: dict[str, dict[str, str]] = {
    STATUS_RASCUNHO: {ACTION_SEND: STATUS_PEDIDO_ENVIADO, ACTION_CANCEL: STATUS_CANCELADO},
    STATUS_PEDIDO_ENVIADO: {ACTION_RECORD_QUOTE: STATUS_ORCAMENTO_RECEBIDO, ACTION_CANCEL: STATUS_CANCELADO},
    STATUS_ORCAMENTO_RECEBIDO: {
        ACTION_RECORD_QUOTE: STATUS_ORCAMENTO_RECEBIDO,
        ACTION_APPROVE: STATUS_APROVADO,
        ACTION_CANCEL: STATUS_CANCELADO,
    },
    STATUS_APROVADO: {ACTION_ADJUDICATE: STATUS_ADJUDICADO, ACTION_CANCEL: STATUS_CANCELADO},
    STATUS_ADJUDICADO: {},
    STATUS_CANCELADO: {},
}

# Permissão exigida por ação. `cancel` tem uma regra própria (ver `_may_cancel`).
ACTION_PERMISSIONS: dict[str, str] = {
    ACTION_SEND: "material_request.approve",
    ACTION_RECORD_QUOTE: "material_request.approve",
    ACTION_APPROVE: "material_request.approve",
    ACTION_ADJUDICATE: "material_request.adjudicate",
}

TWO_PLACES = Decimal("0.01")
MAX_PRICE_DECIMALS = 4  # = escala de MaterialRequestItem.unit_price


class MaterialRequestError(ValueError):
    """Pedido inválido — a mensagem é segura para mostrar ao utilizador."""


@dataclasses.dataclass(frozen=True)
class LineInput:
    quantity: Decimal
    item_id: uuid.UUID | None = None
    description: str = ""


def line_total(item: MaterialRequestItem) -> Decimal | None:
    """Quantidade × preço unitário, arredondado a 2 casas com a MESMA regra do
    total do pedido (half-up) — um único ponto de arredondamento, para o total
    de uma linha nunca contradizer o que o utilizador vê no total."""
    if item.unit_price is None:
        return None
    return (Decimal(item.quantity) * Decimal(item.unit_price)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def request_total(items: list[MaterialRequestItem]) -> Decimal | None:
    """Σ quantidade × preço unitário, arredondado a 2 casas. `None` enquanto
    houver alguma linha sem preço — nunca um total parcial que pareça completo."""
    if not items or any(i.unit_price is None for i in items):
        return None
    return sum((Decimal(i.quantity) * Decimal(i.unit_price) for i in items), Decimal("0")).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )


def _record(
    db: Session,
    request: MaterialRequest,
    *,
    action: str,
    from_status: str | None,
    to_status: str,
    ctx: AuthContext,
    note: str = "",
) -> None:
    db.add(
        MaterialRequestHistory(
            request_id=request.id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            changed_by_person_id=ctx.person_id,
            note=note,
            changed_at=dt.datetime.now(dt.timezone.utc),
        )
    )


# --- Permissões ---


def _may_cancel(ctx: AuthContext, request: MaterialRequest) -> bool:
    if ctx.has_permission("material_request.approve"):
        return True
    # Quem só cria pode cancelar o seu próprio rascunho — nunca um pedido já enviado.
    return (
        ctx.has_permission("material_request.create")
        and request.status == STATUS_RASCUNHO
        and request.created_by_person_id == ctx.person_id
    )


def allowed_actions(ctx: AuthContext, request: MaterialRequest, project: Project) -> list[str]:
    """Ações que ESTE utilizador pode fazer AGORA: máquina de estados ∩
    permissões ∩ âmbito do projeto. O frontend só mostra estas — a regra
    fica num sítio, no servidor, e nunca é reconstruída no cliente."""
    if not can_view_project(ctx, project):
        return []
    actions: list[str] = []
    for action in TRANSITIONS.get(request.status, {}):
        if action == ACTION_CANCEL:
            if _may_cancel(ctx, request):
                actions.append(action)
        elif ctx.has_permission(ACTION_PERMISSIONS[action]):
            actions.append(action)
    return actions


# --- Criação e edição do rascunho ---


def _validate_supplier(db: Session, supplier_id: uuid.UUID | None) -> Supplier | None:
    if supplier_id is None:
        return None
    supplier = db.get(Supplier, supplier_id)
    if supplier is None or not supplier.is_active:
        raise MaterialRequestError("Fornecedor não encontrado ou inativo.")
    return supplier


def _build_items(db: Session, request_id: uuid.UUID, lines: list[LineInput]) -> list[MaterialRequestItem]:
    if not lines:
        raise MaterialRequestError("Indique pelo menos uma linha de material.")
    built: list[MaterialRequestItem] = []
    for position, line in enumerate(lines):
        if line.quantity <= 0:
            raise MaterialRequestError("A quantidade de cada linha tem de ser positiva.")
        description = line.description.strip()
        if line.item_id is not None:
            item = db.get(InventoryItem, line.item_id)
            if item is None:
                raise MaterialRequestError("Um dos itens de inventário não existe.")
            description = description or item.name
        if not description:
            raise MaterialRequestError("Cada linha precisa de um item de inventário ou de uma descrição.")
        built.append(
            MaterialRequestItem(
                request_id=request_id,
                position=position,
                item_id=line.item_id,
                description=description,
                quantity=line.quantity,
            )
        )
    return built


def create_request(
    db: Session,
    ctx: AuthContext,
    *,
    project: Project,
    supplier_id: uuid.UUID | None,
    lines: list[LineInput],
    notes: str = "",
) -> MaterialRequest:
    # Mesma regra de escrita de projeto que reservar/consumir material: PM só nos seus.
    if not (ctx.has_permission("material_request.create") and can_edit_project(ctx, project)):
        raise PermissionDenied("material_request.create")
    _validate_supplier(db, supplier_id)
    request = MaterialRequest(
        project_id=project.id,
        supplier_id=supplier_id,
        status=STATUS_RASCUNHO,
        created_by_person_id=ctx.person_id,
        notes=notes,
    )
    db.add(request)
    db.flush()
    for item in _build_items(db, request.id, lines):
        db.add(item)
    _record(db, request, action=ACTION_CREATE, from_status=None, to_status=STATUS_RASCUNHO, ctx=ctx)
    db.commit()
    db.refresh(request)
    return request


_UNSET = object()


def update_draft(
    db: Session,
    ctx: AuthContext,
    request: MaterialRequest,
    project: Project,
    *,
    supplier_id: object = _UNSET,
    notes: str | None = None,
    lines: list[LineInput] | None = None,
) -> MaterialRequest:
    """Só um rascunho é editável — depois de enviado, o pedido é um registo
    do que foi pedido ao fornecedor e não pode mudar debaixo dele."""
    if request.status != STATUS_RASCUNHO:
        raise MaterialRequestError("Só um pedido em rascunho pode ser editado.")
    owns = request.created_by_person_id == ctx.person_id and ctx.has_permission("material_request.create")
    if not (owns or ctx.has_permission("material_request.approve")) or not can_edit_project(ctx, project):
        raise PermissionDenied("material_request.create")
    if supplier_id is not _UNSET:
        _validate_supplier(db, supplier_id)  # type: ignore[arg-type]
        request.supplier_id = supplier_id  # type: ignore[assignment]
    if notes is not None:
        request.notes = notes
    if lines is not None:
        new_items = _build_items(db, request.id, lines)
        for old in list(request.items):
            db.delete(old)
        db.flush()
        for item in new_items:
            db.add(item)
    db.commit()
    db.refresh(request)
    return request


# --- Transições ---


def apply_action(
    db: Session,
    ctx: AuthContext,
    request: MaterialRequest,
    project: Project,
    *,
    action: str,
    note: str = "",
    prices: dict[uuid.UUID, Decimal] | None = None,
) -> MaterialRequest:
    next_status = TRANSITIONS.get(request.status, {}).get(action)
    if next_status is None:
        raise MaterialRequestError(
            f"Ação '{action}' não permitida com o pedido em '{request.status}'."
        )
    if action not in allowed_actions(ctx, request, project):
        # Estado válido mas sem permissão/âmbito: 403, nunca uma transição silenciosa.
        raise PermissionDenied(ACTION_PERMISSIONS.get(action, "material_request.approve"))

    note = note.strip()
    if action == ACTION_SEND:
        if request.supplier_id is None:
            raise MaterialRequestError("Escolha o fornecedor antes de enviar o pedido.")
        supplier = _validate_supplier(db, request.supplier_id)
        assert supplier is not None
        if not request.items:
            raise MaterialRequestError("O pedido não tem linhas.")
    elif action == ACTION_RECORD_QUOTE:
        _apply_prices(request, prices or {})
    elif action == ACTION_APPROVE:
        # Defesa em profundidade: `record_quote` já garante preços em todas as
        # linhas, mas nunca se aprova um orçamento incompleto.
        if request_total(list(request.items)) is None:
            raise MaterialRequestError("Não pode aprovar um orçamento com linhas sem preço.")
        request.approved_by_person_id = ctx.person_id
    elif action == ACTION_CANCEL and request.status != STATUS_RASCUNHO and not note:
        raise MaterialRequestError("Indique o motivo para cancelar um pedido já enviado.")

    previous = request.status
    request.status = next_status
    _record(db, request, action=action, from_status=previous, to_status=next_status, ctx=ctx, note=note)
    db.commit()
    db.refresh(request)
    return request


def _apply_prices(request: MaterialRequest, prices: dict[uuid.UUID, Decimal]) -> None:
    """O orçamento tem de cobrir TODAS as linhas, com preço positivo."""
    by_id = {i.id: i for i in request.items}
    unknown = set(prices) - set(by_id)
    if unknown:
        raise MaterialRequestError("Um dos preços refere-se a uma linha que não pertence a este pedido.")
    for line_id, price in prices.items():
        if price <= 0:
            raise MaterialRequestError("O preço unitário tem de ser positivo.")
        # Nunca arredondar um preço em silêncio: a coluna guarda 4 casas, por isso
        # mais do que isso é recusado com uma mensagem clara.
        if price.as_tuple().exponent < -MAX_PRICE_DECIMALS:
            raise MaterialRequestError(
                f"O preço unitário admite no máximo {MAX_PRICE_DECIMALS} casas decimais."
            )
        by_id[line_id].unit_price = price
    missing = [i for i in request.items if i.unit_price is None]
    if missing:
        raise MaterialRequestError("O orçamento tem de indicar o preço de todas as linhas.")


# --- Leitura ---


def get_request(db: Session, request_id: uuid.UUID) -> MaterialRequest | None:
    return db.get(MaterialRequest, request_id)


def list_requests(
    db: Session,
    ctx: AuthContext,
    *,
    project_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[MaterialRequest]:
    """Sempre limitado aos projetos que o utilizador vê (`visible_projects_query`)."""
    visible = visible_projects_query(db, ctx).with_entities(Project.id).statement
    query = db.query(MaterialRequest).filter(MaterialRequest.project_id.in_(visible))
    if project_id is not None:
        query = query.filter(MaterialRequest.project_id == project_id)
    if supplier_id is not None:
        query = query.filter(MaterialRequest.supplier_id == supplier_id)
    if status is not None:
        query = query.filter(MaterialRequest.status == status)
    return query.order_by(MaterialRequest.created_at.desc(), MaterialRequest.id.asc()).all()


def list_history(db: Session, request_id: uuid.UUID) -> list[MaterialRequestHistory]:
    return (
        db.query(MaterialRequestHistory)
        .filter(MaterialRequestHistory.request_id == request_id)
        .order_by(MaterialRequestHistory.changed_at.asc(), MaterialRequestHistory.id.asc())
        .all()
    )


@dataclasses.dataclass(frozen=True)
class EmailDraft:
    to: str | None
    subject: str
    body: str


def build_email_draft(
    request: MaterialRequest,
    items: list[MaterialRequestItem],
    supplier: Supplier | None,
    project: Project,
    units: dict[uuid.UUID, str],
) -> EmailDraft:
    """Texto do email ao fornecedor — determinístico (sem IA), para uma pessoa
    rever, copiar e enviar. Nunca é enviado pelo sistema (D-010) e não inclui
    preços."""
    reference = str(request.id)[:8].upper()
    lines = []
    for item in items:
        unit = units.get(item.item_id, "") if item.item_id else ""
        lines.append(f"- {item.quantity.normalize():f} {unit} {item.description}".replace("  ", " ").rstrip())
    delivery = f"\nLocal de entrega: {project.address}" if project.address else ""
    body = (
        f"Bom dia{(' ' + supplier.contact) if supplier and supplier.contact else ''},\n\n"
        f"Gostaríamos de pedir orçamento para o material abaixo, para o projeto {project.name}"
        f" (ref. {reference}).\n\n"
        + "\n".join(lines)
        + delivery
        + (f"\n\nNotas: {request.notes}" if request.notes else "")
        + "\n\nAgradecemos o orçamento com preços unitários e prazo de entrega.\n\nCumprimentos"
    )
    return EmailDraft(
        to=supplier.email if supplier else None,
        subject=f"Pedido de orçamento — {project.name} (ref. {reference})",
        body=body,
    )
