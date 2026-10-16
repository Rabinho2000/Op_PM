"""Loader privado de preços e datasets para o motor de cabos.

Uso::

    python -m app.cli.load_material_prices --dir ~/.hermes/private/op_pm_real/cable_design --dry-run
    python -m app.cli.load_material_prices --dir ~/.hermes/private/op_pm_real/cable_design

O parser de ``rt-indus.js`` só aceita o literal atribuído a ``INDUS`` através
de ``ast.literal_eval``. Nunca importa nem executa JavaScript.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import math
import re
import sys
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.prices_db import CatalogDataset, MaterialPrice, PriceImportBatch, PriceSource, open_prices_session, upgrade_prices_schema
from app.services.material_prices import MaterialPricesStorageError


_REQUIRED_FILES = ("prices.json", "brk.json", "hager.json", "rt-indus.js")
_MAX_TEXT_LENGTH = 512
_PRICE_QUANTUM = Decimal("0.0001")


class MaterialPricesLoadError(ValueError):
    """Input is absent, malformed, or violates the private loader contract."""


@dataclass(frozen=True)
class ParsedFile:
    name: str
    sha256: str
    price_rows: tuple[dict[str, Any], ...] = ()
    dataset: dict[str, Any] | None = None

    @property
    def row_count(self) -> int:
        return len(self.price_rows) + (1 if self.dataset is not None else 0)


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise MaterialPricesLoadError(f"não foi possível ler {path.name}.") from exc


def _read_text(path: Path) -> tuple[str, bytes, str]:
    raw = _read_bytes(path)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MaterialPricesLoadError(f"{path.name} não está em UTF-8 válido.") from exc
    return text, raw, hashlib.sha256(raw).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _text(value: Any, *, field: str, max_length: int = _MAX_TEXT_LENGTH) -> str:
    if not isinstance(value, str):
        raise MaterialPricesLoadError(f"campo {field} inválido.")
    value = value.strip()
    if not value or len(value) > max_length or any(ord(char) < 0x20 for char in value):
        raise MaterialPricesLoadError(f"campo {field} inválido.")
    return value


def _date(value: Any, *, field: str) -> dt.date:
    text = _text(value, field=field, max_length=32)
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        for pattern in ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%Y.%m.%d"):
            try:
                return dt.datetime.strptime(text, pattern).date()
            except ValueError:
                continue
        try:
            return dt.datetime.strptime(text, "%Y-%m").date().replace(day=1)
        except ValueError:
            pass
    raise MaterialPricesLoadError(f"campo {field} não é uma data válida.")


def _price(value: Any, *, field: str = "preço") -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise MaterialPricesLoadError(f"campo {field} inválido.")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MaterialPricesLoadError(f"campo {field} inválido.") from exc
    if not number.is_finite() or number < 0:
        raise MaterialPricesLoadError(f"campo {field} inválido.")
    try:
        rounded = number.quantize(_PRICE_QUANTUM, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise MaterialPricesLoadError(f"campo {field} inválido.") from exc
    if rounded.adjusted() > 9:
        raise MaterialPricesLoadError(f"campo {field} fora do limite.")
    return rounded


def _number_for_json(value: Any) -> int | float:
    decimal = Decimal(str(value))
    if decimal == decimal.to_integral_value():
        return int(decimal)
    return float(decimal)


def _source_code(supplier: str) -> str:
    folded = "".join(
        char for char in unicodedata.normalize("NFKD", supplier.casefold()) if not unicodedata.combining(char)
    )
    slug = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")
    return f"purchase:{slug or 'prices-json'}"[:128]


def _parse_json(path: Path) -> tuple[Any, str]:
    text, _raw, sha256 = _read_text(path)
    try:
        return json.loads(text), sha256
    except json.JSONDecodeError as exc:
        raise MaterialPricesLoadError(f"{path.name} não é JSON válido.") from exc


def _parse_prices(path: Path) -> ParsedFile:
    payload, sha256 = _parse_json(path)
    if not isinstance(payload, list):
        raise MaterialPricesLoadError("prices.json tem de ser uma lista.")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, dt.date]] = set()
    for number, raw in enumerate(payload, start=1):
        if not isinstance(raw, list) or len(raw) != 8:
            raise MaterialPricesLoadError(f"prices.json: linha {number} tem formato inválido.")
        material = _text(raw[0], field="material")
        forma = _text(raw[1], field="forma", max_length=64)
        section = raw[2]
        if isinstance(section, bool) or not isinstance(section, (int, float, str, Decimal)):
            raise MaterialPricesLoadError(f"prices.json: linha {number} tem secção inválida.")
        try:
            section_decimal = Decimal(str(section))
        except (InvalidOperation, ValueError) as exc:
            raise MaterialPricesLoadError(f"prices.json: linha {number} tem secção inválida.") from exc
        if not section_decimal.is_finite() or section_decimal <= 0:
            raise MaterialPricesLoadError(f"prices.json: linha {number} tem secção inválida.")
        unit_price = _price(raw[3], field="preço")
        price_date = _date(raw[4], field="data")
        ref = _text(raw[5], field="referência", max_length=128)
        description = _text(raw[6], field="designação")
        supplier = _text(raw[7], field="fornecedor")
        domain = "terminal" if forma.casefold() == "term" else "cabo"
        key = (domain, ref, price_date)
        if key in seen:
            raise MaterialPricesLoadError(f"prices.json: linha {number} duplica uma referência/data.")
        seen.add(key)
        section_value = _number_for_json(section_decimal)
        engine_row = [
            material,
            forma,
            section_value,
            _number_for_json(unit_price),
            price_date.isoformat(),
            ref,
            description,
            supplier,
        ]
        rows.append(
            {
                "domain": domain,
                "ref": ref,
                "description": description,
                "unit": "un" if domain == "terminal" else "m",
                "unit_price": unit_price,
                "price_date": price_date,
                "attrs": {
                    "material": material,
                    "forma": forma,
                    "section_mm2": section_value,
                    "supplier": supplier,
                    "engine_row": engine_row,
                },
                "estimated": False,
                "is_active": True,
                "item_sku": ref,
                "source": {"code": _source_code(supplier), "name": supplier, "kind": "compra"},
            }
        )
    return ParsedFile(name=path.name, sha256=sha256, price_rows=tuple(rows))


def _strip_js_comments(source: str) -> str:
    result: list[str] = []
    index = 0
    quote: str | None = None
    escaped = False
    while index < len(source):
        char = source[index]
        if quote is not None:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in ('"', "'", "`"):
            quote = char
            result.append(char)
            index += 1
        elif source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = len(source) if newline == -1 else newline
        elif source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end == -1:
                raise MaterialPricesLoadError("rt-indus.js contém um comentário não terminado.")
            index = end + 2
        else:
            result.append(char)
            index += 1
    if quote == "`":
        raise MaterialPricesLoadError("rt-indus.js contém uma string não suportada.")
    return "".join(result)


def _extract_object(source: str, start: int) -> str:
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(start, len(source)):
        char = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ('"', "'"):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise MaterialPricesLoadError("rt-indus.js não contém um objeto INDUS completo.")


def parse_indus_source(path: Path) -> dict[str, list[Any]]:
    """Extract and validate the literal assigned to ``INDUS`` safely."""
    source, _raw, _sha256 = _read_text(path)
    source = _strip_js_comments(source)
    assignment = re.search(r"\b(?:(?:const|let|var)\s+)?INDUS\s*=\s*", source)
    if assignment is None:
        raise MaterialPricesLoadError("rt-indus.js não contém a atribuição INDUS esperada.")
    object_start = source.find("{", assignment.end())
    if object_start == -1:
        raise MaterialPricesLoadError("rt-indus.js não contém o objeto INDUS esperado.")
    object_text = _extract_object(source, object_start)
    try:
        value = ast.literal_eval(object_text)
    except (SyntaxError, ValueError, TypeError, MemoryError) as exc:
        raise MaterialPricesLoadError("o objeto INDUS não é um literal seguro suportado.") from exc
    if not isinstance(value, dict) or not value:
        raise MaterialPricesLoadError("o objeto INDUS tem de ser um mapa não vazio.")
    parsed: dict[str, list[Any]] = {}
    for raw_ref, raw_value in value.items():
        ref = _text(raw_ref, field="referência INDUS", max_length=128)
        if not isinstance(raw_value, (list, tuple)) or len(raw_value) != 3:
            raise MaterialPricesLoadError("uma entrada INDUS tem de ter três campos.")
        description = _text(raw_value[0], field="descrição INDUS")
        price = _price(raw_value[1], field="preço INDUS")
        price_date = _date(raw_value[2], field="data INDUS")
        parsed[ref] = [description, _number_for_json(price), price_date.isoformat()]
    return parsed


def _indus_domain(ref: str, description: str) -> str:
    haystack = f"{ref} {description}".casefold()
    board_words = ("quadro", "envolvente", "armário", "armario", "caixa", "montagem", "univers", "board")
    return "quadro" if any(word in haystack for word in board_words) else "aparelho"


def _parse_dataset(path: Path, *, name: str) -> ParsedFile:
    payload, sha256 = _parse_json(path)
    if not isinstance(payload, dict) or not payload:
        raise MaterialPricesLoadError(f"{path.name} tem de ser um objeto JSON não vazio.")
    return ParsedFile(
        name=path.name,
        sha256=sha256,
        dataset={
            "name": name,
            "version": str(payload.get("version") or sha256[:16]),
            "content_sha256": sha256,
            "payload_json": _canonical_json(payload),
        },
    )


def _parse_indus(path: Path) -> ParsedFile:
    _source, raw, sha256 = _read_text(path)
    del raw
    payload = parse_indus_source(path)
    rows: list[dict[str, Any]] = []
    for ref, (description, price, date_text) in payload.items():
        price_date = _date(date_text, field="data INDUS")
        domain = _indus_domain(ref, description)
        rows.append(
            {
                "domain": domain,
                "ref": ref,
                "description": description,
                "unit": "un",
                "unit_price": _price(price, field="preço INDUS"),
                "price_date": price_date,
                "attrs": {
                    "catalog": "indus",
                    "engine_row": [
                        domain,
                        "indus",
                        None,
                        _number_for_json(price),
                        price_date.isoformat(),
                        ref,
                        description,
                        "indus",
                    ],
                },
                "estimated": True,
                "is_active": True,
                "item_sku": ref,
                "source": {"code": "catalog:indus", "name": "indus", "kind": "catalogo"},
            }
        )
    return ParsedFile(
        name=path.name,
        sha256=sha256,
        price_rows=tuple(rows),
        dataset={
            "name": "indus",
            "version": sha256[:16],
            "content_sha256": sha256,
            "payload_json": _canonical_json(payload),
        },
    )


def parse_directory(directory: Path) -> tuple[ParsedFile, ...]:
    directory = directory.expanduser()
    if not directory.is_dir():
        raise MaterialPricesLoadError("a pasta de entrada não existe.")
    paths = {name: directory / name for name in _REQUIRED_FILES}
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise MaterialPricesLoadError("faltam ficheiros de entrada obrigatórios.")
    return (
        _parse_prices(paths["prices.json"]),
        _parse_dataset(paths["brk.json"], name="breakers"),
        _parse_dataset(paths["hager.json"], name="hager"),
        _parse_indus(paths["rt-indus.js"]),
    )


def _get_or_create_source(db: Session, source_data: dict[str, str]) -> PriceSource:
    source = db.scalar(select(PriceSource).where(PriceSource.code == source_data["code"]))
    if source is None:
        source = PriceSource(**source_data)
        db.add(source)
        db.flush()
    return source


def _apply_file(db: Session, parsed: ParsedFile, *, actor: str) -> int:
    existing = db.scalar(select(PriceImportBatch).where(PriceImportBatch.source_file_sha256 == parsed.sha256))
    if existing is not None:
        return 0
    inserted = 0
    if parsed.dataset is not None:
        dataset = parsed.dataset
        db.execute(
            update(CatalogDataset)
            .where(CatalogDataset.name == dataset["name"], CatalogDataset.is_current.is_(True))
            .values(is_current=False)
        )
        db.add(CatalogDataset(**dataset, is_current=True))
        inserted = 1
    source_cache: dict[str, PriceSource] = {}
    for row in parsed.price_rows:
        source_data = row["source"]
        source = source_cache.get(source_data["code"])
        if source is None:
            source = _get_or_create_source(db, source_data)
            source_cache[source.code] = source
        db.add(
            MaterialPrice(
                domain=row["domain"],
                ref=row["ref"],
                description=row["description"],
                unit=row["unit"],
                unit_price=row["unit_price"],
                source_id=source.id,
                price_date=row["price_date"],
                attrs_json=_canonical_json(row["attrs"]),
                estimated=row["estimated"],
                is_active=row["is_active"],
                item_sku=row["item_sku"],
            )
        )
        inserted += 1
    db.flush()
    db.add(
        PriceImportBatch(
            source_file_sha256=parsed.sha256,
            rows_inserted=inserted,
            rows_skipped=0,
            actor=actor,
        )
    )
    db.flush()
    return inserted


def _empty_summary(*, dry_run: bool) -> dict[str, Any]:
    return {
        "dry_run": dry_run,
        "files": 0,
        "prices": {"cabo": 0, "terminal": 0, "aparelho": 0, "quadro": 0, "inventario": 0},
        "datasets": {"breakers": 0, "indus": 0, "hager": 0},
        "inserted": 0,
        "skipped": 0,
        "already_loaded": 0,
        "conflicts": 0,
    }


def load_directory(
    directory: Path,
    *,
    dry_run: bool = False,
    db: Session | None = None,
    actor: str = "cli",
) -> dict[str, Any]:
    parsed_files = parse_directory(directory)
    summary = _empty_summary(dry_run=dry_run)
    summary["files"] = len(parsed_files)
    for parsed in parsed_files:
        if parsed.dataset is not None:
            summary["datasets"][parsed.dataset["name"]] += 1
        for row in parsed.price_rows:
            summary["prices"][row["domain"]] += 1
    owns_session = db is None
    session = db or open_prices_session(read_only=dry_run)
    try:
        for parsed in parsed_files:
            already = session.scalar(select(PriceImportBatch).where(PriceImportBatch.source_file_sha256 == parsed.sha256))
            if already is not None:
                summary["already_loaded"] += 1
                summary["skipped"] += parsed.row_count
        if dry_run:
            session.rollback()
            return summary
        try:
            for parsed in parsed_files:
                summary["inserted"] += _apply_file(session, parsed, actor=actor)
                if session.scalar(select(PriceImportBatch).where(PriceImportBatch.source_file_sha256 == parsed.sha256)) is not None:
                    # A batch found above is already represented by skipped;
                    # this branch counts only newly inserted rows in _apply_file.
                    pass
            session.commit()
        except Exception:
            session.rollback()
            raise
        return summary
    except MaterialPricesLoadError:
        raise
    except SQLAlchemyError as exc:
        raise MaterialPricesStorageError("não foi possível gravar a BD privada de preços.") from exc
    finally:
        if owns_session:
            session.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Carrega a BD privada de preços de materiais.")
    parser.add_argument("--dir", type=Path, required=True, help="pasta privada com os quatro ficheiros de entrada")
    parser.add_argument("--dry-run", action="store_true", help="valida e mostra contagens sem gravar preços")
    return parser


def _print_summary(summary: dict[str, Any]) -> None:
    mode = "simulação" if summary["dry_run"] else "gravado"
    print(f"Preços de materiais — {mode}.")
    for domain in ("cabo", "terminal", "aparelho", "quadro", "inventario"):
        print(f"  preços {domain}: {summary['prices'][domain]}")
    for dataset in ("breakers", "indus", "hager"):
        print(f"  dataset {dataset}: {summary['datasets'][dataset]}")
    print(f"  ficheiros: {summary['files']}")
    print(f"  inseridos: {summary['inserted']}")
    print(f"  já carregados: {summary['already_loaded']}")
    print(f"  saltados: {summary['skipped']}")
    print(f"  conflitos: {summary['conflicts']}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        summary = load_directory(args.dir, dry_run=args.dry_run)
    except (MaterialPricesLoadError, MaterialPricesStorageError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
