"""Visitas futuras no mapa operacional (`next_visit`/`upcoming_visits_count`)
— ver app/services/map.py e docs/DECISIONS.md D-062. Só eventos de calendário
do projeto, não cancelados e com início no futuro; visíveis só com
`calendar.view`; nunca alteram `attention`.
"""
from __future__ import annotations

import datetime as dt

from app.models.calendar import CalendarEvent
from app.models.people import Person
from app.models.project import Project


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _project(db, name: str) -> Project:
    project = Project(name=name, client_name="Cliente de visitas", lat=5.0, lon=5.0, is_active=True)
    db.add(project)
    db.flush()
    return project


def _event(db, project, title, *, days: float, status="rascunho", assignee=None) -> CalendarEvent:
    start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)
    event = CalendarEvent(
        project_id=project.id,
        title=title,
        starts_at=start,
        ends_at=start + dt.timedelta(hours=1),
        status=status,
        assigned_to_person_id=assignee.id if assignee else None,
    )
    db.add(event)
    return event


def _entry(api_client, project, email="chefe.sintetico@example.invalid") -> dict:
    body = api_client.get("/api/map/data", headers=_headers(email)).json()
    for entry in body["projects"] + body["projects_without_coordinates"]:
        if entry["id"] == str(project.id):
            return entry
    raise AssertionError("projeto ausente do payload do mapa")


def test_next_visit_is_the_earliest_future_one_and_count_is_exact(db_session, api_client):
    db = db_session
    project = _project(db, "Visitas — várias")
    pm = db.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    _event(db, project, "Mais tarde", days=10)
    _event(db, project, "Mais cedo", days=2, assignee=pm)
    _event(db, project, "Meio", days=5)
    db.commit()

    entry = _entry(api_client, project)
    assert entry["visits_visible"] is True
    assert entry["upcoming_visits_count"] == 3
    assert entry["next_visit"]["title"] == "Mais cedo"
    assert entry["next_visit"]["assigned_to_display_name"] == "PM Sintético Um"


def test_past_and_cancelled_visits_are_ignored(db_session, api_client):
    db = db_session
    project = _project(db, "Visitas — passadas e canceladas")
    _event(db, project, "Já passou", days=-3)
    _event(db, project, "Cancelada", days=2, status="cancelado")
    db.commit()

    entry = _entry(api_client, project)
    assert entry["upcoming_visits_count"] == 0
    assert entry["next_visit"] is None


def test_visits_hidden_without_calendar_view_are_null_not_zero(db_session):
    """Nenhum perfil do catálogo tem map.view sem calendar.view, por isso o
    serviço é testado com um contexto sem essa permissão (dataclasse imutável
    -> dataclasses.replace)."""
    import dataclasses

    from app.models.identity import User
    from app.security.permissions import load_auth_context
    from app.services.map import get_map_projects

    db = db_session
    project = _project(db, "Visitas — sem permissão")
    _event(db, project, "Visita futura", days=3)
    db.commit()

    chefe = db.query(User).filter(User.email == "chefe.sintetico@example.invalid").one()
    full = load_auth_context(db, chefe)
    assert full.has_permission("calendar.view")
    restricted = dataclasses.replace(full, permission_codes=full.permission_codes - {"calendar.view"})

    with_coords, _ = get_map_projects(db, restricted)
    entry = next(e for e in with_coords if e.project.id == project.id)
    assert entry.visits_visible is False
    assert entry.upcoming_visits_count is None  # nunca 0 — sem permissão não "sabemos que não há"
    assert entry.next_visit is None

    with_coords_full, _ = get_map_projects(db, full)
    assert next(e for e in with_coords_full if e.project.id == project.id).upcoming_visits_count == 1


def test_visits_never_change_attention(db_session, api_client):
    db = db_session
    project = _project(db, "Visitas — attention")
    _event(db, project, "Visita futura", days=1)
    db.commit()
    assert _entry(api_client, project)["attention"] == "green"


def test_visits_of_projects_outside_scope_do_not_leak(db_session, api_client):
    db = db_session
    other = _project(db, "Visitas — projeto de outro PM")  # sem PM: invisível ao PM
    _event(db, other, "Visita alheia", days=1)
    db.commit()
    body = api_client.get("/api/map/data", headers=_headers("pm.um.sintetico@example.invalid")).json()
    ids = {p["id"] for p in body["projects"] + body["projects_without_coordinates"]}
    assert str(other.id) not in ids
