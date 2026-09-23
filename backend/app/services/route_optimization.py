"""Otimização da ordem de paragens de uma rota (Fase F, D-065).

Cálculo **determinístico do backend** (ARCHITECTURE_PROPOSAL.md, secção de
integrações): sem serviço externo de routing, sem geocoding, sem chamadas de
rede. A distância é em **linha reta (grande círculo, haversine)** — uma
aproximação da distância real por estrada, boa para comparar a ordem de
paragens mas que nunca deve ser apresentada como quilómetros de condução.

A primeira paragem é o ponto de partida e fica sempre em primeiro lugar. Com
`round_trip` a rota fecha no ponto de partida; sem ele, termina onde for mais
curto. Até `EXACT_LIMIT` paragens o resultado é o **ótimo** (programação
dinâmica sobre subconjuntos, Held-Karp); acima disso usa-se vizinho mais
próximo + 2-opt (boa, mas não garantidamente ótima).
"""
from __future__ import annotations

import dataclasses
import math
import uuid
from typing import Literal

from sqlalchemy.orm import Session

from app.models.map_ops import PickupPoint
from app.models.project import Project
from app.models.supplier import Supplier
from app.security.permissions import AuthContext
from app.services.projects import visible_projects_query

EARTH_RADIUS_KM = 6371.0088
MIN_STOPS = 2
MAX_STOPS = 25
# Held-Karp é O(n² · 2ⁿ): com 12 paragens são ~600 mil operações — instantâneo.
EXACT_LIMIT = 12

Point = tuple[float, float]  # (lat, lon) em graus


class RouteError(ValueError):
    """Pedido de rota inválido — a mensagem é segura para mostrar ao utilizador."""


def haversine_km(a: Point, b: Point) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def _matrix(points: list[Point]) -> list[list[float]]:
    return [[haversine_km(a, b) for b in points] for a in points]


def route_length_km(points: list[Point], order: list[int], round_trip: bool) -> float:
    total = sum(haversine_km(points[order[i]], points[order[i + 1]]) for i in range(len(order) - 1))
    if round_trip and len(order) > 1:
        total += haversine_km(points[order[-1]], points[order[0]])
    return total


def _exact_order(dist: list[list[float]], round_trip: bool) -> list[int]:
    """Held-Karp com a paragem 0 fixa como início. `dp[mask][j]` = custo mínimo
    de um caminho que parte de 0, visita o conjunto `mask` e termina em `j`.
    Empates resolvidos pelo menor índice (ordem de iteração ascendente e `<`
    estrito) — o mesmo pedido dá sempre a mesma rota."""
    n = len(dist)
    others = list(range(1, n))
    m = len(others)
    inf = float("inf")
    size = 1 << m
    dp = [[inf] * m for _ in range(size)]
    parent = [[-1] * m for _ in range(size)]
    for j in range(m):
        dp[1 << j][j] = dist[0][others[j]]
    for mask in range(1, size):
        for j in range(m):
            if not mask & (1 << j) or dp[mask][j] == inf:
                continue
            for k in range(m):
                if mask & (1 << k):
                    continue
                nxt = mask | (1 << k)
                cost = dp[mask][j] + dist[others[j]][others[k]]
                if cost < dp[nxt][k]:
                    dp[nxt][k] = cost
                    parent[nxt][k] = j
    full = size - 1
    best_j, best_cost = 0, inf
    for j in range(m):
        cost = dp[full][j] + (dist[others[j]][0] if round_trip else 0.0)
        if cost < best_cost:
            best_cost, best_j = cost, j
    order_rev: list[int] = []
    mask, j = full, best_j
    while j != -1:
        order_rev.append(others[j])
        prev = parent[mask][j]
        mask ^= 1 << j
        j = prev
    return [0] + order_rev[::-1]


def _heuristic_order(points: list[Point], dist: list[list[float]], round_trip: bool) -> list[int]:
    """Vizinho mais próximo a partir de 0 e depois 2-opt até não haver melhoria.
    Determinístico: empates no vizinho mais próximo vão para o menor índice."""
    n = len(points)
    unvisited = set(range(1, n))
    order = [0]
    while unvisited:
        last = order[-1]
        nearest = min(sorted(unvisited), key=lambda k: dist[last][k])
        order.append(nearest)
        unvisited.remove(nearest)

    improved = True
    while improved:
        improved = False
        best = route_length_km(points, order, round_trip)
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                candidate = order[:i] + order[i : j + 1][::-1] + order[j + 1 :]
                length = route_length_km(points, candidate, round_trip)
                if length < best - 1e-9:
                    order, best, improved = candidate, length, True
    return order


def optimize_order(points: list[Point], round_trip: bool) -> tuple[list[int], Literal["exact", "heuristic"]]:
    """Devolve os índices de `points` na ordem otimizada (o índice 0 fica sempre
    primeiro) e o método usado."""
    n = len(points)
    if n < MIN_STOPS:
        raise RouteError(f"Indique pelo menos {MIN_STOPS} paragens.")
    if n > MAX_STOPS:
        raise RouteError(f"No máximo {MAX_STOPS} paragens por rota.")
    dist = _matrix(points)
    if n <= EXACT_LIMIT:
        return _exact_order(dist, round_trip), "exact"
    return _heuristic_order(points, dist, round_trip), "heuristic"


