"""Plano de deslocação (D-066): rota otimizada + o que há para fazer em cada
instalação. Só leitura; cada secção respeita a sua permissão e é `null` (nunca
lista vazia) quando o utilizador não a pode ver.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from decimal import Decimal

import pytest

from app.models.calendar import CalendarEvent
from app.models.identity import User
from app.models.inventory import InventoryItem
from app.models.map_ops import PickupPoint, ProjectIssue
from app.models.project import Project
from app.models.supplier import Supplier
from app.models.task import (
    STATUS_DONE,
    STATUS_TODO,
    TASK_CATEGORY_DOCUMENTATION,
    TASK_CATEGORY_FIELD,
    TASK_CATEGORY_MATERIAL,
    TASK_CATEGORY_WORKFLOW,
    Task,
)
from app.security.permissions import load_auth_context
from app.services.inventory import deliver_to_project
from app.services.route_optimization import RouteError
from app.services.trip_planning import plan_trip

LISBOA = (38.7223, -9.1393)
PORTO = (41.1579, -8.6291)
COIMBRA = (40.2033, -8.4103)
FARO = (37.0194, -7.9304)


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _project(db, name, lat, lon, pm_person_id=None) -> Project:
    project = Project(name=name, client_name="Cliente", lat=lat, lon=lon, pm_person_id=pm_person_id, is_active=True)
    db.add(project)
    db.flush()
    return project


def _ref(kind, entity) -> dict:
    return {"kind": kind, "id": str(entity.id)}


def _plan(api_client, stops, email="chefe.sintetico@example.invalid", round_trip=False):
    return api_client.post(
        "/api/map/trip-plan", json={"stops": stops, "round_trip": round_trip}, headers=_headers(email)
    )


def _item(db, name="Painel de teste", unit="un") -> InventoryItem:
    item = InventoryItem(sku=f"TRIP-{uuid.uuid4().hex[:8]}", name=name, unit=unit)
    db.add(item)
    db.flush()
    return item


def _restricted_ctx(db, *, remove: set[str]):
    """Nenhum perfil do catálogo tem `map.view` sem as outras permissões, por isso
    testa-se o serviço com um contexto a que se retiram permissões."""
    chefe = db.query(User).filter(User.email == "chefe.sintetico@example.invalid").one()
    full = load_auth_context(db, chefe)
    return dataclasses.replace(full, permission_codes=full.permission_codes - remove)


@pytest.fixture()
def scenario(db_session):
    """Missão: 2 instalações + 1 fornecedor + 1 ponto de recolha, com trabalho variado."""
    db = db_session
    lisboa = _project(db, "Missão — Lisboa", *LISBOA)
    porto = _project(db, "Missão — Porto", *PORTO)
    supplier = Supplier(name="Missão — fornecedor", lat=COIMBRA[0], lon=COIMBRA[1], materials="Cabos, conectores", is_active=True)
    pickup = PickupPoint(name="Missão — recolha", lat=FARO[0], lon=FARO[1], materials="", is_active=True)
    db.add_all([supplier, pickup])

    yesterday = dt.date.today() - dt.timedelta(days=1)
    db.add_all(
        [
            Task(project_id=porto.id, title="Medir telhado", category=TASK_CATEGORY_FIELD, status=STATUS_TODO, due_date=yesterday),
            Task(project_id=porto.id, title="Levar cabos", category=TASK_CATEGORY_MATERIAL, status=STATUS_TODO),
            # não contam: workflow, documentação e concluída
            Task(project_id=porto.id, title="Etapa de workflow", category=TASK_CATEGORY_WORKFLOW, status=STATUS_TODO),
            Task(project_id=porto.id, title="Fotos", category=TASK_CATEGORY_DOCUMENTATION, status=STATUS_TODO),
            Task(project_id=porto.id, title="Já feita", category=TASK_CATEGORY_FIELD, status=STATUS_DONE),
            ProjectIssue(project_id=porto.id, description="Acesso ao telhado bloqueado", category="obra", priority="high", status="aberta"),
            ProjectIssue(project_id=porto.id, description="Já resolvida", category="obra", priority="low", status="resolvida"),
            ProjectIssue(project_id=lisboa.id, description="Falta licença", category="documentacao", priority="medium", status="aberta"),
        ]
    )
    panel = _item(db, "Painel 450 W", "un")
    db.commit()
    deliver_to_project(db, item=panel, project_id=lisboa.id, quantity=Decimal("3"), created_by_person_id=None)
    db.add(
        CalendarEvent(
            project_id=porto.id,
            title="Visita técnica",
            starts_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=4),
            ends_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=4, hours=1),
            status="rascunho",
        )
    )
    db.commit()
    return {"lisboa": lisboa, "porto": porto, "supplier": supplier, "pickup": pickup, "panel": panel}


def _stops(s):
    return [_ref("project", s["lisboa"]), _ref("project", s["porto"]), _ref("supplier", s["supplier"]), _ref("pickup", s["pickup"])]


# --- Conteúdo ---


def test_plan_lists_the_work_of_each_installation(api_client, scenario):
    body = _plan(api_client, _stops(scenario)).json()
    by_name = {s["name"]: s for s in body["stops"]}

    porto = by_name["Missão — Porto"]["jobs"]
    # só tarefas operacionais (campo/material) abertas — não workflow, documentação nem concluídas
    assert sorted(t["title"] for t in porto["tasks"]) == ["Levar cabos", "Medir telhado"]
    assert next(t for t in porto["tasks"] if t["title"] == "Medir telhado")["is_overdue"] is True
    assert [i["description"] for i in porto["issues"]] == ["Acesso ao telhado bloqueado"]  # a resolvida não
    assert porto["collect"] == []  # nada no local (lista vazia = sabemos que não há)
    assert porto["next_visit"]["title"] == "Visita técnica"

    lisboa = by_name["Missão — Lisboa"]["jobs"]
    assert [i["description"] for i in lisboa["issues"]] == ["Falta licença"]
    assert [(c["item_name"], c["item_unit"], Decimal(c["quantity"])) for c in lisboa["collect"]] == [
        ("Painel 450 W", "un", Decimal("3"))
    ]
    assert lisboa["next_visit"] is None


def test_suppliers_and_pickups_are_stops_without_jobs(api_client, scenario):
    by_name = {s["name"]: s for s in _plan(api_client, _stops(scenario)).json()["stops"]}
    assert by_name["Missão — fornecedor"]["jobs"] is None
    assert by_name["Missão — fornecedor"]["info"] == "Cabos, conectores"
    assert by_name["Missão — recolha"]["jobs"] is None
    assert by_name["Missão — recolha"]["info"] is None  # materiais vazios não aparecem


def test_summary_totals(api_client, scenario):
    summary = _plan(api_client, _stops(scenario)).json()["summary"]
    assert summary == {
        "projects": 2,
        "suppliers": 1,
        "pickup_points": 1,
        "operational_tasks": 2,
        "overdue_tasks": 1,
        "issues": 2,
        "items_to_collect": 1,
    }


def test_route_is_identical_to_the_optimization_endpoint(api_client, scenario):
    """O plano e a otimização partilham o cálculo (compute_route): não podem divergir."""
    stops = _stops(scenario)
    plan = _plan(api_client, stops, round_trip=True).json()
    opt = api_client.post(
        "/api/map/optimize-route",
        json={"stops": stops, "round_trip": True},
        headers=_headers("chefe.sintetico@example.invalid"),
    ).json()
    assert [s["id"] for s in plan["stops"]] == [s["id"] for s in opt["stops"]]
    for key in ("total_km", "requested_order_km", "saved_km", "method", "return_leg_km", "round_trip"):
        assert plan[key] == opt[key]
    assert plan["stops"][0]["name"] == "Missão — Lisboa"  # a partida continua a ser a primeira


# --- Permissões: cada secção é null (nunca []) sem a sua permissão ---


@pytest.mark.parametrize(
    "removed, field, summary_field",
    [
        ({"task.view_all", "task.view_own"}, "tasks", "operational_tasks"),
        ({"project_issue.view"}, "issues", "issues"),
        ({"inventory.view"}, "collect", "items_to_collect"),
        ({"calendar.view"}, "next_visit", None),
    ],
)
def test_each_section_is_null_without_its_permission(db_session, scenario, removed, field, summary_field):
    ctx = _restricted_ctx(db_session, remove=removed)
    refs = [("project", scenario["lisboa"].id), ("project", scenario["porto"].id)]
    plan = plan_trip(db_session, ctx, refs, round_trip=False)

    for stop in plan.stops:
        assert getattr(stop.jobs, field) is None  # nunca [] — sem permissão não "sabemos que não há"
    if summary_field:
        assert getattr(plan.summary, summary_field) is None
    # as restantes secções continuam visíveis
    other = {"tasks", "issues", "collect"} - {field}
    for stop in plan.stops:
        for name in other:
            assert getattr(stop.jobs, name) is not None
    assert plan.summary.projects == 2  # contagens de paragens nunca são escondidas


def test_visibility_flags_reflect_the_permissions(db_session, scenario):
    ctx = _restricted_ctx(db_session, remove={"inventory.view", "calendar.view"})
    plan = plan_trip(db_session, ctx, [("project", scenario["lisboa"].id), ("project", scenario["porto"].id)], False)
    assert (plan.visibility.tasks, plan.visibility.issues, plan.visibility.material, plan.visibility.visits) == (
        True,
        True,
        False,
        False,
    )


# --- Âmbito e segurança ---


def test_pm_cannot_plan_through_a_project_outside_their_scope(db_session, api_client):
    db = db_session
    other = _project(db, "Alheio — plano", *LISBOA)  # sem PM: invisível ao PM
    supplier = Supplier(name="Alheio — fornecedor", lat=PORTO[0], lon=PORTO[1], is_active=True)
    db.add(supplier)
    db.commit()
    resp = _plan(api_client, [_ref("supplier", supplier), _ref("project", other)], email="pm.um.sintetico@example.invalid")
    assert resp.status_code == 400
    assert "Alheio" not in resp.json()["detail"]


def test_plan_reuses_the_route_validations(db_session, api_client):
    db = db_session
    ok = _project(db, "Val — ok", *LISBOA)
    no_coords = _project(db, "Val — sem coords", None, None)
    db.commit()
    resp = _plan(api_client, [_ref("project", ok), _ref("project", no_coords)])
    assert resp.status_code == 400 and "Val — sem coords" in resp.json()["detail"]
    assert _plan(api_client, [_ref("project", ok), _ref("project", ok)]).status_code == 400  # repetidas
    with pytest.raises(RouteError):
        plan_trip(db, _restricted_ctx(db, remove=set()), [("project", ok.id)], False)  # mínimo 2


def test_plan_rejects_client_supplied_coordinates_and_needs_auth(db_session, api_client):
    db = db_session
    a = _project(db, "Auth — A", *LISBOA)
    b = _project(db, "Auth — B", *PORTO)
    db.commit()
    resp = api_client.post(
        "/api/map/trip-plan",
        json={"stops": [{**_ref("project", a), "lat": 0.0, "lon": 0.0}, _ref("project", b)]},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 422
    assert api_client.post("/api/map/trip-plan", json={"stops": [_ref("project", a), _ref("project", b)]}).status_code == 401


def test_plan_writes_nothing(db_session, api_client, scenario):
    from app.models.calendar import CalendarEvent as Event
    from app.models.inventory import InventoryMovement

    db = db_session

    def counts():
        return (db.query(Task).count(), db.query(ProjectIssue).count(), db.query(Event).count(), db.query(InventoryMovement).count())

    before = counts()
    assert _plan(api_client, _stops(scenario)).status_code == 200
    assert counts() == before


# --- Desempenho: número de queries fixo ---


def test_query_count_does_not_grow_with_the_number_of_stops(db_session, api_client):
    from sqlalchemy import event

    from app.db import engine

    db = db_session
    item = _item(db)
    projects = []
    for i in range(12):
        p = _project(db, f"Vol — {i}", 38.0 + i * 0.3, -9.0 + i * 0.1)
        projects.append(p)
        db.add(Task(project_id=p.id, title=f"Tarefa {i}", category=TASK_CATEGORY_FIELD, status=STATUS_TODO))
        db.add(ProjectIssue(project_id=p.id, description=f"Pendência {i}", category="obra", priority="low", status="aberta"))
        db.add(
            CalendarEvent(
                project_id=p.id,
                title=f"Visita {i}",
                starts_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2 + i),
                ends_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2 + i, hours=1),
                status="rascunho",
            )
        )
    db.commit()
    for p in projects:
        deliver_to_project(db, item=item, project_id=p.id, quantity=Decimal("1"), created_by_person_id=None)

    # Os pedidos constroem-se ANTES de contar: ler `p.id` de instâncias expiradas
    # pelos commits acima dispararia um SELECT por projeto — ruído do teste, não
    # do endpoint (a pilha desse SELECT não passa por nenhum código de `app/`).
    refs = [_ref("project", p) for p in projects]

    def count(n_stops: int) -> int:
        counter = {"n": 0}

        def _on_execute(*_a, **_k):
            counter["n"] += 1

        event.listen(engine, "before_cursor_execute", _on_execute)
        try:
            resp = _plan(api_client, refs[:n_stops])
            assert resp.status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", _on_execute)
        return counter["n"]

    few, many = count(2), count(12)
    assert many <= few + 2, f"queries cresceram de {few} para {many} — provável N+1"
