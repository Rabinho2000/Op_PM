"""Endpoints do mapa operacional: payload combinado, fornecedores, pontos
de recolha, e pendências de obra por projeto. Ver
docs/MAP_AND_PLANNING.md e app/services/map.py.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models.map_ops import PickupPoint, ProjectIssue
from app.models.supplier import Supplier
from app.schemas.map import (
    ConvertIssueToTask,
    MapConfig,
    MapDataResponse,
    MapPickupPointRead,
    MapProjectRead,
    MapSummaryRead,
    MapSupplierRead,
    NextOperationalTaskRead,
    NextVisitRead,
    PickupPointCreate,
    PickupPointUpdate,
    ProjectIssueCreate,
    ProjectIssueRead,
    ProjectIssueUpdate,
    RouteOptimizationRequest,
    RouteOptimizationResponse,
    RouteStopRead,
    SupplierCreate,
    SupplierUpdate,
    TripPlanResponse,
)
from app.schemas.tasks import TaskRead
from app.security.current_user import get_auth_context
from app.security.permissions import (
    AuthContext,
    can_manage_pickup_points,
    can_manage_project_issue,
    can_manage_suppliers,
    can_view_map,
    can_view_project_issue,
)
from app.services.map import (
    compute_map_summary,
    convert_issue_to_task,
    create_project_issue,
    get_map_projects,
    get_visible_issues,
    get_visible_pickup_points,
    get_visible_suppliers,
    list_project_issues,
    update_project_issue,
)
from app.services.projects import get_visible_project
from app.services.route_optimization import RouteError, compute_route, resolve_stops
from app.services.trip_planning import plan_trip

router = APIRouter(tags=["map"])


def _require_map_view(ctx: AuthContext) -> None:
    if not can_view_map(ctx):
        raise HTTPException(status_code=403, detail="Sem permissão para ver o mapa operacional.")


def _map_project_read(entry) -> MapProjectRead:
    project = entry.project
    next_task = None
    if entry.next_operational_task is not None:
        next_task = NextOperationalTaskRead(
            id=entry.next_operational_task.id,
            title=entry.next_operational_task.title,
            due_date=entry.next_operational_task.due_date,
            priority=entry.next_operational_task.priority,
        )
    next_visit = None
    if entry.next_visit is not None:
        next_visit = NextVisitRead(
            id=entry.next_visit.id,
            title=entry.next_visit.title,
            starts_at=entry.next_visit.starts_at,
            ends_at=entry.next_visit.ends_at,
            assigned_to_display_name=entry.next_visit.assigned_to_display_name,
        )
    return MapProjectRead(
        id=project.id,
        name=project.name,
        client_name=project.client_name,
        pm_person_id=project.pm_person_id,
        pm_display_name=project.pm.display_name if project.pm else None,
        status=entry.task_summary.status,
        lat=project.lat,
        lon=project.lon,
        power_kwp=project.power_kwp,
        open_tasks_count=entry.open_tasks_count,
        issues_count=entry.issues_count,
        attention=entry.attention,
        operational_tasks_count=entry.operational_tasks_count,
        overdue_operational_tasks_count=entry.overdue_operational_tasks_count,
        blocked_operational_tasks_count=entry.blocked_operational_tasks_count,
        urgent_operational_tasks_count=entry.urgent_operational_tasks_count,
        next_operational_task=next_task,
        material_visible=entry.material_visible,
        has_material_on_site=entry.has_material_on_site,
        material_sku_count=entry.material_sku_count,
        visits_visible=entry.visits_visible,
        upcoming_visits_count=entry.upcoming_visits_count,
        next_visit=next_visit,
    )


@router.get("/api/map/data", response_model=MapDataResponse)
def get_map_data_endpoint(
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
) -> MapDataResponse:
    _require_map_view(ctx)
    with_coords, without_coords = get_map_projects(db, ctx)
    issues = get_visible_issues(db, ctx)
    issue_reads = []
    for issue in issues:
        data = ProjectIssueRead.model_validate(issue)
        data.project_name = issue.project.name if issue.project else None
        issue_reads.append(data)

    summary = compute_map_summary(with_coords, without_coords)

    return MapDataResponse(
        config=MapConfig(
            provider_enabled=settings.map_provider_enabled,
            tile_url=settings.map_tile_url,
            tile_attribution=settings.map_tile_attribution,
        ),
        projects=[_map_project_read(e) for e in with_coords],
        projects_without_coordinates=[_map_project_read(e) for e in without_coords],
        suppliers=[MapSupplierRead.model_validate(s) for s in get_visible_suppliers(db)],
        pickup_points=[MapPickupPointRead.model_validate(p) for p in get_visible_pickup_points(db)],
        issues=issue_reads,
        summary=MapSummaryRead(
            visible_active_projects=summary.visible_active_projects,
            mapped_projects=summary.mapped_projects,
            unmapped_projects=summary.unmapped_projects,
            map_coverage_percent=summary.map_coverage_percent,
            green_projects=summary.green_projects,
            yellow_projects=summary.yellow_projects,
            red_projects=summary.red_projects,
            operational_clean_percent=summary.operational_clean_percent,
            projects_with_material=summary.projects_with_material,
        ),
    )


@router.get("/api/suppliers", response_model=list[MapSupplierRead])
def list_suppliers_endpoint(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> list[MapSupplierRead]:
    _require_map_view(ctx)
    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    return [MapSupplierRead.model_validate(s) for s in suppliers]


@router.post("/api/suppliers", response_model=MapSupplierRead, status_code=201)
def create_supplier_endpoint(
    body: SupplierCreate, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> MapSupplierRead:
    if not can_manage_suppliers(ctx):
        raise HTTPException(status_code=403, detail="Sem permissão para criar fornecedores.")
    supplier = Supplier(**body.model_dump())
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return MapSupplierRead.model_validate(supplier)


@router.patch("/api/suppliers/{supplier_id}", response_model=MapSupplierRead)
def update_supplier_endpoint(
    supplier_id: uuid.UUID,
    body: SupplierUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> MapSupplierRead:
    if not can_manage_suppliers(ctx):
        raise HTTPException(status_code=403, detail="Sem permissão para editar fornecedores.")
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado.")
    for field_name, value in body.model_dump(exclude_unset=True).items():
        setattr(supplier, field_name, value)
    db.commit()
    db.refresh(supplier)
    return MapSupplierRead.model_validate(supplier)


@router.get("/api/pickup-points", response_model=list[MapPickupPointRead])
def list_pickup_points_endpoint(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> list[MapPickupPointRead]:
    _require_map_view(ctx)
    points = db.query(PickupPoint).order_by(PickupPoint.name).all()
    return [MapPickupPointRead.model_validate(p) for p in points]


@router.post("/api/pickup-points", response_model=MapPickupPointRead, status_code=201)
def create_pickup_point_endpoint(
    body: PickupPointCreate, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> MapPickupPointRead:
    if not can_manage_pickup_points(ctx):
        raise HTTPException(status_code=403, detail="Sem permissão para criar pontos de recolha.")
    point = PickupPoint(**body.model_dump())
    db.add(point)
    db.commit()
    db.refresh(point)
    return MapPickupPointRead.model_validate(point)


@router.patch("/api/pickup-points/{point_id}", response_model=MapPickupPointRead)
def update_pickup_point_endpoint(
    point_id: uuid.UUID,
    body: PickupPointUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> MapPickupPointRead:
    if not can_manage_pickup_points(ctx):
        raise HTTPException(status_code=403, detail="Sem permissão para editar pontos de recolha.")
    point = db.get(PickupPoint, point_id)
    if point is None:
        raise HTTPException(status_code=404, detail="Ponto de recolha não encontrado.")
    for field_name, value in body.model_dump(exclude_unset=True).items():
        setattr(point, field_name, value)
    db.commit()
    db.refresh(point)
    return MapPickupPointRead.model_validate(point)


def _issue_to_read(issue: ProjectIssue) -> ProjectIssueRead:
    data = ProjectIssueRead.model_validate(issue)
    data.project_name = issue.project.name if issue.project else None
    return data


@router.get("/api/projects/{project_id}/issues", response_model=list[ProjectIssueRead])
def list_project_issues_endpoint(
    project_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> list[ProjectIssueRead]:
    project = get_visible_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")
    if not can_view_project_issue(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para ver pendências deste projeto.")
    return [_issue_to_read(i) for i in list_project_issues(db, project_id)]


@router.post("/api/projects/{project_id}/issues", response_model=ProjectIssueRead, status_code=201)
def create_project_issue_endpoint(
    project_id: uuid.UUID,
    body: ProjectIssueCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectIssueRead:
    project = get_visible_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")
    if not can_manage_project_issue(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para criar pendências neste projeto.")
    issue = create_project_issue(
        db,
        project_id=project_id,
        description=body.description,
        category=body.category,
        priority=body.priority,
        lat=body.lat if body.lat is not None else project.lat,
        lon=body.lon if body.lon is not None else project.lon,
        notes=body.notes,
        created_by_person_id=ctx.person_id,
    )
    if body.assigned_to_person_id is not None:
        issue.assigned_to_person_id = body.assigned_to_person_id
    if body.due_date is not None:
        issue.due_date = body.due_date
    issue.visible_on_map = body.visible_on_map
    db.commit()
    db.refresh(issue)
    return _issue_to_read(issue)


@router.patch("/api/projects/{project_id}/issues/{issue_id}", response_model=ProjectIssueRead)
def update_project_issue_endpoint(
    project_id: uuid.UUID,
    issue_id: uuid.UUID,
    body: ProjectIssueUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectIssueRead:
    project = get_visible_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")
    if not can_manage_project_issue(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para editar pendências deste projeto.")
    issue = db.get(ProjectIssue, issue_id)
    if issue is None or issue.project_id != project_id:
        raise HTTPException(status_code=404, detail="Pendência não encontrada.")
    updated = update_project_issue(db, issue=issue, changes=body.model_dump(exclude_unset=True))
    return _issue_to_read(updated)


@router.post("/api/projects/{project_id}/issues/{issue_id}/convert-to-task", response_model=TaskRead)
def convert_issue_to_task_endpoint(
    project_id: uuid.UUID,
    issue_id: uuid.UUID,
    body: ConvertIssueToTask,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> TaskRead:
    project = get_visible_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")
    if not can_manage_project_issue(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para converter pendências deste projeto.")
    issue = db.get(ProjectIssue, issue_id)
    if issue is None or issue.project_id != project_id:
        raise HTTPException(status_code=404, detail="Pendência não encontrada.")
    if issue.related_task_id is not None:
        raise HTTPException(status_code=400, detail="Esta pendência já foi convertida numa tarefa.")
    task = convert_issue_to_task(db, issue=issue, title=body.title, created_by_person_id=ctx.person_id)
    return TaskRead.model_validate(task)


@router.post("/api/map/optimize-route", response_model=RouteOptimizationResponse)
def optimize_route_endpoint(
    body: RouteOptimizationRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> RouteOptimizationResponse:
    """Ordena as paragens para minimizar a distância em linha reta (D-065).
    Só lê — não grava nada. A primeira paragem é o ponto de partida."""
    _require_map_view(ctx)
    try:
        route = compute_route(resolve_stops(db, ctx, [(s.kind, s.id) for s in body.stops]), body.round_trip)
    except RouteError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RouteOptimizationResponse(
        stops=[
            RouteStopRead(
                kind=leg.stop.kind,
                id=leg.stop.id,
                name=leg.stop.name,
                lat=leg.stop.lat,
                lon=leg.stop.lon,
                leg_km=leg.leg_km,
                cumulative_km=leg.cumulative_km,
            )
            for leg in route.legs
        ],
        return_leg_km=route.return_leg_km,
        round_trip=route.round_trip,
        total_km=route.total_km,
        requested_order_km=route.requested_order_km,
        saved_km=route.saved_km,
        method=route.method,
    )


@router.post("/api/map/trip-plan", response_model=TripPlanResponse)
def trip_plan_endpoint(
    body: RouteOptimizationRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> TripPlanResponse:
    """Plano de deslocação (D-066): a rota otimizada mais o que há para fazer em
    cada instalação. Só lê — não cria tarefas, eventos nem movimentos. Cada
    secção respeita a sua permissão e é `null` quando o utilizador não a tem."""
    _require_map_view(ctx)
    try:
        return plan_trip(db, ctx, [(s.kind, s.id) for s in body.stops], body.round_trip)
    except RouteError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
