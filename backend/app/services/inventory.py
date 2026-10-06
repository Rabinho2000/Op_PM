"""Inventário como livro de movimentos — ver app/models/inventory.py e
docs/INVENTORY_RULES.md para o contrato exato. Nenhuma operação apaga ou
edita um `InventoryMovement` existente; reverter é sempre um novo
movimento de sinal oposto.

Quatro números por (item, projeto) — ver docs/PLAN_OPERATIONS_MVP.md
secção 3:

    stock_fisico_central = Σ entrada − Σ saida − Σ consumo + Σ devolucao + Σ ajuste (com sinal)
    reservado[projeto]   = Σ reserva[projeto] − Σ liberta_reserva[projeto] − Σ consumo[projeto]
    stock_disponivel     = stock_fisico_central − Σ reservado[*] (todos os projetos)
    consumido[projeto]   = Σ consumo[projeto] − Σ devolucao[projeto]

Cada operação pública é transacional (um único commit) e idempotente
quando o chamador fornece `idempotency_key`: repetir a mesma chave devolve
o movimento já criado, nunca duplica.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models.inventory import (
    MOVEMENT_AJUSTE,
    MOVEMENT_CONSUMO,
    MOVEMENT_DEVOLUCAO,
    MOVEMENT_ENTRADA,
    MOVEMENT_ENTREGA,
    MOVEMENT_LIBERTA_RESERVA,
    MOVEMENT_RECOLHA,
    MOVEMENT_RESERVA,
    MOVEMENT_SAIDA,
    InventoryItem,
    InventoryLocation,
    InventoryMovement,
    ProjectMaterialRequirement,
)

ZERO = Decimal("0")
QUANTITY_QUANTUM = Decimal("0.001")
MONEY_QUANTUM = Decimal("0.01")


def _canonical_quantity(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value).quantize(QUANTITY_QUANTUM, rounding=ROUND_HALF_UP)


def _canonical_money(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


class InventoryError(ValueError):
    pass


class InsufficientStockError(InventoryError):
    pass


class InsufficientReservationError(InventoryError):
    pass


class InactiveInventoryReferenceError(InventoryError):
    pass


class IdempotencyConflictError(InventoryError):
    """An idempotency key was reused for a different request."""


def _fingerprint_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _movement_fingerprint(
    *,
    item_id: uuid.UUID,
    movement_type: str,
    quantity: Decimal,
    project_id: uuid.UUID | None,
    location_id: uuid.UUID | None,
    destination_location_id: uuid.UUID | None,
    reference: str,
    unit_cost: Decimal | None,
) -> str:
    # The compatibility token is only valid when the request omitted a
    # location. Explicit locations remain part of the canonical fingerprint.
    fingerprint_location_id: object = location_id
    if location_id is None and movement_type in (MOVEMENT_ENTRADA, MOVEMENT_AJUSTE):
        fingerprint_location_id = "__central__"
    payload = {
        "item_id": _fingerprint_value(item_id),
        "movement_type": movement_type,
        "quantity": _fingerprint_value(_canonical_quantity(quantity)),
        "project_id": _fingerprint_value(project_id),
        "location_id": _fingerprint_value(fingerprint_location_id),
        "destination_location_id": _fingerprint_value(destination_location_id),
        "reference": reference,
        "unit_cost": _fingerprint_value(_canonical_money(unit_cost)),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _serialize_item(db: Session, item_id: uuid.UUID) -> None:
    """Acquire the item row before reading any balance.

    PostgreSQL takes a row lock through SELECT FOR UPDATE. SQLite has no row locks;
    the first write upgrades the transaction to SQLite's RESERVED writer lock,
    which serializes writers while keeping the same code path portable. The
    SQLite statement is deliberately a no-op so the model remains append-only.
    """
    if db.get_bind().dialect.name == "postgresql":
        item_row = db.execute(
            select(InventoryItem.id).where(InventoryItem.id == item_id).with_for_update()
        ).scalar_one_or_none()
        if item_row is None:
            raise InventoryError("O artigo de inventário não existe.")
        return

    for attempt in range(5):
        try:
            result = db.execute(
                update(InventoryItem)
                .where(InventoryItem.id == item_id)
                .values(updated_at=InventoryItem.updated_at)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                raise InventoryError("O artigo de inventário não existe.")
            return
        except OperationalError as exc:
            if db.get_bind().dialect.name != "sqlite" or "locked" not in str(exc).lower() or attempt == 4:
                raise
            # SQLite can detect a reader-to-writer deadlock immediately and
            # will not wait for the other reader. Roll back this read before
            # retrying so the other writer can make progress.
            db.rollback()
            time.sleep(0.02 * (2**attempt))


def _lock_refresh_item(db: Session, item: InventoryItem) -> InventoryItem:
    """Serialize on the item, then discard the caller's stale ORM state."""
    _serialize_item(db, item.id)
    db.refresh(item)
    return item


