"""Carregar/ver o percurso de obra (D-052).

    python -m app.cli.workflow show
        Mostra as fases e etapas carregadas na base de dados configurada.

    python -m app.cli.workflow load --file <processo.json>
        Valida o ficheiro e mostra o que mudaria (simulação — nada é
        gravado).

    python -m app.cli.workflow load --file <processo.json> --apply
        Aplica a definição. Idempotente. Recusa remover etapas/subtarefas
        que já tenham progresso registado em algum projeto.

O processo oficial da empresa NÃO está no repositório (é público): fica num
ficheiro local, fora do Git (ex. `backend/data/processo_obra.json`, pasta
ignorada). O formato é o de `app/workflow/processo_exemplo.json` — ver
docs/WORKFLOW.md.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.workflow.definition import WorkflowDefinitionConflict, apply_definition, load_definition


def cmd_show() -> int:
    from app.db import SessionLocal
    from app.models.workflow import Phase, WorkflowStage, WorkflowSubtask

    db = SessionLocal()
    try:
        phases = {p.id: p for p in db.query(Phase).all()}
        stages = db.query(WorkflowStage).order_by(WorkflowStage.sort_order).all()
        if not stages:
            print("Nenhum percurso carregado.")
            return 0
        for stage in stages:
            subs = db.query(WorkflowSubtask).filter(WorkflowSubtask.stage_id == stage.id).count()
            print(
                f"{stage.sort_order:>2}. [{phases[stage.phase_id].name}] {stage.title} "
                f"— {stage.responsible_label or '-'} — dias {stage.planned_start_offset_days}–"
                f"{stage.planned_end_offset_days} — {subs} subtarefas"
            )
    finally:
        db.close()
    return 0


def cmd_load(path: Path, apply: bool) -> int:
    from app.db import SessionLocal

    try:
        definition = load_definition(path)
    except FileNotFoundError:
        print(f"Erro: ficheiro não encontrado: {path}", file=sys.stderr)
        return 1
    except (ValidationError, ValueError) as exc:
        print(f"Erro: definição inválida em {path}:\n{exc}", file=sys.stderr)
        return 1

    subtasks = sum(len(s.subtasks) for s in definition.stages)
    print(f"Definição: {definition.name or path.name}")
    print(f"  {len(definition.phases)} fases, {len(definition.stages)} etapas, {subtasks} subtarefas")
    url = make_url(get_settings().database_url).render_as_string(hide_password=True)
    print(f"Base de dados: {url}")

    db = SessionLocal()
    try:
        report = apply_definition(db, definition)
        for line in report.lines():
            print(f"  {line}")
        if not report.changed:
            print("Nada a alterar.")
            db.rollback()
            return 0
        if apply:
            db.commit()
            print("Percurso aplicado.")
        else:
            db.rollback()
            print("Simulação — nada foi gravado. Repita com --apply para aplicar.")
    except WorkflowDefinitionConflict as exc:
        db.rollback()
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli.workflow", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show", help="mostra o percurso carregado")
    load = sub.add_parser("load", help="valida e aplica uma definição de percurso")
    load.add_argument("--file", required=True, type=Path, help="ficheiro JSON com a definição")
    load.add_argument("--apply", action="store_true", help="grava as alterações (sem isto é só simulação)")
    args = parser.parse_args(argv)

    if args.command == "show":
        return cmd_show()
    return cmd_load(args.file, args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
