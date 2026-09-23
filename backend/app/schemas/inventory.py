from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class InventoryLocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    location_type: str
    project_id: uuid.UUID | None
    is_active: bool


class InventoryItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sku: str
    name: str
    unit: str
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


class InventoryMovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    movement_type: str
    quantity: Decimal
    project_id: uuid.UUID | None
    location_id: uuid.UUID | None
    destination_location_id: uuid.UUID | None
    unit_cost: Decimal | None
    reference: str
    idempotency_key: str | None
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
    quantity: Decimal
    reference: str = ""
    unit_cost: Decimal | None = None
    idempotency_key: str | None = None


class ProjectInventoryOperationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: uuid.UUID
    quantity: Decimal
    reference: str = ""
    idempotency_key: str | None = None


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
    quantity_required: Decimal
    notes: str = ""


class ProjectMaterialRequirementUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity_required: Decimal | None = None
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