def _prepare_item_movement(
    db: Session,
    *,
    item: InventoryItem,
    idempotency_key: str | None,
    request_fingerprint: str,
) -> InventoryMovement | None:
    """Lock/refresh first; replay lookup precedes active validation.

    A retry remains replayable even when the item was deactivated after the
    original movement. New writes validate the refreshed row.
    """
    _lock_refresh_item(db, item)
    existing = _existing_by_idempotency_key(db, idempotency_key, request_fingerprint)
    if existing is not None:
        return existing
    _require_active_item(item)
    return None


def _existing_movement_fingerprint(db: Session, movement: InventoryMovement) -> str:
    location_id = movement.location_id
    if location_id is None and movement.movement_type in (MOVEMENT_ENTRADA, MOVEMENT_AJUSTE):
        location_id = active_central_location(db).id
    return _movement_fingerprint(
        item_id=movement.item_id,
        movement_type=movement.movement_type,
        quantity=Decimal(movement.quantity),
        project_id=movement.project_id,
        location_id=location_id,
        destination_location_id=movement.destination_location_id,
        reference=movement.reference,
        unit_cost=movement.unit_cost,
    )


def _existing_by_idempotency_key(
    db: Session, idempotency_key: str | None, request_fingerprint: str | None = None
) -> InventoryMovement | None:
    if not idempotency_key:
        return None
    existing = (
        db.query(InventoryMovement)
        .filter(InventoryMovement.idempotency_key == idempotency_key)
        .one_or_none()
    )
    if existing is None or request_fingerprint is None:
        return existing
    stored_fingerprint = existing.idempotency_fingerprint or _existing_movement_fingerprint(db, existing)
    if stored_fingerprint != request_fingerprint:
        raise IdempotencyConflictError(
            "A chave de idempotência já foi usada para um pedido diferente."
        )
    if existing.idempotency_fingerprint is None:
        # Only a complete legacy match is backfilled; mismatched reuse never
        # mutates the historical movement.
        existing.idempotency_fingerprint = stored_fingerprint
        db.flush()
        db.commit()
        db.refresh(existing)
    return existing


def _require_active_item(item: InventoryItem) -> None:
    if not item.is_active:
        raise InactiveInventoryReferenceError("O artigo de inventário está inativo.")


def active_central_location(db: Session) -> InventoryLocation:
    locations = (
        db.query(InventoryLocation)
        .filter(
            InventoryLocation.location_type == "central",
            InventoryLocation.is_active.is_(True),
        )
        .all()
    )
    if len(locations) != 1:
        raise InventoryError("É necessária exatamente uma localização central ativa.")
    return locations[0]


def _require_active_central_location(db: Session, location_id: uuid.UUID) -> InventoryLocation:
    location = db.get(InventoryLocation, location_id)
    if location is None or not location.is_active:
        raise InactiveInventoryReferenceError("A localização de inventário está inativa ou não existe.")
    if location.location_type != "central":
        raise InactiveInventoryReferenceError("A entrada de stock só pode ser ligada à localização central.")
    return location


