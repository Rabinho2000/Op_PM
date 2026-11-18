"""Configuração única de logging para a API e as CLIs.

Formato `chave=valor` legível em `docker logs`, sempre para stderr. O nível vem
de `LOG_LEVEL` (INFO por omissão). Idempotente: chamar várias vezes (import da
app + CLI) não duplica handlers. Nunca registar tokens, passwords ou corpos de
pedidos — só identificadores (project_id, send_id, user_id).
"""
from __future__ import annotations

import logging
import os
import sys

_HANDLER_NAME = "op_pm_default"


def configure_logging(level: str | None = None) -> None:
    root = logging.getLogger()
    if any(getattr(handler, "name", None) == _HANDLER_NAME for handler in root.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(
        logging.Formatter("ts=%(asctime)s level=%(levelname)s logger=%(name)s msg=%(message)s")
    )
    root.addHandler(handler)
    root.setLevel((level or os.environ.get("LOG_LEVEL") or "INFO").upper())
