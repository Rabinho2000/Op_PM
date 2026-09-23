"""Inventário como livro de movimentos, não como total editável.

O stock atual de um item é sempre calculado a partir da soma de
`InventoryMovement` (entrada/saída/reserva/consumo/devolução/ajuste/trânsito)
— não existe uma coluna `stock_atual` editável diretamente. Isto cumpre a
regra explícita do pedido: "Stock deve ser calculado através de movimentos,
reservas, entradas, consumos e ajustes." Ver `app/services/inventory.py`
para o cálculo e as regras de negócio (reserva/consumo/libertação/devolução
— ver docs/INVENTORY_RULES.md e docs/PLAN_OPERATIONS_MVP.md secção 3).

Quantidades usam `Numeric`, nunca `Float` (pedido explícito do MVP de
Operações — antes desta fase, só os valores monetários seguiam esta regra,
ver D-018). `QUANTITY` guarda 3 casas decimais para cobrir unidades como
metros/quilómetros de cabo sem perder precisão.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk
from app.models.cost import MONEY

# 14 dígitos, 3 casas decimais — cobre quantidades fracionárias (ex. km de
# cabo) sem o erro de arredondamento binário de `float`.
QUANTITY = Numeric(14, 3)

# Preço unitário de material: 4 casas decimais (ver MaterialRequestItem.unit_price).
UNIT_PRICE = Numeric(14, 4)

# Localização física/lógica de stock (ver InventoryLocation.location_type).
LOCATION_TYPE_CENTRAL = "central"
LOCATION_TYPE_PROJECT = "project"
LOCATION_TYPE_VEHICLE = "vehicle"
LOCATION_TYPE_SUPPLIER = "supplier"
LOCATION_TYPES: frozenset[str] = frozenset(
    {LOCATION_TYPE_CENTRAL, LOCATION_TYPE_PROJECT, LOCATION_TYPE_VEHICLE, LOCATION_TYPE_SUPPLIER}
)

# Código estável da localização central semeada por app/migration/seed_dev.py
# — nunca usado para decidir lógica de negócio por comparação de nome/texto,
# só para o seed encontrar o registo que ele próprio cria (idempotência).
CENTRAL_LOCATION_CODE = "IDEALMINDE"

# Tipos de movimento — ver app/services/inventory.py para a semântica exata
# de cada um (o que afeta stock físico vs. reservado vs. disponível).
MOVEMENT_ENTRADA = "entrada"
MOVEMENT_SAIDA = "saida"
MOVEMENT_RESERVA = "reserva"
MOVEMENT_LIBERTA_RESERVA = "liberta_reserva"
MOVEMENT_CONSUMO = "consumo"
MOVEMENT_DEVOLUCAO = "devolucao"
MOVEMENT_AJUSTE = "ajuste"
MOVEMENT_TRANSITO_ENTRADA = "transito_entrada"
MOVEMENT_TRANSITO_SAIDA = "transito_saida"
# Localização física do material numa instalação (D-064). Nenhum dos dois
# altera o stock físico central nem a reserva — só o saldo "no local" (ver
# app/services/inventory.py:on_site_for_project).
MOVEMENT_ENTREGA = "entrega"
MOVEMENT_RECOLHA = "recolha"

MOVEMENT_TYPES: frozenset[str] = frozenset(
    {
        MOVEMENT_ENTRADA,
        MOVEMENT_SAIDA,
        MOVEMENT_RESERVA,
        MOVEMENT_LIBERTA_RESERVA,
        MOVEMENT_CONSUMO,
        MOVEMENT_DEVOLUCAO,
        MOVEMENT_AJUSTE,
        MOVEMENT_TRANSITO_ENTRADA,
        MOVEMENT_TRANSITO_SAIDA,
        MOVEMENT_ENTREGA,
        MOVEMENT_RECOLHA,
    }
)


class InventoryLocation(UUIDPk, TimestampMixin, Base):
    __tablename__ = "inventory_locations"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    location_type: Mapped[str] = mapped_column(String(32), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class InventoryItem(UUIDPk, TimestampMixin, Base):
    __tablename__ = "inventory_items"

    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), default="un")
    min_stock: Mapped[Decimal] = mapped_column(QUANTITY, default=0)
    preferred_supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("suppliers.id"), nullable=True
    )
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class InventoryMovement(UUIDPk, TimestampMixin, Base):
    __tablename__ = "inventory_movements"

    item_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("inventory_items.id"), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=True)
    # Localização afetada (para reserva/consumo/devolução, a localização de
    # origem central quando o movimento não tem outra); destino usado só
    # para trânsito entre localizações. Nenhuma das duas é exigida por
    # todos os tipos de movimento — ver app/services/inventory.py.
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("inventory_locations.id"), nullable=True
    )
    destination_location_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("inventory_locations.id"), nullable=True
    )
    unit_cost: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # Só em `consumo`: quanto do consumo foi abatido ao material que estava no
    # local (D-064). Guardado no próprio movimento — e não recalculado por
    # ordem cronológica — porque `created_at` tem resolução de 1 segundo em
    # SQLite e o saldo "no local" tem de ser independente da ordem. NULL nos
    # movimentos anteriores a esta coluna (tratado como 0).
    from_site_quantity: Mapped[Decimal | None] = mapped_column(QUANTITY, nullable=True)
    reference: Mapped[str] = mapped_column(String(256), default="")
    # Presente só quando o chamador pede idempotência explícita (ex. um
    # pedido HTTP repetido pela UI por falha de rede) — repetir a mesma
    # chave devolve o movimento já criado em vez de duplicar (ver
    # app/services/inventory.py).
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_inventory_movement_idempotency_key"),
    )


class ProjectMaterialRequirement(UUIDPk, TimestampMixin, Base):
    """Necessidade de material de um projeto — comparado contra
    reservado/consumido para calcular "em falta" (ver
    app/services/inventory.py:material_requirement_status)."""

    __tablename__ = "project_material_requirements"
    __table_args__ = (UniqueConstraint("project_id", "item_id", name="uq_project_material_requirement"),)

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("inventory_items.id"), nullable=False)
    quantity_required: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(32), default="ui")
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
    # Ordem das linhas tal como foram introduzidas (D-067). Não se pode ordenar
    # por `created_at`: tem resolução de 1 s em SQLite e as linhas de um mesmo
    # pedido são criadas todas no mesmo segundo.
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("inventory_items.id"), nullable=True)
    description: Mapped[str] = mapped_column(String(512), default="")
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    # Monetário — Numeric, nunca Float. Preço UNITÁRIO com 4 casas (`UNIT_PRICE`,
    # não `MONEY`): materiais custam frequentemente frações de cêntimo (ex.
    # 0.325 €/m de cabo) e `Numeric(12, 2)` arredondaria o preço em silêncio,
    # alterando o total. Os TOTAIS continuam a 2 casas (D-018).
    unit_price: Mapped[Decimal | None] = mapped_column(UNIT_PRICE, nullable=True)

    request: Mapped["MaterialRequest"] = relationship(back_populates="items")


class MaterialRequestHistory(UUIDPk, Base):
    """Auditoria append-only das transições de um pedido de material (D-067) —
    mesmo padrão de `ProjectHistory`/`TaskHistory`: sem `updated_at`, nunca
    editada nem apagada. Guarda quem fez cada passo (enviar, orçamento,
    aprovar, adjudicar, cancelar). `changed_at` é escrito em Python (resolução
    de microssegundos), não por `server_default`, para a ordem ser exata."""

    __tablename__ = "material_request_history"

    request_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("material_requests.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # create|send|record_quote|approve|adjudicate|cancel
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    note: Mapped[str] = mapped_column(Text, default="")
    changed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