def _movement_sum(
    db: Session,
    *,
    item_id: uuid.UUID,
    movement_types: tuple[str, ...],
    project_id: uuid.UUID | None = None,
    project_filter: bool = False,
) -> Decimal:
    query = db.query(func.coalesce(func.sum(InventoryMovement.quantity), ZERO)).filter(
        InventoryMovement.item_id == item_id,
        InventoryMovement.movement_type.in_(movement_types),
    )
    if project_filter:
        query = query.filter(InventoryMovement.project_id == project_id)
    result = query.scalar()
    return (_canonical_quantity(Decimal(result)) or ZERO) if result is not None else ZERO


def physical_stock_central(db: Session, item_id: uuid.UUID) -> Decimal:
    entradas = _movement_sum(db, item_id=item_id, movement_types=(MOVEMENT_ENTRADA,))
    saidas = _movement_sum(db, item_id=item_id, movement_types=(MOVEMENT_SAIDA,))
    consumos = _movement_sum(db, item_id=item_id, movement_types=(MOVEMENT_CONSUMO,))
    devolucoes = _movement_sum(db, item_id=item_id, movement_types=(MOVEMENT_DEVOLUCAO,))
    # ajuste guarda o delta com sinal (positivo = stock encontrado a mais,
    # negativo = quebra/perda) — soma direta, sem separar por tipo.
    ajustes = _movement_sum(db, item_id=item_id, movement_types=(MOVEMENT_AJUSTE,))
    return entradas - saidas - consumos + devolucoes + ajustes


def reserved_for_project(db: Session, item_id: uuid.UUID, project_id: uuid.UUID) -> Decimal:
    reservas = _movement_sum(
        db, item_id=item_id, movement_types=(MOVEMENT_RESERVA,), project_id=project_id, project_filter=True
    )
    libertacoes = _movement_sum(
        db,
        item_id=item_id,
        movement_types=(MOVEMENT_LIBERTA_RESERVA,),
        project_id=project_id,
        project_filter=True,
    )
    consumos = _movement_sum(
        db, item_id=item_id, movement_types=(MOVEMENT_CONSUMO,), project_id=project_id, project_filter=True
    )
    return reservas - libertacoes - consumos


def total_reserved(db: Session, item_id: uuid.UUID) -> Decimal:
    """Soma de `reserved_for_project` sobre todos os projetos — usada para
    calcular o disponível. Não filtra por projeto: soma reserva/liberta/
    consumo de qualquer projeto."""
    reservas = _movement_sum(db, item_id=item_id, movement_types=(MOVEMENT_RESERVA,))
    libertacoes = _movement_sum(db, item_id=item_id, movement_types=(MOVEMENT_LIBERTA_RESERVA,))
    consumos = _movement_sum(db, item_id=item_id, movement_types=(MOVEMENT_CONSUMO,))
    return reservas - libertacoes - consumos


def available_stock(db: Session, item_id: uuid.UUID) -> Decimal:
    return physical_stock_central(db, item_id) - total_reserved(db, item_id)


def consumed_for_project(db: Session, item_id: uuid.UUID, project_id: uuid.UUID) -> Decimal:
    consumos = _movement_sum(
        db, item_id=item_id, movement_types=(MOVEMENT_CONSUMO,), project_id=project_id, project_filter=True
    )
    devolucoes = _movement_sum(
        db, item_id=item_id, movement_types=(MOVEMENT_DEVOLUCAO,), project_id=project_id, project_filter=True
    )
    return consumos - devolucoes


