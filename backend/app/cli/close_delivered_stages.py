"""Conclui, por regra, as etapas do processo dos projetos **entregues ao cliente** (D-075):
só falta a inspeção final e o certificado (`etapa-18`), por isso o resto do que aparece
por fazer é falta de registo. Ver `app/services/process_rules.py` para as garantias
(nunca sobrescreve, só projetos entregues, idempotente, origem `inferred`).

Comando administrativo (como os outros de migração): recusa `APP_ENV=production`.

Utilização:
    python -m app.cli.close_delivered_stages --dry-run
    python -m app.cli.close_delivered_stages [--actor-email admin@empresa.pt] [--except-stage etapa-18 …]
"""
from __future__ import annotations

import argparse
import sys

from app.cli.ingest_staging import IngestionError, _resolve_actor_person_id, assert_staging_only_environment
from app.config import get_settings
from app.db import SessionLocal
from app.services.process_rules import DEFAULT_EXCEPT_STAGES, RuleError, complete_delivered_projects


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Conclui por regra as etapas dos projetos entregues ao cliente.")
    parser.add_argument("--actor-email", help="utilizador ativo a registar no histórico (opcional)")
    parser.add_argument(
        "--except-stage",
        action="append",
        dest="except_stages",
        help=f"etapa que continua por fazer (repetível; por omissão {', '.join(DEFAULT_EXCEPT_STAGES)})",
    )
    parser.add_argument("--dry-run", action="store_true", help="mostra o resumo sem gravar nada")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        assert_staging_only_environment(get_settings().app_env)
    except IngestionError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    db = SessionLocal()
    try:
        try:
            actor = _resolve_actor_person_id(db, args.actor_email)
            summary = complete_delivered_projects(
                db, except_stage_codes=tuple(args.except_stages or DEFAULT_EXCEPT_STAGES), actor_person_id=actor
            )
        except (IngestionError, RuleError) as exc:
            db.rollback()
            print(f"Erro: {exc}", file=sys.stderr)
            return 1
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()
    mode = "simulação (nada gravado)" if args.dry_run else "gravado"
    print(f"Etapas dos projetos entregues — {mode}:")
    print(f"  projetos entregues: {summary['projects']} · alterados: {summary['projects_changed']}")
    print(f"  subtarefas concluídas: {summary['subtasks_marked']} · contactos concluídos: {summary['contacts_marked']}")
    print(f"  por fazer (excecionadas): {', '.join(summary['excepted_stages'])}")
    if summary["kept_unmarked_in_app"]:
        print(f"  mantidas por fazer porque foram desmarcadas na aplicação: {summary['kept_unmarked_in_app']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
