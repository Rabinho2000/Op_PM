"""Inventário como livro de movimentos, não como total editável.

O stock atual de um item é sempre calculado a partir da soma de
`InventoryMovement` (entrada/saída/reserva/ajuste/trânsito) — não existe uma
coluna `stock_atual` editável diretamente. Isto cumpre a regra explícita do
pedido: "Stock deve ser calculado através de movimentos, reservas, entradas,
consumos e ajustes." Ver `app/services/inventory.py` (fase seguinte) para o
cálculo; nesta fase só o modelo/ledger está definido.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk
from app.models.cost import MONEY


class InventoryItem(UUIDPk, TimestampMixin, Base):
    __tablename__ = "inventory_items"

    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), default="un")
    min_stock: Mapped[float] = mapped_column(Float, default=0)
    preferred_supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("suppliers.id"), nullable=True
    )
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)


class InventoryMovement(UUIDPk, TimestampMixin, Base):
    __tablename__ = "inventory_movements"

    item_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("inventory_items.id"), nullable=False)
    # entrada | saida | reserva | liberta_reserva | ajuste | transito_entrada | transito_saida
    movement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=True)
    reference: Mapped[str] = mapped_column(String(256), default="")
    created_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )


class MaterialRequest(UUIDPk, TimestampMixin, Base):
    __tablename__ = "material_requests"

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("suppliers.id"), nullable=True)
    # rascunho | pedido_enviado | orcamento_recebido | aprovado | adjudicado
    # | enviado_financeiro | pago | cancelado
    status: Mapped[str] = mapped_column(String(32), default="rascunho", nullable=False)
    created_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    approved_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")

    items: Mapped[list["MaterialRequestItem"]] = relationship(back_populates="request")


class MaterialRequestItem(UUIDPk, TimestampMixin, Base):
    __tablename__ = "material_request_items"

    request_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("material_requests.id"), nullable=False
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("inventory_items.id"), nullable=True)
    description: Mapped[str] = mapped_column(String(512), default="")
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    # Monetário — Numeric, nunca Float (ver app/models/cost.py:MONEY).
    unit_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)

    request: Mapped["MaterialRequest"] = relationship(back_populates="items")
