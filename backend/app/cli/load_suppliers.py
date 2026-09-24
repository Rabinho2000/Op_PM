"""Carregamento inicial de fornecedores a partir de um ficheiro JSON **fora do
repositório** (D-070). A lista de fornecedores é informação comercial da
Solcor: nunca entra no Git — o comando recusa-se a ler um ficheiro que o Git
apanharia (`assert_file_is_not_trackable_by_git`, o mesmo de `ingest_staging`).

Idempotente, pelo nome (sem maiúsculas nem acentos):
- fornecedor novo → criado;
- fornecedor existente → só se **preenchem campos vazios** e se acrescentam os
  tipos de material em falta. Nunca sobrescreve o que alguém editou na app, nem
  reativa um fornecedor desativado.

Formato: `{"suppliers": [{"name": ..., "material_types": [...], "phone": ...,
"email": ..., "address": ..., "website": ..., "notes": ...}, ...]}`. Cada
entrada passa pela mesma validação da API; uma entrada inválida é reportada e
saltada, sem impedir as outras.

Utilização:
    python -m app.cli.load_suppliers --file caminho/fornecedores.json --dry-run
    python -m app.cli.load_suppliers --file caminho/fornecedores.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.cli.ingest_staging import IngestionError, assert_file_is_not_trackable_by_git
from app.db import SessionLocal
from app.models.supplier import Supplier
from app.schemas.suppliers import SupplierCreate
from app.services import suppliers as service

_ALLOWED_KEYS = set(SupplierCreate.model_fields)
# Campos de texto/opcionais que se preenchem num fornecedor existente se estiverem vazios.
_FILLABLE = ("contact", "phone", "email", "website", "address", "category", "notes", "materials")


def load_suppliers(db: Session, entries: list[dict]) -> dict:
    """Aplica as entradas e devolve o resumo. Não faz commit: quem chama decide
    (para permitir `--dry-run`)."""
    summary = {"created": 0, "updated": 0, "unchanged": 0, "invalid": []}
    for index, raw in enumerate(entries, start=1):
        label = str(raw.get("name") or f"entrada {index}") if isinstance(raw, dict) else f"entrada {index}"
        if not isinstance(raw, dict):
            summary["invalid"].append(f"{label}: não é um objeto")
            continue
        try:
            data = SupplierCreate.model_validate({k: v for k, v in raw.items() if k in _ALLOWED_KEYS})
        except ValidationError as exc:
            reasons = "; ".join(e["msg"].removeprefix("Value error, ") for e in exc.errors())
            summary["invalid"].append(f"{label}: {reasons}")
            continue

        payload = data.model_dump()
        existing = service.find_supplier_by_name(db, data.name)
        if existing is None:
            types = payload.pop("material_types")
            supplier = Supplier(**payload)
            supplier.material_types = service.get_or_create_material_types(db, types)
            db.add(supplier)
            db.flush()
            summary["created"] += 1
            continue

        changed = False
        for field_name in _FILLABLE:
            current = getattr(existing, field_name)
            if (current is None or current == "") and payload.get(field_name):
                setattr(existing, field_name, payload[field_name])
                changed = True
        have = {t.name_key for t in existing.material_types}
        missing = [t for t in service.get_or_create_material_types(db, payload["material_types"]) if t.name_key not in have]
        if missing:
            existing.material_types = [*existing.material_types, *missing]
            changed = True
        if changed:
            db.flush()
            summary["updated"] += 1
        else:
            summary["unchanged"] += 1
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Carrega fornecedores de um JSON externo ao repositório.")
    parser.add_argument("--file", type=Path, required=True, help="JSON com {'suppliers': [...]}")
    parser.add_argument("--dry-run", action="store_true", help="mostra o resumo sem gravar nada")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.file.exists():
        print(f"Erro: ficheiro não encontrado: {args.file}", file=sys.stderr)
        return 1
    try:
        assert_file_is_not_trackable_by_git(args.file)
    except IngestionError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    try:
        payload = json.loads(args.file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Erro: ficheiro não é JSON válido: {exc}", file=sys.stderr)
        return 1
    entries = payload.get("suppliers") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        print("Erro: esperado um objeto com a chave 'suppliers' (lista).", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        summary = load_suppliers(db, entries)
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()

    mode = "simulação (nada gravado)" if args.dry_run else "gravado"
    print(
        f"Fornecedores — {mode}: {summary['created']} criados, {summary['updated']} atualizados, "
        f"{summary['unchanged']} sem alterações, {len(summary['invalid'])} inválidos."
    )
    for problem in summary["invalid"]:
        print(f"  - {problem}")
    return 0 if not summary["invalid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
