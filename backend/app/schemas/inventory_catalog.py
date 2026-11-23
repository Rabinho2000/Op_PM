"""Schemas do catálogo de inventário e da entrada de stock inicial."""
from __future__ import annotations

import hashlib
import unicodedata
import uuid
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.inventory import (
    INVENTORY_CATEGORIES,
    INVENTORY_CATEGORY_KEY_MAX_LENGTH,
    INVENTORY_CATEGORY_NAME_MAX_LENGTH,
    LOCATION_TYPES,
)
from app.utils.text import alnum_casefold_key

# Rótulo do grupo "Outros" no frontend; reservado para não o confundir com a
# categoria incorporada "Outros".
RESERVED_UNASSIGNED_INVENTORY_CATEGORY = "Outros/Sem categoria"


class InventoryCategoryError(ValueError):
    """Erro base das regras do catálogo de categorias."""


class InventoryCategoryKeyTooLongError(InventoryCategoryError):
    """Nome cuja chave normalizada excede o limite persistível."""


def _clean_required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"O campo {field_name} tem de ser texto.")
    value = " ".join(value.split())
    if not value:
        raise ValueError(f"O campo {field_name} é obrigatório.")
    return value


def inventory_category_key(value: str) -> str:
    """Chave canónica partilhada pela API para categorias de inventário."""
    return alnum_casefold_key(value)


def inventory_category_key_for_read(value: str) -> str:
    """Chave de leitura sempre limitada e não vazia.

    Valores legados fora do limite do nome, com chave vazia (só pontuação) ou
    com chave expandida demasiado longa recebem uma identidade opaca
    (`!legacy:<sha256>`) que não colide com chaves normalizadas (só contêm
    letras/números).
    """
    if len(value) <= INVENTORY_CATEGORY_NAME_MAX_LENGTH:
        key = inventory_category_key(value)
        if key and len(key) <= INVENTORY_CATEGORY_KEY_MAX_LENGTH:
            return key
    digest = hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()
    return f"!legacy:{digest}"


def is_reserved_unassigned_inventory_category(value: object) -> bool:
    """Reconhece o rótulo reservado para o grupo incorporado ``Outros``."""
    return isinstance(value, str) and inventory_category_key_for_read(
        value
    ) == inventory_category_key(RESERVED_UNASSIGNED_INVENTORY_CATEGORY)


def inventory_category_slug(value: str) -> str:
    """Slug de URL derivado da mesma equivalência Unicode do backend."""
    safe_key = inventory_category_key_for_read(value)
    if safe_key.startswith("!legacy:"):
        return f"!legacy-slug:{safe_key.removeprefix('!legacy:')}"
    if safe_key == inventory_category_key("Outros"):
        return "outros-sem-categoria"
    if is_reserved_unassigned_inventory_category(value):
        # Separador duplo: identifica sem colisão a linha legada literal.
        return "outros-sem-categoria--legado"
    slug: list[str] = []
    for char in unicodedata.normalize("NFKD", value).casefold():
        if unicodedata.category(char).startswith("M"):
            continue
        if char.isalnum():
            slug.append(char)
        elif slug and slug[-1] != "-":
            slug.append("-")
    return "".join(slug).strip("-")


def normalize_inventory_category_name(value: object, *, required: bool = False) -> str | None:
    """Limpa espaços; valida tipo e presença. Não limita o tamanho (ver abaixo)."""
    if value is None:
        if required:
            raise ValueError("A categoria é obrigatória.")
        return None
    if not isinstance(value, str):
        raise ValueError("A categoria tem de ser texto.")
    cleaned = " ".join(value.split())
    if not cleaned:
        if required:
            raise ValueError("A categoria é obrigatória.")
        return None
    return cleaned


def validate_inventory_category_input(value: object, *, required: bool = False) -> str | None:
    """Valida uma entrada nova/alterada antes de consultar ou escrever no catálogo."""
    cleaned = normalize_inventory_category_name(value, required=required)
    if cleaned is None:
        return None
    if len(cleaned) > INVENTORY_CATEGORY_NAME_MAX_LENGTH:
        raise InventoryCategoryKeyTooLongError("A categoria excede o limite permitido.")
    key = inventory_category_key(cleaned)
    if not key:
        raise ValueError("A categoria tem de conter pelo menos uma letra ou número.")
    if len(key) > INVENTORY_CATEGORY_KEY_MAX_LENGTH:
        raise InventoryCategoryKeyTooLongError(
            "A categoria excede o limite após normalização Unicode."
        )
    return cleaned


_CATEGORY_BY_KEY = {inventory_category_key(category): category for category in INVENTORY_CATEGORIES}

# Valores legados frequentes aceites na entrada e agrupados no mesmo grupo
# canónico no frontend. A base de dados mantém os valores antigos até serem
# alterados explicitamente por um utilizador.
LEGACY_INVENTORY_CATEGORY_ALIASES: dict[str, str] = {
    "Cabo AC": "Cabos AC",
    "Cabo DC": "Cabos DC",
    "Painel": "Painéis",
    "Painéis solares": "Painéis",
    "Inversor": "Inversores",
    "Bateria": "Baterias",
    "Estrutura": "Estruturas",
    "Conector": "Conectores",
    "Consumível": "Consumíveis",
}
_ALIAS_CATEGORY_BY_KEY = {
    inventory_category_key(alias): canonical
    for alias, canonical in LEGACY_INVENTORY_CATEGORY_ALIASES.items()
}