def on_site_for_project(db: Session, item_id: uuid.UUID, project_id: uuid.UUID) -> Decimal:
    """Material fisicamente na instalação (D-064):

        no_local = Σ entrega − Σ recolha − Σ from_site_quantity(consumo)

    Independente da reserva (pode haver mais no local do que o reservado —
    excedente enviado pela transportadora ou reforço propositado) e do stock
    físico central. Soma simples, independente da ordem dos movimentos."""
    entregas = _movement_sum(
        db, item_id=item_id, movement_types=(MOVEMENT_ENTREGA,), project_id=project_id, project_filter=True
    )
    recolhas = _movement_sum(
        db, item_id=item_id, movement_types=(MOVEMENT_RECOLHA,), project_id=project_id, project_filter=True
    )
    abatido = (
        db.query(func.coalesce(func.sum(InventoryMovement.from_site_quantity), ZERO))
        .filter(
            InventoryMovement.item_id == item_id,
            InventoryMovement.project_id == project_id,
            InventoryMovement.movement_type == MOVEMENT_CONSUMO,
        )
        .scalar()
    )
    return entregas - recolhas - ((_canonical_quantity(Decimal(abatido)) or ZERO) if abatido is not None else ZERO)


def on_site_balances_by_project(
    db: Session, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[uuid.UUID, Decimal]]:
    """Saldo "no local" positivo por projeto e item, numa única query
    agregada (mesma fórmula de `on_site_for_project`). Usado pelo mapa e pelo
    resumo do projeto — nunca uma query por (projeto, item)."""
    result: dict[uuid.UUID, dict[uuid.UUID, Decimal]] = {}
    if not project_ids:
        return result
    signed = case(
        (InventoryMovement.movement_type == MOVEMENT_ENTREGA, InventoryMovement.quantity),
        (InventoryMovement.movement_type == MOVEMENT_RECOLHA, -InventoryMovement.quantity),
        (
            InventoryMovement.movement_type == MOVEMENT_CONSUMO,
            -func.coalesce(InventoryMovement.from_site_quantity, 0),
        ),
        else_=0,
    )
    balance = func.sum(signed)
    rows = (
        db.query(InventoryMovement.project_id, InventoryMovement.item_id, balance.label("on_site"))
        .filter(
            InventoryMovement.project_id.in_(project_ids),
            InventoryMovement.movement_type.in_((MOVEMENT_ENTREGA, MOVEMENT_RECOLHA, MOVEMENT_CONSUMO)),
        )
        .group_by(InventoryMovement.project_id, InventoryMovement.item_id)
        .having(balance > 0)
        .all()
    )
    for project_id, item_id, on_site in rows:
        if project_id is None:
            continue
        result.setdefault(project_id, {})[item_id] = _canonical_quantity(Decimal(on_site)) or ZERO
    return result


@dataclass(frozen=True)
class InventoryItemBalance:
    item_id: uuid.UUID
    physical_stock: Decimal
    available_stock: Decimal
    total_reserved: Decimal


def item_balance(db: Session, item: InventoryItem) -> InventoryItemBalance:
    physical = physical_stock_central(db, item.id)
    reserved = total_reserved(db, item.id)
    return InventoryItemBalance(
        item_id=item.id, physical_stock=physical, available_stock=physical - reserved, total_reserved=reserved
    )


def _create_movement(
    db: Session,
    *,
    item_id: uuid.UUID,
    movement_type: str,
    quantity: Decimal,
    project_id: uuid.UUID | None,
    created_by_person_id: uuid.UUID | None,
    reference: str,
    unit_cost: Decimal | None,
    idempotency_key: str | None,
    from_site_quantity: Decimal | None = None,
    location_id: uuid.UUID | None = None,
    destination_location_id: uuid.UUID | None = None,
    fingerprint_location_id: uuid.UUID | None = None,
) -> InventoryMovement:
    quantity = _canonical_quantity(quantity)  # type: ignore[assignment]
    from_site_quantity = _canonical_quantity(from_site_quantity)
    unit_cost = _canonical_money(unit_cost)
    request_fingerprint = _movement_fingerprint(
        item_id=item_id,
        movement_type=movement_type,
        quantity=quantity,
        project_id=project_id,
        location_id=(
            fingerprint_location_id
            if movement_type in (MOVEMENT_ENTRADA, MOVEMENT_AJUSTE)
            else location_id
        ),
        destination_location_id=destination_location_id,
        reference=reference,
        unit_cost=unit_cost,
    )
    existing = _existing_by_idempotency_key(db, idempotency_key, request_fingerprint)
    if existing is not None:
        return existing

    movement = InventoryMovement(
        from_site_quantity=from_site_quantity,
        item_id=item_id,
        movement_type=movement_type,
        quantity=quantity,
        project_id=project_id,
        location_id=location_id,
        destination_location_id=destination_location_id,
        reference=reference,
        unit_cost=unit_cost,
        idempotency_key=idempotency_key,
        idempotency_fingerprint=request_fingerprint if idempotency_key else None,
        created_by_person_id=created_by_person_id,
    )
    db.add(movement)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request may have won the unique idempotency-key race.
        db.rollback()
        if idempotency_key:
            existing = _existing_by_idempotency_key(db, idempotency_key, request_fingerprint)
            if existing is not None:
                return existing
        raise
    db.refresh(movement)
    return movement


