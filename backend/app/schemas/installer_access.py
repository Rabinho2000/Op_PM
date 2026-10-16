from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


class InventoryScopedLocationRead(BaseModel):
    label: str


class InstallerInventoryRow(BaseModel):
    project_id: uuid.UUID
    project_name: str
    item_name: str
    unit: str
    required_quantity: Decimal = Decimal("0")
    reserved_quantity: Decimal = Decimal("0")
    consumed_quantity: Decimal = Decimal("0")
    delivered_quantity: Decimal = Decimal("0")
    locations: list[InventoryScopedLocationRead] = Field(default_factory=list)


class InstallerInventoryPage(BaseModel):
    items: list[InstallerInventoryRow]
    total: int
    offset: int
    limit: int
