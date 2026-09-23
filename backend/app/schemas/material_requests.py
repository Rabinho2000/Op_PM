from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MaterialRequestLineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Um item do inventário OU uma descrição livre (ou ambos: a descrição prevalece).
    item_id: uuid.UUID | None = None
    description: str = ""
    quantity: Decimal


class MaterialRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: uuid.UUID
    supplier_id: uuid.UUID | None = None
    notes: str = ""
    lines: list[MaterialRequestLineCreate] = Field(min_length=1)


class MaterialRequestUpdate(BaseModel):
    """Só um rascunho é editável. Só os campos presentes são alterados."""

    model_config = ConfigDict(extra="forbid")

    supplier_id: uuid.UUID | None = None
    notes: str | None = None
    lines: list[MaterialRequestLineCreate] | None = Field(default=None, min_length=1)


class QuotePrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_id: uuid.UUID
    unit_price: Decimal


class MaterialRequestActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["send", "record_quote", "approve", "adjudicate", "cancel"]
    note: str = ""
    # Só em `record_quote`: o orçamento tem de cobrir todas as linhas.
    prices: list[QuotePrice] = []


class MaterialRequestLineRead(BaseModel):
    id: uuid.UUID
    item_id: uuid.UUID | None
    description: str
    quantity: Decimal
    unit: str | None = None
    unit_price: Decimal | None = None
    line_total: Decimal | None = None


class MaterialRequestHistoryRead(BaseModel):
    action: str
    from_status: str | None
    to_status: str
    changed_by_display_name: str | None = None
    note: str
    changed_at: dt.datetime


class MaterialRequestRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str | None = None
    supplier_id: uuid.UUID | None
    supplier_name: str | None = None
    status: str
    notes: str
    created_by_display_name: str | None = None
    approved_by_display_name: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime
    lines: list[MaterialRequestLineRead]
    # `null` enquanto houver linhas sem preço — nunca um total parcial.
    total: Decimal | None = None
    # Ações que o utilizador atual pode fazer agora (máquina de estados ∩
    # permissões ∩ âmbito): a UI só mostra estas.
    allowed_actions: list[str]
    # Só no detalhe (vazio na listagem).
    history: list[MaterialRequestHistoryRead] = []


class EmailDraftRead(BaseModel):
    """Rascunho do email ao fornecedor — para copiar. O sistema nunca o envia."""

    to: str | None
    subject: str
    body: str
