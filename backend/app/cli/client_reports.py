"""CLI para execução agendada de relatórios semanais."""
from __future__ import annotations

import argparse
import datetime as dt
import time

from app.db import SessionLocal
from app.models.identity import User
from app.security.permissions import load_auth_context
from app.services.client_report_scheduler import run_due


def _context(db):
    user = db.query(User).filter(User.is_active.is_(True)).order_by(User.email).first()
    if user is None:
        raise RuntimeError("Não existe utilizador ativo para executar o scheduler.")
    return load_auth_context(db, user)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    due = sub.add_parser("run-due")
    due.add_argument("--now")
    due.add_argument("--dry-run", action="store_true")
    loop = sub.add_parser("loop")
    loop.add_argument("--interval", type=int, default=300)
    args = parser.parse_args(argv)

    while True:
        now = dt.datetime.fromisoformat(args.now) if getattr(args, "now", None) else dt.datetime.now(dt.timezone.utc)
        with SessionLocal() as db:
            if args.command == "run-due" and args.dry_run:
                from app.services.client_report_scheduler import due_configs
                rows = due_configs(db, now=now)
            else:
                rows = run_due(db, now=now, system_context=_context(db))
            print(f"processados={len(rows)}")
        if args.command != "loop":
            return 0
        time.sleep(max(1, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
