"""Carregamento de instaladores e equipas a partir de um JSON **fora do
repositório** (D-071). Os nomes dos chefes de equipa são dados pessoais de
pessoas externas à Solcor: nunca entram no Git — o comando recusa-se a ler um
ficheiro que o Git apanharia (`assert_file_is_not_trackable_by_git`).

Idempotente, pelo nome (sem maiúsculas nem acentos):
- instalador/equipa novos → criados;
- existentes → só se preenchem campos vazios (chefe, telefone). Nunca
  sobrescreve o que alguém editou na app, nem reativa o que foi desativado.

Formato:
    {"installers": [{"name": "Instalador A", "teams": [
        {"name": "Equipa 1", "leader_name": "…", "leader_phone": "+351 …"}, …]}]}

Utilização:
    python -m app.cli.load_installers --file caminho/instaladores.json --dry-run
    python -m app.cli.load_installers --file caminho/instaladores.json
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
from app.models.installer import InstallerTeam
from app.schemas.installers import InstallerCreate, TeamCreate
from app.services import installers as service
from app.utils.text import normalize_key


def load_installers(db: Session, entries: list) -> dict:
    """Aplica as entradas e devolve o resumo. Não faz commit (permite `--dry-run`)."""
    summary = {
        "installers_created": 0,
        "teams_created": 0,
        "teams_updated": 0,
        "unchanged": 0,
        "invalid": [],
    }
    for index, raw in enumerate(entries, start=1):
        label = str(raw.get("name") or f"entrada {index}") if isinstance(raw, dict) else f"entrada {index}"
        if not isinstance(raw, dict):
            summary["invalid"].append(f"{label}: não é um objeto")
            continue
        try:
            installer_data = InstallerCreate.model_validate({"name": raw.get("name", "")})
        except ValidationError as exc:
            summary["invalid"].append(f"{label}: " + "; ".join(e["msg"].removeprefix("Value error, ") for e in exc.errors()))
            continue

        installer = service.find_installer_by_name(db, installer_data.name)
        created_installer = installer is None
        if created_installer:
            installer = service.get_or_create_installer(db, installer_data.name)
            summary["installers_created"] += 1

        touched = created_installer
        for team_raw in raw.get("teams") or []:
            team_label = f"{label} / {team_raw.get('name', '?') if isinstance(team_raw, dict) else '?'}"
            try:
                team_data = TeamCreate.model_validate(team_raw)
            except ValidationError as exc:
                summary["invalid"].append(
                    f"{team_label}: " + "; ".join(e["msg"].removeprefix("Value error, ") for e in exc.errors())
                )
                continue
            team = service.find_team_by_name(db, installer.id, team_data.name)
            if team is None:
                db.add(
                    InstallerTeam(
                        installer_id=installer.id,
                        name=team_data.name,
                        name_key=normalize_key(team_data.name),
                        leader_name=team_data.leader_name,
                        leader_phone=team_data.leader_phone,
                    )
                )
                summary["teams_created"] += 1
                touched = True
                continue
            changed = False
            for field_name in ("leader_name", "leader_phone"):
                if not getattr(team, field_name) and getattr(team_data, field_name):
                    setattr(team, field_name, getattr(team_data, field_name))
                    changed = True
            if changed:
                summary["teams_updated"] += 1
                touched = True
        db.flush()
        if not touched:
            summary["unchanged"] += 1
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Carrega instaladores e equipas de um JSON externo ao repositório.")
    parser.add_argument("--file", type=Path, required=True, help="JSON com {'installers': [...]}")
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
    entries = payload.get("installers") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        print("Erro: esperado um objeto com a chave 'installers' (lista).", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        summary = load_installers(db, entries)
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()

    mode = "simulação (nada gravado)" if args.dry_run else "gravado"
    print(
        f"Instaladores — {mode}: {summary['installers_created']} instaladores e {summary['teams_created']} equipas criados, "
        f"{summary['teams_updated']} equipas atualizadas, {summary['unchanged']} sem alterações, "
        f"{len(summary['invalid'])} inválidos."
    )
    for problem in summary["invalid"]:
        print(f"  - {problem}")
    return 0 if not summary["invalid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
