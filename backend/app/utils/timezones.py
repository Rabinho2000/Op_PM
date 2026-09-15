"""Ponto único de conversão de fuso horário — evita cada módulo calcular
"hoje"/"esta semana" à sua maneira (e divergir do servidor, que pode não
estar em Europe/Lisbon). Usado por `app/models/task.py` (tarefa atrasada),
`app/services/tasks.py`, `app/services/projects.py`, e
`app/services/dashboard.py` (ver requisito explícito: "A semana deve usar
o fuso horário Europe/Lisbon").

Sem dependência de nenhum outro módulo da app (nem `app.models`, nem
`app.services`) de propósito — importável de qualquer sítio, incluindo
`app/models/task.py`, sem risco de import circular.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

LISBON_TZ = ZoneInfo("Europe/Lisbon")


def today_lisbon() -> dt.date:
    return dt.datetime.now(LISBON_TZ).date()


def week_range_lisbon(reference: dt.date | None = None) -> tuple[dt.date, dt.date]:
    """Segunda a domingo (ISO) da semana que contém `reference`
    (por omissão, hoje em Europe/Lisbon) — devolve (início, fim), ambos
    incluídos."""
    day = reference if reference is not None else today_lisbon()
    start = day - dt.timedelta(days=day.weekday())
    end = start + dt.timedelta(days=6)
    return start, end
