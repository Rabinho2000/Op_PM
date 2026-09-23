"""Otimização da ordem de paragens (D-065): algoritmo (contra força bruta),
resolução segura das paragens no servidor, e o endpoint. Distâncias em linha
reta (haversine), sem serviços externos.
"""
from __future__ import annotations

import itertools
import random
import uuid

import pytest

from app.models.map_ops import PickupPoint
from app.models.project import Project
from app.models.supplier import Supplier
from app.services.route_optimization import (
    EXACT_LIMIT,
    MAX_STOPS,
    RouteError,
    haversine_km,
    optimize_order,
    route_length_km,
)

LISBOA = (38.7223, -9.1393)
PORTO = (41.1579, -8.6291)
FARO = (37.0194, -7.9304)
COIMBRA = (40.2033, -8.4103)


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _random_points(rng: random.Random, n: int) -> list[tuple[float, float]]:
    return [(rng.uniform(37.0, 42.0), rng.uniform(-9.5, -6.5)) for _ in range(n)]


def _brute_force_best(points, round_trip: bool) -> float:
    """Menor comprimento entre TODAS as permutações com a paragem 0 fixa."""
    return min(
        route_length_km(points, [0, *perm], round_trip) for perm in itertools.permutations(range(1, len(points)))
    )


# --- haversine ---


def test_haversine_known_distance_and_symmetry():
    assert 270 < haversine_km(LISBOA, PORTO) < 280  # ~274 km em linha reta
    assert haversine_km(LISBOA, PORTO) == pytest.approx(haversine_km(PORTO, LISBOA))
    assert haversine_km(LISBOA, LISBOA) == 0.0


# --- algoritmo ---


@pytest.mark.parametrize("round_trip", [False, True])
@pytest.mark.parametrize("n", [2, 3, 4, 5, 6, 7])
def test_exact_result_matches_brute_force(n, round_trip):
    rng = random.Random(1000 + n)
    for _ in range(15):  # 15 conjuntos aleatórios por combinação, semente fixa
        points = _random_points(rng, n)
        order, method = optimize_order(points, round_trip)
        assert method == "exact"
        assert route_length_km(points, order, round_trip) == pytest.approx(
            _brute_force_best(points, round_trip), abs=1e-6
        )


def test_start_is_fixed_and_every_stop_is_visited_exactly_once():
    rng = random.Random(7)
    for n in (2, 5, 9, EXACT_LIMIT, EXACT_LIMIT + 1, 20):
        points = _random_points(rng, n)
        order, _ = optimize_order(points, round_trip=False)
        assert order[0] == 0
        assert sorted(order) == list(range(n))


def test_is_deterministic_for_the_same_input():
    points = _random_points(random.Random(42), 10)
    assert optimize_order(points, True) == optimize_order(points, True)
    big = _random_points(random.Random(43), 20)
    assert optimize_order(big, False) == optimize_order(big, False)


def test_reorders_a_zigzag_into_a_line():
    # Pedido em ziguezague Lisboa -> Porto -> Faro -> Coimbra: a ordem otimizada
    # tem de ser mais curta e igual ao ótimo por força bruta.
    points = [LISBOA, PORTO, FARO, COIMBRA]
    order, _ = optimize_order(points, round_trip=False)
    assert route_length_km(points, order, False) < route_length_km(points, [0, 1, 2, 3], False)
    assert route_length_km(points, order, False) == pytest.approx(_brute_force_best(points, False), abs=1e-6)


def test_round_trip_closes_the_loop_and_is_never_shorter_than_open():
    points = _random_points(random.Random(5), 8)
    open_order, _ = optimize_order(points, False)
    loop_order, _ = optimize_order(points, True)
    assert route_length_km(points, loop_order, True) >= route_length_km(points, open_order, False) - 1e-9


