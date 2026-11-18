"""CLI do relatório semanal ao cliente.

    python -m app.cli.client_reports run-due [--now ISO] [--dry-run]
    python -m app.cli.client_reports loop [--interval 300]
    python -m app.cli.client_reports health [--max-age 900]

`loop` nunca morre por causa de uma exceção: regista-a, espera o intervalo e
tenta de novo. Depois de cada ciclo bem-sucedido escreve o heartbeat que o
subcomando `health` verifica (para o healthcheck do container).
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import time
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.logging_setup import configure_logging
from app.models.identity import User
from app.security.permissions import AuthContext, load_auth_context
from app.services.client_report_scheduler import due_configs, run_due, summarize
from app.services.client_reports import REPORT_MANAGE

logger = logging.getLogger("app.cli.client_reports")


class SchedulerIdentityError(RuntimeError):
    """Não há um utilizador de serviço válido para correr o scheduler."""


def _is_suitable(ctx: AuthContext) -> bool:
    return ctx.has_permission(REPORT_MANAGE) and (
        ctx.has_permission("project.view_all") or ctx.has_permission("project.edit_all")
    )


def resolve_system_context(db: Session, settings: Settings) -> AuthContext:
    """Contexto de autorização do scheduler: o utilizador de serviço configurado
    em CLIENT_REPORT_SCHEDULER_EMAIL ou, sem configuração, o primeiro utilizador
    ativo com client_report.manage e âmbito global. Nunca um utilizador qualquer."""
    email = settings.client_report_scheduler_email.strip()
    if email:
        user = (
            db.query(User)
            .filter(User.is_active.is_(True), func.lower(User.email) == email.lower())
            .one_or_none()
        )
        if user is None:
            raise SchedulerIdentityError("CLIENT_REPORT_SCHEDULER_EMAIL não corresponde a um utilizador ativo.")
        ctx = load_auth_context(db, user)
        if not _is_suitable(ctx):
            raise SchedulerIdentityError(
                "O utilizador de CLIENT_REPORT_SCHEDULER_EMAIL não tem client_report.manage e âmbito global."
            )
        return ctx
    for user in db.query(User).filter(User.is_active.is_(True)).order_by(User.email):
        ctx = load_auth_context(db, user)
        if _is_suitable(ctx):
            logger.warning(
                "CLIENT_REPORT_SCHEDULER_EMAIL não definido; o scheduler usa o utilizador id=%s. "
                "Configure um utilizador de serviço explícito.",
                user.id,
            )
            return ctx
    raise SchedulerIdentityError("Nenhum utilizador ativo com client_report.manage e âmbito global.")


def write_heartbeat(path: Path, now: dt.datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(now.isoformat(), encoding="utf-8")


def heartbeat_age(path: Path, now: dt.datetime) -> dt.timedelta | None:
    try:
        stamp = dt.datetime.fromisoformat(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return now - stamp


def run_once(*, now: dt.datetime, settings: Settings, dry_run: bool = False) -> dict[str, int]:
    with SessionLocal() as db:
        if dry_run:
            due = due_configs(db, now=now)
            logger.info("dry-run: %d relatório(s) devido(s)", len(due))
            return {"due": len(due)}
        results = run_due(db, now=now, system_context=resolve_system_context(db, settings))
    summary = summarize(results)
    if results:
        logger.info("Ciclo do scheduler concluído: %s", " ".join(f"{k}={v}" for k, v in summary.items()))
    return summary


def main(argv=None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    due = sub.add_parser("run-due")
    due.add_argument("--now")
    due.add_argument("--dry-run", action="store_true")
    loop = sub.add_parser("loop")
    loop.add_argument("--interval", type=int, default=300)
    health = sub.add_parser("health")
    health.add_argument("--max-age", type=int, default=900, help="segundos desde o último ciclo bem-sucedido")
    args = parser.parse_args(argv)
    settings = get_settings()
    heartbeat = settings.resolved_scheduler_heartbeat_file()

    if args.command == "health":
        age = heartbeat_age(heartbeat, dt.datetime.now(dt.timezone.utc))
        if age is None or age > dt.timedelta(seconds=args.max_age):
            print(f"unhealthy: último ciclo há {age}" if age is not None else "unhealthy: sem heartbeat")
            return 1
        print(f"ok: último ciclo há {int(age.total_seconds())}s")
        return 0

    if args.command == "run-due":
        now = dt.datetime.fromisoformat(args.now) if args.now else dt.datetime.now(dt.timezone.utc)
        summary = run_once(now=now, settings=settings, dry_run=args.dry_run)
        print(" ".join(f"{k}={v}" for k, v in summary.items()) or "nada a enviar")
        return 1 if summary.get("error") else 0

    interval = max(1, args.interval)
    logger.info("Scheduler do relatório semanal a arrancar (intervalo %ss)", interval)
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        try:
            run_once(now=now, settings=settings)
            write_heartbeat(heartbeat, now)
        except Exception:
            # Sem heartbeat novo: o healthcheck passa a falhar se isto persistir.
            logger.exception("Ciclo do scheduler falhou; nova tentativa daqui a %ss", interval)
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