# --- Resolução das paragens (visibilidade e coordenadas vêm SEMPRE do servidor) ---


@dataclasses.dataclass(frozen=True)
class ResolvedStop:
    kind: str
    id: uuid.UUID
    name: str
    lat: float
    lon: float


def resolve_stops(db: Session, ctx: AuthContext, refs: list[tuple[str, uuid.UUID]]) -> list[ResolvedStop]:
    """Resolve cada paragem no servidor: nunca confia em coordenadas do cliente
    e aplica a mesma visibilidade do mapa (`visible_projects_query` para
    instalações). Uma paragem inexistente, inativa ou fora do âmbito do
    utilizador dá a mesma mensagem — não revela se existe."""
    if len(refs) < MIN_STOPS:
        raise RouteError(f"Indique pelo menos {MIN_STOPS} paragens.")
    if len(refs) > MAX_STOPS:
        raise RouteError(f"No máximo {MAX_STOPS} paragens por rota.")
    if len(set(refs)) != len(refs):
        raise RouteError("Há paragens repetidas na rota.")

    project_ids = [i for k, i in refs if k == "project"]
    supplier_ids = [i for k, i in refs if k == "supplier"]
    pickup_ids = [i for k, i in refs if k == "pickup"]

    projects = (
        {p.id: p for p in visible_projects_query(db, ctx).filter(Project.id.in_(project_ids), Project.is_active.is_(True)).all()}
        if project_ids
        else {}
    )
    suppliers = (
        {s.id: s for s in db.query(Supplier).filter(Supplier.id.in_(supplier_ids), Supplier.is_active.is_(True)).all()}
        if supplier_ids
        else {}
    )
    pickups = (
        {p.id: p for p in db.query(PickupPoint).filter(PickupPoint.id.in_(pickup_ids), PickupPoint.is_active.is_(True)).all()}
        if pickup_ids
        else {}
    )
    by_kind = {"project": projects, "supplier": suppliers, "pickup": pickups}

    resolved: list[ResolvedStop] = []
    missing_coordinates: list[str] = []
    for kind, stop_id in refs:
        entity = by_kind.get(kind, {}).get(stop_id)
        if entity is None:
            raise RouteError("Uma das paragens não existe ou não tem permissão para a ver.")
        if entity.lat is None or entity.lon is None:
            missing_coordinates.append(entity.name)
            continue
        resolved.append(ResolvedStop(kind=kind, id=stop_id, name=entity.name, lat=entity.lat, lon=entity.lon))
    if missing_coordinates:
        raise RouteError("Paragens sem coordenadas: " + ", ".join(missing_coordinates) + ".")
    return resolved


# --- Rota completa (pernas, totais e poupança) — partilhada por todos os endpoints ---


@dataclasses.dataclass(frozen=True)
class RouteLeg:
    stop: ResolvedStop
    leg_km: float  # desde a paragem anterior (0 na primeira)
    cumulative_km: float


@dataclasses.dataclass(frozen=True)
class RouteComputation:
    legs: list[RouteLeg]
    return_leg_km: float | None  # só com round_trip
    total_km: float
    requested_order_km: float
    saved_km: float
    method: Literal["exact", "heuristic"]
    round_trip: bool


def compute_route(stops: list[ResolvedStop], round_trip: bool) -> RouteComputation:
    """Otimiza a ordem e calcula pernas/totais. É o único sítio que faz esta
    conta: a otimização de rota (D-065) e o plano de deslocação (D-066) usam-no,
    por isso nunca podem divergir."""
    points = [(s.lat, s.lon) for s in stops]
    order, method = optimize_order(points, round_trip)
    requested = route_length_km(points, list(range(len(points))), round_trip)
    total = route_length_km(points, order, round_trip)

    ordered = [stops[i] for i in order]
    legs: list[RouteLeg] = []
    cumulative = 0.0
    for index, stop in enumerate(ordered):
        leg = haversine_km((ordered[index - 1].lat, ordered[index - 1].lon), (stop.lat, stop.lon)) if index else 0.0
        cumulative += leg
        legs.append(RouteLeg(stop=stop, leg_km=round(leg, 2), cumulative_km=round(cumulative, 2)))
    return_leg = (
        round(haversine_km((ordered[-1].lat, ordered[-1].lon), (ordered[0].lat, ordered[0].lon)), 2)
        if round_trip
        else None
    )
    return RouteComputation(
        legs=legs,
        return_leg_km=return_leg,
        total_km=round(total, 2),
        requested_order_km=round(requested, 2),
        saved_km=round(max(requested - total, 0.0), 2),
        method=method,
        round_trip=round_trip,
    )
