from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Espelha `MOVEMENT_TYPES` (app/models/inventory.py); ver `tests/test_schema_literals.py`.
MovementType = Literal[
    "entrada",
    "saida",
    "reserva",
    "liberta_reserva",
    "consumo",
    "devolucao",
    "ajuste",
    "transito_entrada",
    "transito_saida",
    "entrega",
    "recolha",
]


class InventoryLocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    location_type: str
    project_id: uuid.UUID | None
    owner: Literal["solcor", "verde_milenar"]
    is_active: bool


class InventoryLocationStockRead(BaseModel):
    location_id: uuid.UUID | None
    location_name: str
    physical_stock: Decimal


class InventoryItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sku: str
    name: str
    unit: str
    category: str | None = None
    category_key: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    subcategory: str | None = None
    power_w: Decimal | None = None
    cross_section_mm2: Decimal | None = None
    section_label: str = "Geral"
    has_photo: bool = False
    min_stock: Decimal
    preferred_supplier_id: uuid.UUID | None
    lead_time_days: int | None
    is_active: bool

    # Derivados (ver app/services/inventory.py) — nunca calculados no
    # frontend, sempre no backend a partir do livro de movimentos.
    physical_stock: Decimal = Decimal("0")
    available_stock: Decimal = Decimal("0")
    total_reserved: Decimal = Decimal("0")
    below_min_stock: bool = False
    location_stocks: list[InventoryLocationStockRead] = Field(default_factory=list)


class InventoryItemDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    kind: Literal["datasheet", "manual", "guia", "outro"]
    title: str
    filename: str
    content_type: str
    size: int
    created_by_person_id: uuid.UUID | None
    created_at: dt.datetime


class InventoryCategoryImageRead(BaseModel):
    name: str
    category_key: str
    slug: str
    has_custom_image: bool
    image_version: str | None = None


class InventoryCategoryUnitStockRead(BaseModel):
    unit: str
    total_stock: Decimal


class InventoryCategorySummaryRead(BaseModel):
    category: str
    owner: Literal["solcor", "verde_milenar"]
    item_count: int
    stock_by_unit: list[InventoryCategoryUnitStockRead] = Field(default_factory=list)
    low_stock_count: int


class InventoryMovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    movement_type: MovementType
    quantity: Decimal
    project_id: uuid.UUID | None
    location_id: uuid.UUID | None
    destination_location_id: uuid.UUID | None
    unit_cost: Decimal | None
    reference: str
    idempotency_key: str | None
    reversal_of_movement_id: uuid.UUID | None
    created_by_person_id: uuid.UUID | None
    created_at: dt.datetime

    item_name: str | None = None
    project_name: str | None = None


class InventoryMovementCreate(BaseModel):
    """Corpo genérico de `POST /api/inventory/movements` — só cobre
    `entrada`/`ajuste` (stock central). Reserva/consumo/libertação vivem em
    `/api/projects/{id}/inventory/*`, que já têm o projeto no URL e a
    permissão de âmbito de projeto correspondente."""

    model_config = ConfigDict(extra="forbid")

    item_id: uuid.UUID
    movement_type: str
    quantity: Decimal = Field(max_digits=14, decimal_places=3)
    location_id: uuid.UUID | None = None
    destination_location_id: uuid.UUID | None = None
    reference: str = ""
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    idempotency_key: str | None = None


class ProjectInventoryOperationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    reference: str = ""
    idempotency_key: str | None = None
    owner: Literal["solcor", "verde_milenar"] = "solcor"


class ProjectInventoryMovementReverse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="Anulação manual", max_length=220)


class ProjectMaterialRequirementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    item_id: uuid.UUID
    quantity_required: Decimal
    notes: str
    source: str
    created_by_person_id: uuid.UUID | None
    created_at: dt.datetime
    updated_at: dt.datetime

    item_name: str | None = None
    item_unit: str | None = None
    reserved: Decimal = Decimal("0")
    consumed: Decimal = Decimal("0")
    missing: Decimal = Decimal("0")
    available_stock_sufficient: bool = True


class ProjectMaterialRequirementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: uuid.UUID
    quantity_required: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    notes: str = ""


class ProjectMaterialRequirementUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity_required: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=3)
    notes: str | None = None


class ProjectOnSiteRead(BaseModel):
    """Material fisicamente na instalação (D-064) — independente da reserva:
    inclui excedentes que não têm nenhuma "necessidade" associada."""

    item_id: uuid.UUID
    item_name: str | None = None
    item_unit: str | None = None
    quantity: Decimal


class ProjectInventorySummary(BaseModel):
    project_id: uuid.UUID
    requirements: list[ProjectMaterialRequirementRead]
    reservations: list[InventoryMovementRead]
    on_site: list[ProjectOnSiteRead] = []
