"""Schemas dos fornecedores (D-070). A validação vive aqui, uma só vez: as rotas
e o comando de carregamento inicial usam-nas."""
from __future__ import annotations

import re
import uuid
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
_PHONE_RE = re.compile(r"^\+?[\d\s().-]+$")


def _blank_to_none(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


OptionalText = Annotated[str | None, BeforeValidator(_blank_to_none)]


def _validate_email(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) > 320 or not _EMAIL_RE.match(value):
        raise ValueError("Email inválido.")
    return value


def _validate_phone(value: str | None) -> str | None:
    if value is None:
        return None
    digits = sum(c.isdigit() for c in value)
    if len(value) > 64 or not _PHONE_RE.match(value) or not 6 <= digits <= 15:
        raise ValueError("Telefone inválido: use só números, espaços, +, ( ) . e -, com 6 a 15 dígitos.")
    return value


def _validate_website(value: str | None) -> str | None:
    if value is None:
        return None
    if not re.match(r"^https?://", value, flags=re.IGNORECASE):
        value = f"https://{value}"
    if len(value) > 512 or " " in value or "." not in value:
        raise ValueError("Endereço do site inválido.")
    return value


class SupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: str | None
    contact: str | None
    phone: str | None
    email: str | None
    website: str | None
    address: str | None
    lat: float | None
    lon: float | None
    is_preferred: bool
    lead_time_days: int | None
    materials: str
    notes: str
    is_active: bool
    material_types: list[str] = []

    @field_validator("material_types", mode="before")
    @classmethod
    def _type_names(cls, value: object) -> object:
        return [getattr(t, "name", t) for t in value] if isinstance(value, (list, tuple)) else value


class SupplierMaterialTypeRead(BaseModel):
    id: uuid.UUID
    name: str
    active_suppliers: int


class SupplierBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: OptionalText = None
    contact: OptionalText = Field(default=None, max_length=256)
    phone: OptionalText = None
    email: OptionalText = None
    website: OptionalText = None
    address: OptionalText = Field(default=None, max_length=512)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    is_preferred: bool = False
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    materials: str = ""
    notes: str = ""
    material_types: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return _validate_email(value)

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        return _validate_phone(value)

    @field_validator("website")
    @classmethod
    def _website(cls, value: str | None) -> str | None:
        return _validate_website(value)

    @field_validator("material_types")
    @classmethod
    def _types(cls, value: list[str] | None) -> list[str] | None:
        if value and any(len(" ".join(t.split())) > 128 for t in value):
            raise ValueError("Cada tipo de material tem no máximo 128 caracteres.")
        return value


class SupplierCreate(SupplierBase):
    name: str = Field(min_length=1, max_length=256)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("O nome é obrigatório.")
        return value


class SupplierUpdate(SupplierBase):
    """Só os campos presentes são alterados; `null` limpa um campo opcional."""

    name: str | None = Field(default=None, max_length=256)
    is_active: bool | None = None
    is_preferred: bool | None = None  # type: ignore[assignment]
    materials: str | None = None  # type: ignore[assignment]
    notes: str | None = None  # type: ignore[assignment]
    material_types: list[str] | None = Field(default=None, max_length=30)  # type: ignore[assignment]

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("O nome não pode ficar vazio.")
        return value
