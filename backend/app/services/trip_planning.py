"""Plano de deslocação (Fase F, D-066): a rota otimizada (D-065) mais o que há
para fazer em cada instalação — tarefas operacionais abertas, pendências
abertas, material a recolher e próxima visita. É o "3 instalações, 5
pendências, 2 recolhas numa saída" do plano original.

**Só leitura**: não cria tarefas, eventos nem movimentos. Reaproveita a mesma
resolução de paragens (visibilidade e coordenadas vêm sempre do servidor) e o
mesmo cálculo de rota da otimização. Número de queries fixo, independente do
número de paragens (tarefas, pendências, saldos no local e visitas de todas as
instalações de uma vez).

Cada secção respeita a permissão que já a protege no resto da aplicação e é
`None` quando o utilizador não a tem — nunca uma lista vazia, que diria
"não há nada": tarefas (`task.view_all`/`task.view_own`), pendências
(`project_issue.view`), material (`inventory.view`), visitas (`calendar.view`).
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict

from sqlalchemy.orm import Session

from app.models.inventory import InventoryItem
from app.models.map_ops import PickupPoint, ProjectIssue
from app.models.supplier import Supplier
from app.models.task import OPEN_TASK_STATUSES, OPERATIONAL_TASK_CATEGORIES
from app.schemas.map import (
    NextVisitRead,
    TripCollectRead,
    TripIssueRead,
    TripPlanResponse,
    TripStopJobs,
    TripStopRead,
    TripSummary,
    TripTaskRead,
    TripVisibility,
)
from app.security.permissions import AuthContext
from app.services.inventory import on_site_balances_by_project
from app.services.map import (
    _load_person_names,
    _load_tasks_by_project,
    _load_upcoming_visits_by_project,
    _next_visit,
)
from app.services.route_optimization import ResolvedStop, compute_route, resolve_stops

ISSUE_OPEN_STATUS = "aberta"


def plan_trip(db: Session, ctx: AuthContext, refs: list[tuple[str, uuid.UUID]], round_trip: bool) -> TripPlanResponse:
    stops = resolve_stops(db, ctx, refs)
    route = compute_route(stops, round_trip)

    project_ids = [s.id for s in stops if s.kind == "project"]
    visibility = TripVisibility(
        tasks=ctx.has_permission("task.view_all") or ctx.has_permission("task.view_own"),
        issues=ctx.has_permission("project_issue.view"),
        material=ctx.has_permission("inventory.view"),
        visits=ctx.has_permission("calendar.view"),
    )

    tasks_by_project = _load_tasks_by_project(db, project_ids) if visibility.tasks else {}
    issues_by_project = _load_open_issues(db, project_ids) if visibility.issues else {}
    on_site = on_site_balances_by_project(db, project_ids) if visibility.material else {}
    item_names = _load_items(db, {i for balances in on_site.values() for i in balances})
    visits = _load_upcoming_visits_by_project(db, project_ids) if visibility.visits else {}
    assignees = _load_person_names(
        db, {ev[0].assigned_to_person_id for ev in visits.values() if ev and ev[0].assigned_to_person_id}
    )
    info_by_stop = _load_stop_info(db, stops)

    total_tasks = total_overdue = total_issues = total_collect = 0
    read_stops: list[TripStopRead] = []
    for leg in route.legs:
        stop = leg.stop
        jobs = None
        if stop.kind == "project":
            jobs = TripStopJobs()
            if visibility.tasks:
                operational = sorted(
                    (
                        t
                        for t in tasks_by_project.get(stop.id, [])
                        if t.category in OPERATIONAL_TASK_CATEGORIES and t.status in OPEN_TASK_STATUSES
                    ),
                    key=lambda t: (t.due_date is None, t.due_date or dt.date.max, str(t.id)),
                )
                jobs.tasks = [
                    TripTaskRead(
                        id=t.id,
                        title=t.title,
                        category=t.category,
                        priority=t.priority,
                        status=t.status,
                        due_date=t.due_date,
                        is_overdue=t.is_overdue,
                    )
                    for t in operational
                ]
                total_tasks += len(jobs.tasks)
                total_overdue += sum(1 for t in jobs.tasks if t.is_overdue)
            if visibility.issues:
                jobs.issues = [
                    TripIssueRead(
                        id=i.id, description=i.description, category=i.category, priority=i.priority, due_date=i.due_date
                    )
                    for i in issues_by_project.get(stop.id, [])
                ]
                total_issues += len(jobs.issues)
            if visibility.material:
                balances = on_site.get(stop.id, {})
                jobs.collect = [
                    TripCollectRead(
                        item_id=item_id,
                        item_name=item_names[item_id].name if item_id in item_names else None,
                        item_unit=item_names[item_id].unit if item_id in item_names else None,
                        quantity=quantity,
                    )
                    for item_id, quantity in sorted(
                        balances.items(),
                        key=lambda kv: (item_names[kv[0]].name if kv[0] in item_names else "", str(kv[0])),
                    )
                ]
                total_collect += len(jobs.collect)
            if visibility.visits:
                visit = _next_visit(visits.get(stop.id, []), assignees)
                jobs.next_visit = (
                    NextVisitRead(
                        id=visit.id,
                        title=visit.title,
                        starts_at=visit.starts_at,
                        ends_at=visit.ends_at,
                        assigned_to_display_name=visit.assigned_to_display_name,
                    )
                    if visit
                    else None
                )
        read_stops.append(
            TripStopRead(
                kind=stop.kind,
                id=stop.id,
                name=stop.name,
                lat=stop.lat,
                lon=stop.lon,
                leg_km=leg.leg_km,
                cumulative_km=leg.cumulative_km,
                info=info_by_stop.get((stop.kind, stop.id)),
                jobs=jobs,
            )
        )

    return TripPlanResponse(
        stops=read_stops,
        return_leg_km=route.return_leg_km,
        round_trip=route.round_trip,
        total_km=route.total_km,
        requested_order_km=route.requested_order_km,
        saved_km=route.saved_km,
        method=route.method,
        summary=TripSummary(
            projects=len(project_ids),
            suppliers=sum(1 for s in stops if s.kind == "supplier"),
            pickup_points=sum(1 for s in stops if s.kind == "pickup"),
            operational_tasks=total_tasks if visibility.tasks else None,
            overdue_tasks=total_overdue if visibility.tasks else None,
            issues=total_issues if visibility.issues else None,
            items_to_collect=total_collect if visibility.material else None,
        ),
        visibility=visibility,
    )


def _load_open_issues(db: Session, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[ProjectIssue]]:
    by_project: dict[uuid.UUID, list[ProjectIssue]] = defaultdict(list)
    if not project_ids:
        return by_project
    rows = (
        db.query(ProjectIssue)
        .filter(ProjectIssue.project_id.in_(project_ids), ProjectIssue.status == ISSUE_OPEN_STATUS)
        .order_by(ProjectIssue.created_at.asc(), ProjectIssue.id.asc())
        .all()
    )
    for issue in rows:
        by_project[issue.project_id].append(issue)
    return by_project


def _load_items(db: Session, item_ids: set[uuid.UUID]) -> dict[uuid.UUID, InventoryItem]:
    if not item_ids:
        return {}
    return {i.id: i for i in db.query(InventoryItem).filter(InventoryItem.id.in_(item_ids)).all()}


def _load_stop_info(db: Session, stops: list[ResolvedStop]) -> dict[tuple[str, uuid.UUID], str]:
    """Texto livre dos materiais de fornecedores/pontos de recolha (uma query
    por tipo, nunca uma por paragem). Vazio não aparece."""
    info: dict[tuple[str, uuid.UUID], str] = {}
    supplier_ids = [s.id for s in stops if s.kind == "supplier"]
    pickup_ids = [s.id for s in stops if s.kind == "pickup"]
    if supplier_ids:
        for row in db.query(Supplier).filter(Supplier.id.in_(supplier_ids)).all():
            if row.materials:
                info[("supplier", row.id)] = row.materials
    if pickup_ids:
        for row in db.query(PickupPoint).filter(PickupPoint.id.in_(pickup_ids)).all():
            if row.materials:
                info[("pickup", row.id)] = row.materials
    return info
