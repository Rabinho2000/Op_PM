"""Ordem da lista de projetos (D-077): por estado (ordem do fluxo) e, dentro de
cada um, cronológica por entrada no programa; desempate pela data de ligação."""
from __future__ import annotations

import datetime as dt

from app.models.project import Project

CHEFE = "chefe.sintetico@example.invalid"


def _day(d: str) -> dt.datetime:
    return dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc)


def test_list_is_grouped_by_state_then_chronological(db_session, api_client):
    rows = [
        # (nome, estado, entrada, ligação)
        ("Z construção antigo", "construcao", "2025-01-10", None),
        ("A construção novo", "construcao", "2026-03-01", None),
        ("M prep 1", "preparacao", "2025-06-01", "2026-05-01"),
        ("B prep 2 mesma entrada", "preparacao", "2025-06-01", "2026-02-01"),
        ("N on hold", "on_hold_cliente", "2026-08-01", None),
        ("S sem estado", None, "2024-01-01", None),
    ]
    for name, state, entered, conn in rows:
        db_session.add(Project(name=name, lifecycle_status=state, entered_at=_day(entered), upac_connection_date_raw=conn))
    db_session.commit()

    res = api_client.get("/api/projects", headers={"X-Dev-User-Email": CHEFE})
    assert res.status_code == 200
    ours = {r[0] for r in rows}
    # A base de teste já tem projetos: só interessa a ordem relativa dos nossos.
    assert [p["name"] for p in res.json() if p["name"] in ours] == [
        "N on hold",
        "B prep 2 mesma entrada",  # entrada igual → ligação mais antiga primeiro
        "M prep 1",
        "Z construção antigo",
        "A construção novo",
        "S sem estado",
    ]


def test_new_project_gets_entered_at(db_session):
    p = Project(name="Novo sintético")
    db_session.add(p)
    db_session.commit()
    assert p.entered_at is not None
