"""Importação controlada do Excel de licenciamento — comando
administrativo, nunca um endpoint HTTP casual (mesmo princípio de
`app.cli.ingest_staging`, D-026). Ver docs/DATA_IMPORTS.md.

Nunca commitar o ficheiro real — a segunda barreira já usada por
`app.cli.ingest_staging` (`assert_file_is_not_trackable_by_git`) também
se aplica aqui.

Utilização:
    python -m app.cli.import_licensing --file caminho.xlsx --dry-run
    python -m app.cli.import_licensing --file caminho.xlsx --apply
    python -m app.cli.import_licensing --rollback <batch_id>
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from app.cli.ingest_staging import _resolve_actor_person_id, assert_file_is_not_trackable_by_git
from app.db import SessionLocal
from app.models.imports import FieldImportBatch
from app.config import get_settings
from app.services.imports_licensing import (
    SIM_LAYOUT_NAME,
    DuplicateLicensingImportError,
    LicensingImportError,
    apply_licensing_import,
    apply_sim_import,
    detect_layout,
    dry_run_licensing_import,
    dry_run_sim_import,
    rollback_licensing_batch,
)


def _print_summary(summary, *, applied: bool) -> None:
    print(f"Projetos no ficheiro: {summary.total_projects}")
    print(f"  novos: {summary.new_projects}")
    print(f"  existentes/com conflitos: {summary.existing_projects}")
    print(f"  conflitos por resolver: {summary.total_conflicts}")
    print(f"Venda do excedente: {summary.surplus_contracts_linked} ligados, {summary.surplus_contracts_unlinked} sem projeto identificado")
    for sheet, columns in summary.ignored_columns.items():
        if columns:
            print(f"Colunas ignoradas em '{sheet}': {', '.join(columns)}")
    if applied and summary.batch_id:
        print(f"Lote: {summary.batch_id}")
        if summary.total_conflicts:
            print(
                "Alguns registos ficaram pendentes por terem conflitos — resolva-os via "
                f"POST /api/imports/conflicts/{{id}}/resolve e volte a correr --apply com o mesmo "
                "ficheiro (o hash garante que não duplica)."
            )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.import_licensing",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--file", type=Path, help="Caminho para o ficheiro .xlsx.")
    parser.add_argument("--actor-email", default=None, help="Email de um utilizador ativo já provisionado.")
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="(layout SIM) Caminho do relatório JSON. Não contém segredos, usernames nem emails.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Só analisa e reporta — nunca escreve na base de dados.")
    mode.add_argument("--apply", action="store_true", help="Aplica a importação (staging + escrita imediata dos registos sem conflitos).")
    mode.add_argument("--rollback", metavar="BATCH_ID", help="Reverte um lote já aplicado.")
    parser.add_argument(
        "--safe-only",
        action="store_true",
        help="(layout SIM) Exclui campos com warning/erro; usar com --dry-run ou --apply.",
    )
    return parser


def _run_sim_layout(args, db, content: bytes) -> int:
    """Layout "SIM card Numbers Projects" — ver docs/DATA_IMPORTS.md (2b)."""
    import json

    settings = get_settings()
    try:
        if args.dry_run:
            report = dry_run_sim_import(db, content=content, settings=settings, safe_only=args.safe_only)
            db.rollback()
            header = "=== Dry-run (layout SIM) — nada foi escrito na base de dados ==="
        else:
            try:
                actor_person_id = _resolve_actor_person_id(db, args.actor_email)
            except Exception as exc:  # noqa: BLE001
                print(f"ERRO: {exc}", file=sys.stderr)
                return 1
            report = apply_sim_import(
                db,
                filename=args.file.name,
                content=content,
                settings=settings,
                applied_by_person_id=actor_person_id,
                safe_only=args.safe_only,
            )
            header = "=== Importação aplicada (layout SIM) ==="
    except LicensingImportError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    data = report.to_dict()
    print(header)
    if args.safe_only:
        print("Modo safe-only: campos com warning/erro excluídos.")
        for item in data["exclusoes_safe_only"]:
            print(
                f"  Excluído: linha {item['linha']} | bloco {item['bloco']} | "
                f"campo {item['campo']} | motivo: {item['motivo']}"
            )
    print(f"Projetos encontrados: {data['projetos_encontrados']}")
    print(f"Projetos não encontrados: {len(data['projetos_nao_encontrados'])}")
    print(f"Projetos ambíguos: {len(data['projetos_ambiguos'])}")
    for block, counts in data["contagens"].items():
        if counts:
            summary = ", ".join(f"{k}={v}" for k, v in counts.items())
            print(f"  {block}: {summary}")
    print(f"Linhas inválidas: {len(data['linhas_invalidas'])}  |  conflitos: {len(data['conflitos'])}  |  avisos: {len(data['avisos'])}")
    if data["ja_importado"]:
        print(f"Este ficheiro já foi aplicado (lote {data['lote']}) — nada foi escrito.")
    if data["lote"] and not data["ja_importado"]:
        print(f"Lote: {data['lote']}")
    if args.report is not None:
        args.report.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Relatório: {args.report}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.safe_only and args.rollback:
        parser.error("--safe-only só pode ser usado com --dry-run ou --apply.")

    db = SessionLocal()
    try:
        if args.rollback:
            try:
                batch_id = uuid.UUID(args.rollback)
            except ValueError:
                print(f"ERRO: '{args.rollback}' não é um UUID válido.", file=sys.stderr)
                return 1
            batch = db.get(FieldImportBatch, batch_id)
            if batch is None:
                print(f"ERRO: lote {batch_id} não encontrado.", file=sys.stderr)
                return 1
            try:
                reverted = rollback_licensing_batch(db, batch=batch)
            except LicensingImportError as exc:
                print(f"ERRO: {exc}", file=sys.stderr)
                return 1
            print(f"Lote {batch_id} revertido — {reverted} campo(s) repostos ao valor anterior.")
            return 0

        if args.file is None:
            print("ERRO: --file é obrigatório com --dry-run/--apply.", file=sys.stderr)
            return 1
        if not args.file.exists():
            print(f"ERRO: ficheiro não encontrado: {args.file}", file=sys.stderr)
            return 1
        # Fixtures sintéticas (backend/fixtures/) são feitas para serem
        # commitadas — só um ficheiro fora dessa pasta passa pela barreira
        # anti-dados-reais (mesmo princípio de ingest_staging, mas essa
        # verificação pressupõe um export real que nunca deveria ser
        # commitado, o oposto de uma fixture).
        if args.file.resolve().parent.name != "fixtures":
            try:
                assert_file_is_not_trackable_by_git(args.file)
            except Exception as exc:  # noqa: BLE001 - mesmo padrão de ingest_staging: nunca falha "a fechado"
                print(f"ERRO: {exc}", file=sys.stderr)
                return 1

        content = args.file.read_bytes()

        try:
            layout = detect_layout(content)
        except LicensingImportError as exc:
            print(f"ERRO: {exc}", file=sys.stderr)
            return 1
        if layout == SIM_LAYOUT_NAME:
            return _run_sim_layout(args, db, content)

        if args.safe_only:
            print("ERRO: --safe-only só é suportado no layout SIM.", file=sys.stderr)
            return 1

        if args.report is not None:
            print("ERRO: --report só é suportado no layout SIM.", file=sys.stderr)
            return 1

        if args.dry_run:
            try:
                summary = dry_run_licensing_import(db, content=content)
            except LicensingImportError as exc:
                print(f"ERRO: {exc}", file=sys.stderr)
                return 1
            print("=== Dry-run — nada foi escrito na base de dados ===")
            _print_summary(summary, applied=False)
            db.rollback()
            return 0

        # --apply
        try:
            actor_person_id = _resolve_actor_person_id(db, args.actor_email)
        except Exception as exc:  # noqa: BLE001
            print(f"ERRO: {exc}", file=sys.stderr)
            return 1
        try:
            summary = apply_licensing_import(
                db, filename=args.file.name, content=content, applied_by_person_id=actor_person_id
            )
        except DuplicateLicensingImportError as exc:
            print(f"ERRO: {exc}", file=sys.stderr)
            return 1
        except LicensingImportError as exc:
            print(f"ERRO: {exc}", file=sys.stderr)
            return 1
        print("=== Importação aplicada ===")
        _print_summary(summary, applied=True)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
