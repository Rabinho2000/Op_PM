"""Preparação da demonstração local com dados sintéticos (D-051).

Dois subcomandos, ambos **só com `APP_ENV=local`** — recusam-se a correr
em `test`, `staging` ou `production`, antes de tocar na base de dados:

    python -m app.cli.demo setup
        Aplica as migrações (`alembic upgrade head`), o seed de
        desenvolvimento e os dados extra de demonstração. Idempotente —
        pode correr em cada arranque.

    python -m app.cli.demo reset --yes
        Apaga TODAS as tabelas da base de dados configurada
        (`alembic downgrade base`), volta a criá-las e semeia outra vez.
        Sem `--yes` só explica o que faria.

Nunca cria utilizadores reais, nunca liga integrações externas, nunca lê
ficheiros fora do repositório.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.migration.seed_demo import DemoSeedNotAllowedError, assert_demo_allowed_environment, seed_demo_data

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def _seed() -> bool:
    # Importados aqui (não no topo) para o guard de ambiente correr antes de
    # qualquer ligação à base de dados.
    from app.db import SessionLocal
    from app.migration.seed_dev import run_seed

    run_seed()
    db = SessionLocal()
    try:
        applied = seed_demo_data(db)
        db.commit()
    finally:
        db.close()
    return applied


def _print_ready() -> None:
    app_url = os.environ.get("DEMO_APP_URL", "http://localhost:5173")
    print()
    print("=" * 64)
    print(" Demonstração Op_PM pronta (dados 100% sintéticos)")
    print(f"   Aplicação: {app_url}")
    print("   Entrar como: chefe.sintetico@example.invalid (ou outro")
    print("   utilizador sintético listado no ecrã de login)")
    print("=" * 64)


def cmd_setup() -> None:
    command.upgrade(_alembic_config(), "head")
    applied = _seed()
    print("Dados de demonstração aplicados." if applied else "Dados de demonstração já existiam — nada a fazer.")
    _print_ready()


def cmd_reset(confirmed: bool) -> None:
    settings = get_settings()
    if not confirmed:
        print(
            "Isto apaga TODOS os dados da base de dados configurada "
            f"({make_url(settings.database_url).render_as_string(hide_password=True)}) e volta a semear os dados sintéticos.\n"
            "Repita com --yes para confirmar."
        )
        return
    cfg = _alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    _seed()
    print("Dados de demonstração reiniciados.")
    _print_ready()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli.demo", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="migrações + seed sintético (idempotente)")
    reset = sub.add_parser("reset", help="apaga e volta a semear a base de dados local")
    reset.add_argument("--yes", action="store_true", help="confirma a reposição dos dados")
    args = parser.parse_args(argv)

    try:
        assert_demo_allowed_environment(get_settings().app_env)
    except DemoSeedNotAllowedError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    if args.command == "setup":
        cmd_setup()
    else:
        cmd_reset(args.yes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