def enter_stock(
    db: Session,
    *,
    item: InventoryItem,
    quantity: Decimal,
    created_by_person_id: uuid.UUID | None,
    reference: str = "",
    unit_cost: Decimal | None = None,
    idempotency_key: str | None = None,
    location_id: uuid.UUID | None = None,
) -> InventoryMovement:
    quantity = _canonical_quantity(quantity)  # type: ignore[assignment]
    if quantity <= ZERO:
        raise InventoryError("A quantidade de entrada tem de ser positiva.")
    central = active_central_location(db) if location_id is None else _require_active_central_location(db, location_id)
    existing = _prepare_item_movement(
        db,
        item=item,
        idempotency_key=idempotency_key,
        request_fingerprint=_movement_fingerprint(
            item_id=item.id,
            movement_type=MOVEMENT_ENTRADA,
            quantity=quantity,
            project_id=None,
            location_id=central.id,
            destination_location_id=None,
            reference=reference,
            unit_cost=unit_cost,
        ),
    )
    if existing is not None:
        return existing
    return _create_movement(
        db,
        item_id=item.id,
        movement_type=MOVEMENT_ENTRADA,
        quantity=quantity,
        project_id=None,
        created_by_person_id=created_by_person_id,
        reference=reference,
        unit_cost=unit_cost,
        idempotency_key=idempotency_key,
        location_id=central.id,
        fingerprint_location_id=central.id,
    )


def adjust_stock(
    db: Session,
    *,
    item: InventoryItem,
    delta: Decimal,
    created_by_person_id: uuid.UUID | None,
    reference: str = "",
    idempotency_key: str | None = None,
    location_id: uuid.UUID | None = None,
) -> InventoryMovement:
    """`delta` pode ser positivo (stock encontrado a mais) ou negativo
    (quebra/perda) — nunca deixa o stock físico central ficar negativo."""
    delta = _canonical_quantity(delta)  # type: ignore[assignment]
    if delta == ZERO:
        raise InventoryError("O ajuste tem de ter um valor diferente de zero.")
    central = active_central_location(db) if location_id is None else _require_active_central_location(db, location_id)
    existing = _prepare_item_movement(
        db,
        item=item,
        idempotency_key=idempotency_key,
        request_fingerprint=_movement_fingerprint(
            item_id=item.id,
            movement_type=MOVEMENT_AJUSTE,
            quantity=delta,
            project_id=None,
            location_id=central.id,
            destination_location_id=None,
            reference=reference,
            unit_cost=None,
        ),
    )
    if existing is not None:
        return existing
    current = physical_stock_central(db, item.id)
    if current + delta < ZERO:
        raise InsufficientStockError(
            f"Ajuste deixaria o stock físico negativo (atual {current}, ajuste {delta})."
        )
    return _create_movement(
        db,
        item_id=item.id,
        movement_type=MOVEMENT_AJUSTE,
        quantity=delta,
        project_id=None,
        created_by_person_id=created_by_person_id,
        reference=reference,
        unit_cost=None,
        idempotency_key=idempotency_key,
        location_id=central.id,
        fingerprint_location_id=central.id,
    )