def normalize_inventory_category(value: object) -> str | None:
    """Limpa o texto e resolve categorias de origem e aliases para o nome canónico.

    Não decide se uma categoria desconhecida existe: isso depende do catálogo
    na BD e é verificado em `app.services.inventory_categories`.
    """
    cleaned = normalize_inventory_category_name(value)
    if cleaned is None or len(cleaned) > INVENTORY_CATEGORY_NAME_MAX_LENGTH:
        return cleaned
    key = inventory_category_key_for_read(cleaned)
    return _CATEGORY_BY_KEY.get(key) or _ALIAS_CATEGORY_BY_KEY.get(key) or cleaned


def normalize_inventory_category_for_read(value: object) -> str | None:
    """Como `normalize_inventory_category`, para valores já gravados (nunca falha)."""
    if not isinstance(value, str):
        return None
    return normalize_inventory_category(value)


def _validate_category(value: str | None) -> str | None:
    return normalize_inventory_category(value)


class InventoryCategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=INVENTORY_CATEGORY_NAME_MAX_LENGTH)

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value: object) -> str:
        return normalize_inventory_category_name(value, required=True) or ""


class InventoryItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    unit: str = Field(default="un", min_length=1, max_length=16)
    category: str | None = Field(default=None, max_length=INVENTORY_CATEGORY_NAME_MAX_LENGTH)
    manufacturer: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=128)
    subcategory: str | None = Field(default=None, max_length=100)
    power_w: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)
    cross_section_mm2: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=3)
    min_stock: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=3)
    preferred_supplier_id: uuid.UUID | None = None
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)

    @field_validator("sku")
    @classmethod
    def _sku(cls, value: str) -> str:
        return _clean_required_text(value, "SKU").upper()

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_required_text(value, "nome")

    @field_validator("unit")
    @classmethod
    def _unit(cls, value: str) -> str:
        return _clean_required_text(value, "unidade").lower()

    @field_validator("category", mode="before")
    @classmethod
    def _category(cls, value: str | None) -> str | None:
        return _validate_category(value)

    @field_validator("manufacturer", "model", "subcategory", mode="before")
    @classmethod
    def _optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("O campo tem de ser texto.")
        cleaned = " ".join(value.split())
        return cleaned or None


class InventoryItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=256)
    unit: str | None = Field(default=None, max_length=16)
    category: str | None = Field(default=None, max_length=INVENTORY_CATEGORY_NAME_MAX_LENGTH)
    manufacturer: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=128)
    subcategory: str | None = Field(default=None, max_length=100)
    power_w: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)
    cross_section_mm2: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=3)
    min_stock: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)
    preferred_supplier_id: uuid.UUID | None = None
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    is_active: bool | None = None

    @field_validator("sku", mode="before")
    @classmethod
    def _sku(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("O campo SKU é obrigatório quando enviado.")
        return _clean_required_text(value, "SKU").upper()

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("O campo nome é obrigatório quando enviado.")
        return _clean_required_text(value, "nome")

    @field_validator("unit", mode="before")
    @classmethod
    def _unit(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("O campo unidade é obrigatório quando enviado.")
        return _clean_required_text(value, "unidade").lower()

    @field_validator("category", mode="before")
    @classmethod
    def _category(cls, value: str | None) -> str | None:
        # O serviço compara com a categoria persistida para permitir PATCHes
        # que apenas reenviam texto legado desconhecido sem o alterar.
        if value is not None and not isinstance(value, str):
            raise ValueError("A categoria tem de ser texto.")
        return value

    @field_validator("manufacturer", "model", "subcategory", mode="before")
    @classmethod
    def _optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("O campo tem de ser texto.")
        cleaned = " ".join(value.split())
        return cleaned or None

    @field_validator("min_stock", "is_active", mode="before")
    @classmethod
    def _non_nullable_patch_fields(cls, value: object) -> object:
        if value is None:
            raise ValueError("O campo não pode ser nulo quando enviado.")
        return value


class InventoryLocationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    location_type: str
    project_id: uuid.UUID | None = None
    owner: Literal["solcor", "verde_milenar"] = "solcor"

    @field_validator("code")
    @classmethod
    def _code(cls, value: str) -> str:
        return _clean_required_text(value, "código").upper()

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_required_text(value, "nome")

    @field_validator("location_type")
    @classmethod
    def _location_type(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in LOCATION_TYPES:
            raise ValueError("Tipo de localização inválido.")
        return value


class InventoryLocationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=256)
    location_type: str | None = None
    project_id: uuid.UUID | None = None
    owner: Literal["solcor", "verde_milenar"] | None = None
    is_active: bool | None = None

    @field_validator("code", mode="before")
    @classmethod
    def _code(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("O campo código é obrigatório quando enviado.")
        return _clean_required_text(value, "código").upper()

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("O campo nome é obrigatório quando enviado.")
        return _clean_required_text(value, "nome")

    @field_validator("location_type", mode="before")
    @classmethod
    def _location_type(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("O tipo de localização é obrigatório quando enviado.")
        if not isinstance(value, str):
            raise ValueError("O tipo de localização tem de ser texto.")
        value = value.strip().lower()
        if value not in LOCATION_TYPES:
            raise ValueError("Tipo de localização inválido.")
        return value

    @field_validator("is_active", mode="before")
    @classmethod
    def _is_active(cls, value: object) -> object:
        if value is None:
            raise ValueError("O campo ativo não pode ser nulo quando enviado.")
        return value


class OpeningStockCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    reference: str = Field(min_length=1, max_length=256)
    idempotency_key: str = Field(min_length=1, max_length=128)
    location_id: uuid.UUID | None = None

    @field_validator("reference", "idempotency_key")
    @classmethod
    def _text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("O campo não pode ficar vazio.")
        return value


class InventoryCatalogHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    action: str
    changes: dict[str, Any] = Field(default_factory=dict)
    changed_by_person_id: uuid.UUID | None
    changed_by_person_name: str | None = None
    changed_at: Any
