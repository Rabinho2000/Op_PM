"""Ingestão controlada de um export externo para staging — comando
administrativo, nunca um endpoint HTTP (D-026 já deixava isso
deliberadamente fora da API — ver `app/api/routes_migration.py`, cujo
docstring explica porquê).

**Modo staging-only (D-037):** recusa-se a correr com `APP_ENV=production`
— a migração real dos 295 projetos passa sempre primeiro por 'staging'
para revisão manual (docs/DATA_MIGRATION_RUNBOOK.md, docs/PLAN.md Fase 2),
nunca diretamente para produção por este caminho. Correr contra
`local`/`test` (fixtures sintéticas, para ensaiar o fluxo end-to-end) ou
`staging` (export real, sempre seguido de revisão humana da fila de
conflitos) é permitido.

Nunca escreve em `projects` — só em `import_batches`/
`staging_project_records`, via `app.migration.staging.ingest_export`. A
promoção continua sempre um passo humano explícito e separado (API
`POST /api/migration/staging-records/{id}/promote`, ou
`promote_staging_record` diretamente) — este comando nunca promove nada
sozinho.

Utilização:
    python -m app.cli.ingest_staging \\
        --file caminho/para/export.json \\
        --actor-email admin@empresa.pt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.migration.staging import ImportBatch, ingest_export, summarize_import_batch
from app.models.identity import User

PRODUCTION_ENV = "production"


class IngestionError(ValueError):
    """Erro de negócio conhecido — mensagem sempre segura para mostrar
    diretamente a quem corre o comando."""


def assert_staging_only_environment(app_env: str) -> None:
    """Barreira do modo staging-only: nunca `production`. Separada de
    `main()` para ser testável sem depender do cache de `get_settings()`."""
    if app_env == PRODUCTION_ENV:
        raise IngestionError(
            f"ingestão recusada em APP_ENV={app_env!r} (modo staging-only) — a migração real "
            "passa sempre primeiro por 'staging' para revisão manual, nunca diretamente para "
            "produção por este comando (ver docs/DATA_MIGRATION_RUNBOOK.md)."
        )


def _resolve_actor_person_id(db: Session, actor_email: str | None):
    """`None` é aceitável (ingestão sem autor registado) — mas um email
    fornecido tem de corresponder a um `User` ativo já existente; nunca
    inventa nem ignora silenciosamente um email desconhecido."""
    if not actor_email:
        return None
    user = db.query(User).filter(User.email == actor_email, User.is_active.is_(True)).one_or_none()
    if user is None:
        raise IngestionError(
            f"nenhum utilizador ATIVO com email {actor_email!r} — usar o email de um utilizador já "
            "provisionado, ou omitir --actor-email para uma ingestão sem autor registado."
        )
    return user.person_id


def run_ingestion(
    db: Session,
    *,
    payload: dict,
    source_system: str,
    actor_email: str | None,
) -> tuple[ImportBatch, dict[str, int]]:
    """Núcleo do comando — chamado tanto por `main()` como pelos testes
    (`tests/test_ingest_staging_cli.py`), para nunca haver duas lógicas
    divergentes. Devolve o lote criado e o resumo de contagens
    (`summarize_import_batch`) para o chamador reportar/decidir."""
    actor_person_id = _resolve_actor_person_id(db, actor_email)
    batch = ingest_export(db, payload=payload, source_system=source_system, actor_person_id=actor_person_id)
    summary = summarize_import_batch(db, batch)
    return batch, summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.ingest_staging",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--file", required=True, type=Path, help="Caminho para o ficheiro JSON do export.")
    parser.add_argument(
        "--source-system", default="legacy_json", help="Identificador da origem (omissão: 'legacy_json')."
    )
    parser.add_argument(
        "--actor-email",
        default=None,
        help="Email de um User já existente e ativo — opcional, gravado em "
        "ImportBatch.started_by_person_id para auditoria.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = get_settings()

    try:
        assert_staging_only_environment(settings.app_env)
    except IngestionError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    if not args.file.exists():
        print(f"Erro: ficheiro não encontrado: {args.file}", file=sys.stderr)
        return 1
    try:
        payload = json.loads(args.file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Erro: ficheiro não é JSON válido: {exc}", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        batch, summary = run_ingestion(
            db, payload=payload, source_system=args.source_system, actor_email=args.actor_email
        )
    except (IngestionError, ValueError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    print(f"OK: import_batch_id={batch.id} (APP_ENV={settings.app_env!r}, source_system={args.source_system!r})")
    print("Resumo (nunca inclui dados de 'projects' — só do lote de staging):")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print(
        "\nNunca escreveu em 'projects'. Reveja a fila de conflitos antes de promover nada:\n"
        f"  GET /api/migration/import-batches/{batch.id}/records?status=conflict"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
