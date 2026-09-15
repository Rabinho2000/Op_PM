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

Piloto (5 a 10 projetos antes dos 295 — ver docs/STAGING_RUNBOOK.md):
    python -m app.cli.ingest_staging --file export_real.json --dry-run
    python -m app.cli.ingest_staging --file export_real.json \\
        --only-ids id001,id002,id003 --actor-email admin@empresa.pt
"""
from __future__ import annotations

import argparse
import json
import subprocess
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


def assert_file_is_not_trackable_by_git(file_path: Path) -> None:
    """Segunda barreira (além da disciplina manual já documentada em
    `docs/DATA_MIGRATION_RUNBOOK.md`) contra um export com dados reais
    entrar neste repositório por engano: recusa-se a ler um ficheiro que
    esteja dentro da árvore de trabalho do Git e que o Git **não** ignore
    — ou seja, um ficheiro que `git add -A` apanharia. Um ficheiro fora do
    repositório (o caso recomendado — nem por perto do Git) passa sempre.

    Nunca falha "a fechado": qualquer erro inesperado (Git ausente, timeout,
    saída não reconhecida) deixa passar — o disparador real, `.gitignore` +
    revisão manual de `git status` antes de commitar, continua sempre ativo
    independentemente desta verificação. `encoding="utf-8"` explícito na
    leitura do `stdout` do Git é obrigatório aqui: sem isso, `subprocess`
    decodifica com `locale.getpreferredencoding()` (em Windows sem modo
    UTF-8 do sistema, tipicamente `cp1252`), corrompendo silenciosamente
    qualquer caminho com acentos (`é`→`Ã©`) — o `cwd` resultante deixava de
    corresponder a nenhuma pasta real e a chamada seguinte falhava."""
    try:
        resolved = file_path.resolve()
        toplevel = subprocess.run(
            ["git", "-C", str(resolved.parent), "rev-parse", "--show-toplevel"],
            capture_output=True,
            encoding="utf-8",
            timeout=5,
        )
        if toplevel.returncode != 0:
            return  # não está dentro de nenhum repositório Git — sempre seguro
        repo_root = Path(toplevel.stdout.strip())
        try:
            resolved.relative_to(repo_root)
        except ValueError:
            return  # fora deste repositório (pode estar dentro de outro) — sempre seguro

        check = subprocess.run(
            ["git", "-C", str(repo_root), "check-ignore", "-q", "--", str(resolved)],
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return
    if check.returncode == 0:
        return  # ignorado — seguro
    if check.returncode != 1:
        return  # 128 (erro do git) ou outro — inconclusivo, nunca bloquear por isto

    raise IngestionError(
        f"o ficheiro {resolved} está dentro do repositório Git e NÃO está coberto pelo "
        ".gitignore — um export com dados reais nunca deve poder ser 'git add'ado por "
        "engano. Mova o ficheiro para fora do repositório (recomendado) ou para um caminho "
        "já coberto pelo .gitignore (ex. dentro de backend/files/ ou backend/data/) antes "
        "de correr este comando."
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
    only_ids: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> tuple[ImportBatch, dict[str, int]]:
    """Núcleo do comando — chamado tanto por `main()` como pelos testes
    (`tests/test_ingest_staging_cli.py`), para nunca haver duas lógicas
    divergentes. Devolve o lote criado e o resumo de contagens
    (`summarize_import_batch`) para o chamador reportar/decidir.

    `only_ids` (string separada por vírgulas) e `limit` restringem o
    piloto a um subconjunto do payload (docs/STAGING_RUNBOOK.md). Quando
    `dry_run=True`, o chamador tem de fazer `db.rollback()` depois de usar
    o resumo devolvido — esta função nunca commita nesse caso, mas também
    nunca reverte sozinha, para o chamador poder decidir inspecionar o
    estado intermédio antes de descartar."""
    actor_person_id = _resolve_actor_person_id(db, actor_email)
    only_external_ids = (
        {part.strip() for part in only_ids.split(",") if part.strip()} if only_ids else None
    )
    batch = ingest_export(
        db,
        payload=payload,
        source_system=source_system,
        actor_person_id=actor_person_id,
        only_external_ids=only_external_ids,
        limit=limit,
        dry_run=dry_run,
    )
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
    parser.add_argument(
        "--only-ids",
        default=None,
        help="Lista de IDs externos (chaves do objeto 'projects' no export), separados por "
        "vírgula — processa só esses. Para o piloto de 5 a 10 projetos (docs/STAGING_RUNBOOK.md) "
        "antes dos 295.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Só processa os primeiros N projetos do ficheiro (ordem do JSON). Combinável com "
        "--only-ids (o limite aplica-se depois do filtro).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Não escreve nada, nem em staging — mostra o resumo (contagens/conflitos) e depois "
        "reverte a transação. Útil para pré-visualizar um piloto antes de o ingerir a sério.",
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
        assert_file_is_not_trackable_by_git(args.file)
    except IngestionError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    try:
        payload = json.loads(args.file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Erro: ficheiro não é JSON válido: {exc}", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        batch, summary = run_ingestion(
            db,
            payload=payload,
            source_system=args.source_system,
            actor_email=args.actor_email,
            only_ids=args.only_ids,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    except (IngestionError, ValueError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    finally:
        if args.dry_run:
            db.rollback()
        db.close()

    if args.dry_run:
        print(f"DRY-RUN: nada foi escrito (APP_ENV={settings.app_env!r}, source_system={args.source_system!r})")
        print("Resumo do que teria acontecido (revertido — nem em staging ficou nada):")
        for key, value in summary.items():
            print(f"  {key}: {value}")
        print("\nPara ingerir a sério, repita sem --dry-run.")
        return 0

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