def test_heuristic_above_the_exact_limit_improves_on_the_requested_order():
    points = _random_points(random.Random(11), 20)
    order, method = optimize_order(points, False)
    assert method == "heuristic"
    # Com semente fixa, o vizinho mais próximo + 2-opt é claramente melhor do que
    # a ordem aleatória pedida.
    assert route_length_km(points, order, False) < route_length_km(points, list(range(20)), False)


def test_heuristic_is_close_to_the_exact_optimum_on_a_size_where_both_run():
    """Mesmo conjunto (11 paragens) pelos dois caminhos: a heurística fica a
    poucos % do ótimo — não é garantidamente ótima, e a documentação diz-lo."""
    from app.services.route_optimization import _exact_order, _heuristic_order, _matrix

    points = _random_points(random.Random(99), 11)
    dist = _matrix(points)
    exact = route_length_km(points, _exact_order(dist, False), False)
    heuristic = route_length_km(points, _heuristic_order(points, dist, False), False)
    assert exact <= heuristic + 1e-9
    assert heuristic <= exact * 1.15


def test_limits():
    with pytest.raises(RouteError):
        optimize_order([LISBOA], False)
    with pytest.raises(RouteError):
        optimize_order(_random_points(random.Random(1), MAX_STOPS + 1), False)


# --- endpoint ---


def _project(db, name, lat=None, lon=None, pm_person_id=None, active=True) -> Project:
    project = Project(name=name, client_name="Cliente rota", lat=lat, lon=lon, pm_person_id=pm_person_id, is_active=active)
    db.add(project)
    db.flush()
    return project


def _ref(kind, entity) -> dict:
    return {"kind": kind, "id": str(entity.id)}


def _post(api_client, stops, email="chefe.sintetico@example.invalid", round_trip=False):
    return api_client.post(
        "/api/map/optimize-route", json={"stops": stops, "round_trip": round_trip}, headers=_headers(email)
    )


def test_endpoint_orders_stops_and_reports_distances(db_session, api_client):
    db = db_session
    lisboa = _project(db, "Rota — Lisboa", *LISBOA)
    porto = _project(db, "Rota — Porto", *PORTO)
    faro = _project(db, "Rota — Faro", *FARO)
    coimbra = _project(db, "Rota — Coimbra", *COIMBRA)
    db.commit()

    resp = _post(api_client, [_ref("project", p) for p in (lisboa, porto, faro, coimbra)])
    assert resp.status_code == 200
    body = resp.json()
    assert body["method"] == "exact"
    assert body["distance_model"] == "great_circle"
    names = [s["name"] for s in body["stops"]]
    assert names[0] == "Rota — Lisboa"  # a primeira paragem é a partida
    assert sorted(names) == sorted(["Rota — Lisboa", "Rota — Porto", "Rota — Faro", "Rota — Coimbra"])
    assert body["stops"][0]["leg_km"] == 0 and body["stops"][0]["cumulative_km"] == 0
    # total = soma das pernas; poupança = pedido − otimizado, nunca negativa
    assert body["total_km"] == pytest.approx(sum(s["leg_km"] for s in body["stops"]), abs=0.05)
    assert body["saved_km"] == pytest.approx(body["requested_order_km"] - body["total_km"], abs=0.02)
    assert body["saved_km"] > 0
    assert body["return_leg_km"] is None


def test_endpoint_round_trip_adds_the_return_leg(db_session, api_client):
    db = db_session
    a = _project(db, "Regresso — A", *LISBOA)
    b = _project(db, "Regresso — B", *PORTO)
    db.commit()
    body = _post(api_client, [_ref("project", a), _ref("project", b)], round_trip=True).json()
    assert body["return_leg_km"] == pytest.approx(body["stops"][1]["leg_km"], abs=0.02)
    assert body["total_km"] == pytest.approx(2 * body["stops"][1]["leg_km"], abs=0.05)


