"""Carrega o catálogo do processo e, opcionalmente, as delegações de suporte, a
partir de JSON **fora do repositório** (D-073). O processo real da Solcor e os
nomes de quem delega em quem são internos: o comando recusa-se a ler um ficheiro
que o Git apanharia (`assert_file_is_not_trackable_by_git`).

Idempotente e sem apagar (ver `app/services/process_catalog.py`). As delegações,
quando indicadas, são **autoritativas**: ficam exatamente como no ficheiro.

Utilização:
    python -m app.cli.load_process --file processo.json --dry-run
    python -m app.cli.load_process --file processo.json --delegations delegacoes.json

Formato das delegações: {"delegations": [{"pm": "Nome do PM", "support": "Nome de quem apoia"}]}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.cli.ingest_staging import IngestionError, assert_file_is_not_trackable_by_git
from app.db import SessionLocal
from app.services.process_catalog import CatalogError, load_process_catalog, sync_support_delegations


def _read_json(path: Path) -> object:
    assert_file_is_not_trackable_by_git(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Carrega o processo (e as delegações) de JSON externo ao repositório.")
    parser.add_argument("--file", type=Path, required=True, help="JSON do processo (fases/etapas/subtarefas)")
    parser.add_argument("--delegations", type=Path, help="JSON com as delegações de suporte (opcional, autoritativo)")
    parser.add_argument("--dry-run", action="store_true", help="mostra o resumo sem gravar nada")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    for path in (args.file, args.delegations):
        if path is not None and not path.exists():
            print(f"Erro: ficheiro não encontrado: {path}", file=sys.stderr)
            return 1
    try:
        catalog = _read_json(args.file)
        delegations = _read_json(args.delegations) if args.delegations else None
    except IngestionError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"Erro: ficheiro não é JSON válido: {exc}", file=sys.stderr)
        return 1
    entries = None
    if delegations is not None:
        entries = delegations.get("delegations") if isinstance(delegations, dict) else None
        if not isinstance(entries, list):
            print("Erro: as delegações esperam um objeto com a chave 'delegations' (lista).", file=sys.stderr)
            return 1

    db = SessionLocal()
    try:
        try:
            summary = load_process_catalog(db, catalog)  # type: ignore[arg-type]
        except CatalogError as exc:
            db.rollback()
            print(f"Erro: catálogo inválido — {exc}", file=sys.stderr)
            return 1
        delegation_summary = sync_support_delegations(db, entries) if entries is not None else None
        problems = delegation_summary["invalid"] if delegation_summary else []
        if args.dry_run or problems:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()

    mode = "simulação (nada gravado)" if args.dry_run or problems else "gravado"
    print(
        f"Processo — {mode}: fases {summary['phases_created']} criadas/{summary['phases_updated']} atualizadas; "
        f"etapas {summary['stages_created']}/{summary['stages_updated']}; "
        f"subtarefas {summary['subtasks_created']}/{summary['subtasks_updated']}."
    )
    if delegation_summary is not None:
        print(
            f"Delegações: {delegation_summary['created']} criadas, {delegation_summary['updated']} atualizadas, "
            f"{delegation_summary['removed']} removidas, {delegation_summary['unchanged']} sem alterações, "
            f"{len(problems)} inválidas."
        )
        for problem in problems:
            print(f"  - {problem}")
        if problems:
            print("Nada foi gravado (nem o catálogo): corrija as delegações e volte a correr.", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