def reserve_for_project(
    db: Session,
    *,
    item: InventoryItem,
    project_id: uuid.UUID,
    quantity: Decimal,
    created_by_person_id: uuid.UUID | None,
    reference: str = "",
    idempotency_key: str | None = None,
) -> InventoryMovement:
    quantity = _canonical_quantity(quantity)  # type: ignore[assignment]
    if quantity <= ZERO:
        raise InventoryError("A quantidade a reservar tem de ser positiva.")
    existing = _prepare_item_movement(
        db,
        item=item,
        idempotency_key=idempotency_key,
        request_fingerprint=_movement_fingerprint(
            item_id=item.id,
            movement_type=MOVEMENT_RESERVA,
            quantity=quantity,
            project_id=project_id,
            location_id=None,
            destination_location_id=None,
            reference=reference,
            unit_cost=None,
        ),
    )
    if existing is not None:
        return existing
    available = available_stock(db, item.id)
    if quantity > available:
        raise InsufficientStockError(
            f"Stock disponível insuficiente para reservar (disponível {available}, pedido {quantity})."
        )
    return _create_movement(
        db,
        item_id=item.id,
        movement_type=MOVEMENT_RESERVA,
        quantity=quantity,
        project_id=project_id,
        created_by_person_id=created_by_person_id,
        reference=reference,
        unit_cost=None,
        idempotency_key=idempotency_key,
    )


def release_reservation(
    db: Session,
    *,
    item: InventoryItem,
    project_id: uuid.UUID,
    quantity: Decimal,
    created_by_person_id: uuid.UUID | None,
    reference: str = "",
    idempotency_key: str | None = None,
) -> InventoryMovement:
    quantity = _canonical_quantity(quantity)  # type: ignore[assignment]
    if quantity <= ZERO:
        raise InventoryError("A quantidade a libertar tem de ser positiva.")
    existing = _prepare_item_movement(
        db,
        item=item,
        idempotency_key=idempotency_key,
        request_fingerprint=_movement_fingerprint(
            item_id=item.id,
            movement_type=MOVEMENT_LIBERTA_RESERVA,
            quantity=quantity,
            project_id=project_id,
            location_id=None,
            destination_location_id=None,
            reference=reference,
            unit_cost=None,
        ),
    )
    if existing is not None:
        return existing
    reserved = reserved_for_project(db, item.id, project_id)
    if quantity > reserved:
        raise InsufficientReservationError(
            f"Não pode libertar mais do que o reservado (reservado {reserved}, pedido {quantity})."
        )
    return _create_movement(
        db,
        item_id=item.id,
        movement_type=MOVEMENT_LIBERTA_RESERVA,
        quantity=quantity,
        project_id=project_id,
        created_by_person_id=created_by_person_id,
        reference=reference,
        unit_cost=None,
        idempotency_key=idempotency_key,
    )


def consume_from_project(
    db: Session,
    *,
    item: InventoryItem,
    project_id: uuid.UUID,
    quantity: Decimal,
    created_by_person_id: uuid.UUID | None,
    reference: str = "",
    idempotency_key: str | None = None,
) -> InventoryMovement:
    """Exige reserva ativa suficiente no projeto — o pedido original não
    define "consumo sem reserva"; esta é a opção mais segura e auditável
    (ver docs/PLAN_OPERATIONS_MVP.md secção 11)."""
    quantity = _canonical_quantity(quantity)  # type: ignore[assignment]
    if quantity <= ZERO:
        raise InventoryError("A quantidade a consumir tem de ser positiva.")
    existing = _prepare_item_movement(
        db,
        item=item,
        idempotency_key=idempotency_key,
        request_fingerprint=_movement_fingerprint(
            item_id=item.id,
            movement_type=MOVEMENT_CONSUMO,
            quantity=quantity,
            project_id=project_id,
            location_id=None,
            destination_location_id=None,
            reference=reference,
            unit_cost=None,
        ),
    )
    if existing is not None:
        return existing
    reserved = reserved_for_project(db, item.id, project_id)
    if quantity > reserved:
        raise InsufficientReservationError(
            f"Não pode consumir mais do que o reservado para este projeto "
            f"(reservado {reserved}, pedido {quantity})."
        )
    # O consumo abate primeiro ao material que está no local (D-064) — a parte
    # abatida fica registada no próprio movimento. O consumo em si (exige
    # reserva, reduz stock central e reservado) não muda.
    on_site = max(on_site_for_project(db, item.id, project_id), ZERO)
    return _create_movement(
        db,
        item_id=item.id,
        movement_type=MOVEMENT_CONSUMO,
        quantity=quantity,
        project_id=project_id,
        created_by_person_id=created_by_person_id,
        reference=reference,
        unit_cost=None,
        idempotency_key=idempotency_key,
        from_site_quantity=min(quantity, on_site),
    )