def test_endpoint_mixes_projects_suppliers_and_pickup_points(db_session, api_client):
    db = db_session
    project = _project(db, "Mista — obra", *COIMBRA)
    supplier = Supplier(name="Mista — fornecedor", lat=PORTO[0], lon=PORTO[1], is_active=True)
    pickup = PickupPoint(name="Mista — recolha", lat=LISBOA[0], lon=LISBOA[1], is_active=True)
    db.add_all([supplier, pickup])
    db.commit()
    resp = _post(api_client, [_ref("pickup", pickup), _ref("project", project), _ref("supplier", supplier)])
    assert resp.status_code == 200
    assert [s["kind"] for s in resp.json()["stops"]][0] == "pickup"


def test_endpoint_never_trusts_client_coordinates(db_session, api_client):
    db = db_session
    a = _project(db, "Coords — A", *LISBOA)
    b = _project(db, "Coords — B", *PORTO)
    db.commit()
    resp = api_client.post(
        "/api/map/optimize-route",
        json={"stops": [{**_ref("project", a), "lat": 0.0, "lon": 0.0}, _ref("project", b)]},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 422  # extra="forbid": o cliente só identifica a paragem


def test_endpoint_rejects_stops_without_coordinates_naming_them(db_session, api_client):
    db = db_session
    ok = _project(db, "Sem coords — com", *LISBOA)
    bad = _project(db, "Sem coords — sem")
    db.commit()
    resp = _post(api_client, [_ref("project", ok), _ref("project", bad)])
    assert resp.status_code == 400
    assert "Sem coords — sem" in resp.json()["detail"]


def test_endpoint_rejects_duplicates_unknown_and_inactive_with_the_same_safe_message(db_session, api_client):
    db = db_session
    a = _project(db, "Inv — A", *LISBOA)
    b = _project(db, "Inv — B", *PORTO)
    inactive = _project(db, "Inv — inativo", *FARO, active=False)
    db.commit()

    assert _post(api_client, [_ref("project", a), _ref("project", a)]).status_code == 400
    unknown = _post(api_client, [_ref("project", a), {"kind": "project", "id": str(uuid.uuid4())}])
    hidden = _post(api_client, [_ref("project", a), _ref("project", inactive)])
    assert unknown.status_code == hidden.status_code == 400
    assert unknown.json()["detail"] == hidden.json()["detail"]  # não revela se existe
    assert _post(api_client, [_ref("project", a)]).status_code == 422  # mínimo 2 (validação do schema)
    assert _post(api_client, [_ref("project", a), _ref("project", b)]).status_code == 200


def test_pm_cannot_route_through_a_project_outside_their_scope(db_session, api_client):
    db = db_session
    other = _project(db, "Alheio — sem PM", *LISBOA)  # sem PM: invisível ao PM
    supplier = Supplier(name="Alheio — fornecedor", lat=PORTO[0], lon=PORTO[1], is_active=True)
    db.add(supplier)
    db.commit()
    resp = _post(
        api_client, [_ref("supplier", supplier), _ref("project", other)], email="pm.um.sintetico@example.invalid"
    )
    assert resp.status_code == 400
    assert "Alheio" not in resp.json()["detail"]  # nem o nome do projeto alheio vaza


def test_endpoint_requires_authentication(api_client):
    resp = api_client.post(
        "/api/map/optimize-route",
        json={"stops": [{"kind": "project", "id": str(uuid.uuid4())}, {"kind": "project", "id": str(uuid.uuid4())}]},
    )
    assert resp.status_code == 401


def test_endpoint_does_not_write_anything(db_session, api_client):
    from app.models.project import ProjectHistory

    db = db_session
    a = _project(db, "Só leitura — A", *LISBOA)
    b = _project(db, "Só leitura — B", *PORTO)
    db.commit()
    before = (db.query(Project).count(), db.query(ProjectHistory).count())
    assert _post(api_client, [_ref("project", a), _ref("project", b)]).status_code == 200
    assert (db.query(Project).count(), db.query(ProjectHistory).count()) == before
