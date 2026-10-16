"""Leitura e serialização da BD privada de preços."""
from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.prices_db import CatalogDataset, MaterialPrice, PriceSource


_ALLOWED_DOMAINS = frozenset({"cabo", "terminal", "aparelho", "quadro", "inventario"})
_DATASET_NAMES = frozenset({"breakers", "indus", "hager"})


class MaterialPricesPermissionError(PermissionError):
    """The actor lacks a private-price capability."""


class MaterialPricesValidationError(ValueError):
    """A private-price filter or stored payload is invalid."""


class MaterialPricesStorageError(RuntimeError):
    """The private price database is unavailable or inconsistent."""


def require_price_view(ctx: Any) -> None:
    if not ctx.has_permission("price.view"):
        raise MaterialPricesPermissionError("Sem permissão para consultar preços de materiais.")


def require_price_manage(ctx: Any) -> None:
    if not ctx.has_permission("price.manage"):
        raise MaterialPricesPermissionError("Sem permissão para gerir preços de materiais.")


def _validate_filter(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    normalised = value.strip()
    if not normalised or len(normalised) > 128 or any(ord(char) < 0x20 for char in normalised):
        raise MaterialPricesValidationError(f"{field_name} inválido.")
    return normalised


def _decode_attrs(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise MaterialPricesStorageError("Atributos de preço persistidos inválidos.") from exc
    if not isinstance(decoded, dict):
        raise MaterialPricesStorageError("Atributos de preço persistidos inválidos.")
    return decoded


def _source_map(db: Session, rows: Iterable[MaterialPrice]) -> dict[str, PriceSource]:
    source_ids = {row.source_id for row in rows}
    if not source_ids:
        return {}
    return {source.id: source for source in db.scalars(select(PriceSource).where(PriceSource.id.in_(source_ids))).all()}


def _row_payload(row: MaterialPrice, source: PriceSource | None = None) -> dict[str, Any]:
    attrs = _decode_attrs(row.attrs_json)
    return {
        "id": row.id,
        "domain": row.domain,
        "ref": row.ref,
        "description": row.description,
        "unit": row.unit,
        "unit_price": row.unit_price,
        "source_id": row.source_id,
        "source_code": source.code if source is not None else None,
        "price_date": row.price_date,
        "attrs": attrs,
        "estimated": row.estimated,
        "is_active": row.is_active,
        "item_sku": row.item_sku,
        "created_at": row.created_at,
    }


def _ordered_rows(
    db: Session,
    *,
    domain: str | None,
    ref: str | None,
    current: bool,
) -> list[MaterialPrice]:
    statement = select(MaterialPrice)
    if domain is not None:
        statement = statement.where(MaterialPrice.domain == domain)
    if ref is not None:
        statement = statement.where(MaterialPrice.ref == ref)
    if current:
        statement = statement.where(MaterialPrice.is_active.is_(True))
    statement = statement.order_by(
        MaterialPrice.domain.asc(),
        MaterialPrice.ref.asc(),
        MaterialPrice.price_date.desc(),
        MaterialPrice.created_at.desc(),
        MaterialPrice.id.desc(),
    )
    rows = list(db.scalars(statement).all())
    if not current:
        return rows
    seen: set[tuple[str, str]] = set()
    selected: list[MaterialPrice] = []
    for row in rows:
        key = (row.domain, row.ref)
        if key in seen:
            continue
        seen.add(key)
        selected.append(row)
    return selected


def list_material_prices(
    db: Session,
    *,
    domain: str | None = None,
    ref: str | None = None,
    current: bool = True,
) -> list[dict[str, Any]]:
    domain = _validate_filter(domain, field_name="domain")
    ref = _validate_filter(ref, field_name="ref")
    if domain is not None and domain not in _ALLOWED_DOMAINS:
        raise MaterialPricesValidationError("domain inválido.")
    try:
        rows = _ordered_rows(db, domain=domain, ref=ref, current=current)
        sources = _source_map(db, rows)
        return [_row_payload(row, sources.get(row.source_id)) for row in rows]
    except MaterialPricesValidationError:
        raise
    except SQLAlchemyError as exc:
        raise MaterialPricesStorageError("Não foi possível consultar a BD de preços.") from exc


def _as_json_number(value: Decimal | int | float) -> int | float:
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    if decimal_value == decimal_value.to_integral_value():
        return int(decimal_value)
    return float(decimal_value)


def material_price_to_engine_row(row: dict[str, Any]) -> list[Any]:
    """Return the eight-column row consumed by the cable engine."""
    attrs = row["attrs"]
    explicit = attrs.get("engine_row")
    if isinstance(explicit, list) and len(explicit) == 8:
        return explicit
    return [
        attrs.get("material", row["domain"]),
        attrs.get("forma", row["unit"]),
        attrs.get("section_mm2", attrs.get("secção_mm2")),
        _as_json_number(row["unit_price"]),
        row["price_date"].isoformat() if isinstance(row["price_date"], dt.date) else str(row["price_date"]),
        row["ref"],
        row["description"],
        attrs.get("supplier", attrs.get("fornecedor", row.get("source_code") or "")),
    ]


def _decode_dataset(row: CatalogDataset) -> Any:
    try:
        value = json.loads(row.payload_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise MaterialPricesStorageError("Dataset de preços persistido inválido.") from exc
    return value


def _current_datasets(db: Session) -> dict[str, CatalogDataset]:
    rows = list(
        db.scalars(
            select(CatalogDataset)
            .where(CatalogDataset.is_current.is_(True))
            .order_by(CatalogDataset.name.asc(), CatalogDataset.loaded_at.desc(), CatalogDataset.id.desc())
        ).all()
    )
    result: dict[str, CatalogDataset] = {}
    for row in rows:
        if row.name in _DATASET_NAMES and row.name not in result:
            result[row.name] = row
    return result


def get_engine_data(db: Session) -> dict[str, Any]:
    """Build the browser-facing calculation snapshot from current private rows."""
    rows = list_material_prices(db, current=True)
    prices = [material_price_to_engine_row(row) for row in rows]
    datasets = _current_datasets(db)
    return {
        "prices": prices,
        "breakers": _decode_dataset(datasets["breakers"]) if "breakers" in datasets else {},
        "indus": _decode_dataset(datasets["indus"]) if "indus" in datasets else {},
        "versions": {
            name: datasets[name].content_sha256
            for name in sorted(datasets)
        },
    }