def return_to_stock(
    db: Session,
    *,
    item: InventoryItem,
    project_id: uuid.UUID,
    quantity: Decimal,
    created_by_person_id: uuid.UUID | None,
    reference: str = "",
    idempotency_key: str | None = None,
) -> InventoryMovement:
    """Reverte um consumo anterior: aumenta o stock físico central, nunca
    reabre a reserva do projeto de origem (decisão assumida — ver
    docs/PLAN_OPERATIONS_MVP.md secção 11)."""
    quantity = _canonical_quantity(quantity)  # type: ignore[assignment]
    if quantity <= ZERO:
        raise InventoryError("A quantidade a devolver tem de ser positiva.")
    existing = _prepare_item_movement(
        db,
        item=item,
        idempotency_key=idempotency_key,
        request_fingerprint=_movement_fingerprint(
            item_id=item.id,
            movement_type=MOVEMENT_DEVOLUCAO,
            quantity=quantity,
            project_id=project_id,
            location_id=None,
            destination_location_id=None,
            reference=reference,
            unit_cost=None,
        ),
    )
    if existing is not None:
        return existing
    consumed = consumed_for_project(db, item.id, project_id)
    if quantity > consumed:
        raise InventoryError(
            f"Não pode devolver mais do que o consumido por este projeto "
            f"(consumido {consumed}, pedido {quantity})."
        )
    return _create_movement(
        db,
        item_id=item.id,
        movement_type=MOVEMENT_DEVOLUCAO,
        quantity=quantity,
        project_id=project_id,
        created_by_person_id=created_by_person_id,
        reference=reference,
        unit_cost=None,
        idempotency_key=idempotency_key,
    )


def deliver_to_project(
    db: Session,
    *,
    item: InventoryItem,
    project_id: uuid.UUID,
    quantity: Decimal,
    created_by_person_id: uuid.UUID | None,
    reference: str = "",
    idempotency_key: str | None = None,
) -> InventoryMovement:
    """Regista material que passou a estar fisicamente na instalação.

    Sem limite pela reserva: a obra pode receber mais do que o reservado
    (excedente da transportadora ou reforço propositado, ex. painéis de
    reserva). Não altera o stock físico central nem a reserva (D-064)."""
    quantity = _canonical_quantity(quantity)  # type: ignore[assignment]
    if quantity <= ZERO:
        raise InventoryError("A quantidade a entregar tem de ser positiva.")
    existing = _prepare_item_movement(
        db,
        item=item,
        idempotency_key=idempotency_key,
        request_fingerprint=_movement_fingerprint(
            item_id=item.id,
            movement_type=MOVEMENT_ENTREGA,
            quantity=quantity,
            project_id=project_id,
            location_id=None,
            destination_location_id=None,
            reference=reference,
            unit_cost=None,
        ),
    )
    if existing is not None:
        return existing
    return _create_movement(
        db,
        item_id=item.id,
        movement_type=MOVEMENT_ENTREGA,
        quantity=quantity,
        project_id=project_id,
        created_by_person_id=created_by_person_id,
        reference=reference,
        unit_cost=None,
        idempotency_key=idempotency_key,
    )


