"""Importa o progresso do processo (subtarefas e contactos feitos) do export do legado
(D-074). Comando administrativo, nunca um endpoint HTTP. É informação de clientes reais:
recusa-se a ler um ficheiro que o Git apanharia, e (como `ingest_staging`) recusa
`APP_ENV=production` — a migração real passa primeiro por staging.

Pré-requisitos: os projetos já promovidos (`ingest_staging` + promoção) e o catálogo do
processo carregado (`load_process`). Idempotente; nunca sobrescreve progresso existente.

Utilização:
    python -m app.cli.import_legacy_progress --file export.json --dry-run
    python -m app.cli.import_legacy_progress --file export.json [--actor-email admin@empresa.pt]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.cli.ingest_staging import (
    IngestionError,
    _resolve_actor_person_id,
    assert_file_is_not_trackable_by_git,
    assert_staging_only_environment,
)
from app.config import get_settings
from app.db import SessionLocal
from app.models.workflow import WorkflowSubtask
from app.services.legacy_progress import import_legacy_progress


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Importa o progresso do processo do export do legado.")
    parser.add_argument("--file", type=Path, required=True, help="export JSON do legado")
    parser.add_argument("--actor-email", help="utilizador ativo a registar no histórico (opcional)")
    parser.add_argument("--dry-run", action="store_true", help="mostra o resumo sem gravar nada")
    return parser


def _print(summary: dict, dry_run: bool) -> None:
    mode = "simulação (nada gravado)" if dry_run else "gravado"
    print(f"Progresso do legado — {mode}:")
    print(f"  projetos no export: {summary['projects_seen']} · encontrados: {summary['projects_matched']} · "
          f"não encontrados: {summary['projects_not_found_count']}")
    print(f"  subtarefas: {summary['subtasks_created']} criadas, {summary['subtasks_kept']} já existiam")
    print(f"  contactos: {summary['contacts_created']} criados, {summary['contacts_kept']} já existiam")
    print(f"  ignorados: {summary['false_ignored']} valores falsos · {summary['commissioned_ignored']} datas de "
          f"comissionamento · {summary['shift_ignored']} projetos com deslocamento de etapas")
    if summary["unmapped_count"]:
        print(f"  ATENÇÃO: {summary['unmapped_count']} chaves sem correspondência no catálogo:")
        for item in summary["unmapped"]:
            print(f"    - {item}")
    if summary["projects_not_found_count"]:
        print(f"  ATENÇÃO: projetos por encontrar (primeiros {len(summary['projects_not_found'])}): "
              + ", ".join(summary["projects_not_found"]))


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        assert_staging_only_environment(get_settings().app_env)
    except IngestionError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    if not args.file.exists():
        print(f"Erro: ficheiro não encontrado: {args.file}", file=sys.stderr)
        return 1
    try:
        assert_file_is_not_trackable_by_git(args.file)
        payload = json.loads(args.file.read_text(encoding="utf-8"))
    except IngestionError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"Erro: ficheiro não é JSON válido: {exc}", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        if db.query(WorkflowSubtask).count() == 0:
            print("Erro: o catálogo do processo não está carregado (correr `app.cli.load_process` primeiro).", file=sys.stderr)
            return 1
        try:
            actor = _resolve_actor_person_id(db, args.actor_email)
            summary = import_legacy_progress(db, payload, actor_person_id=actor)
        except (IngestionError, ValueError) as exc:
            db.rollback()
            print(f"Erro: {exc}", file=sys.stderr)
            return 1
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()
    _print(summary, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