def collect_from_project(
    db: Session,
    *,
    item: InventoryItem,
    project_id: uuid.UUID,
    quantity: Decimal,
    created_by_person_id: uuid.UUID | None,
    reference: str = "",
    idempotency_key: str | None = None,
) -> InventoryMovement:
    """Regista material que deixou de estar na instalação (recolhido).

    Não pode recolher mais do que o que está no local. Não liberta a reserva
    nem altera o stock físico central (D-064) — o excedente que motiva uma
    recolha normalmente nunca foi reservado; libertar reserva é uma operação
    separada e explícita."""
    quantity = _canonical_quantity(quantity)  # type: ignore[assignment]
    if quantity <= ZERO:
        raise InventoryError("A quantidade a recolher tem de ser positiva.")
    existing = _prepare_item_movement(
        db,
        item=item,
        idempotency_key=idempotency_key,
        request_fingerprint=_movement_fingerprint(
            item_id=item.id,
            movement_type=MOVEMENT_RECOLHA,
            quantity=quantity,
            project_id=project_id,
            location_id=None,
            destination_location_id=None,
            reference=reference,
            unit_cost=None,
        ),
    )
    if existing is not None:
        return existing
    on_site = on_site_for_project(db, item.id, project_id)
    if quantity > on_site:
        raise InventoryError(
            f"Não pode recolher mais do que o que está no local (no local {on_site}, pedido {quantity})."
        )
    return _create_movement(
        db,
        item_id=item.id,
        movement_type=MOVEMENT_RECOLHA,
        quantity=quantity,
        project_id=project_id,
        created_by_person_id=created_by_person_id,
        reference=reference,
        unit_cost=None,
        idempotency_key=idempotency_key,
    )


@dataclass(frozen=True)
class MaterialRequirementStatus:
    project_id: uuid.UUID
    item_id: uuid.UUID
    quantity_required: Decimal
    reserved: Decimal
    consumed: Decimal
    missing: Decimal
    available_stock_sufficient: bool


def create_material_requirement(
    db: Session,
    *,
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    quantity_required: Decimal,
    notes: str = "",
    created_by_person_id: uuid.UUID | None,
) -> ProjectMaterialRequirement:
    quantity_required = _canonical_quantity(quantity_required)  # type: ignore[assignment]
    if quantity_required <= ZERO:
        raise InventoryError("A quantidade necessária tem de ser positiva.")
    requirement = ProjectMaterialRequirement(
        project_id=project_id,
        item_id=item_id,
        quantity_required=quantity_required,
        notes=notes,
        source="ui",
        created_by_person_id=created_by_person_id,
    )
    db.add(requirement)
    db.commit()
    db.refresh(requirement)
    return requirement


def update_material_requirement(
    db: Session,
    *,
    requirement: ProjectMaterialRequirement,
    quantity_required: Decimal | None = None,
    notes: str | None = None,
) -> ProjectMaterialRequirement:
    if quantity_required is not None:
        quantity_required = _canonical_quantity(quantity_required) or ZERO
        if quantity_required <= ZERO:
            raise InventoryError("A quantidade necessária tem de ser positiva.")
        requirement.quantity_required = quantity_required
    if notes is not None:
        requirement.notes = notes
    db.commit()
    db.refresh(requirement)
    return requirement


def material_requirement_status(
    db: Session, *, project_id: uuid.UUID, item: InventoryItem, quantity_required: Decimal
) -> MaterialRequirementStatus:
    reserved = reserved_for_project(db, item.id, project_id)
    consumed = consumed_for_project(db, item.id, project_id)
    missing = quantity_required - reserved - consumed
    if missing < ZERO:
        missing = ZERO
    available = available_stock(db, item.id)
    return MaterialRequirementStatus(
        project_id=project_id,
        item_id=item.id,
        quantity_required=quantity_required,
        reserved=reserved,
        consumed=consumed,
        missing=missing,
        available_stock_sufficient=available >= missing,
    )
