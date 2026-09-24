from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NextOperationalTaskRead(BaseModel):
    id: uuid.UUID
    title: str
    due_date: dt.date | None
    priority: str


class NextVisitRead(BaseModel):
    id: uuid.UUID
    title: str
    starts_at: dt.datetime
    ends_at: dt.datetime
    assigned_to_display_name: str | None = None


class MapProjectRead(BaseModel):
    id: uuid.UUID
    name: str
    client_name: str | None
    pm_person_id: uuid.UUID | None = None
    pm_display_name: str | None
    status: str
    lifecycle_status: str | None = None
    lat: float | None
    lon: float | None
    power_kwp: float | None
    open_tasks_count: int
    issues_count: int

    # attention (green|yellow|red) — sempre derivado, nunca persistido; ver
    # app/services/map.py:_compute_attention. Só usa OPERATIONAL_TASK_CATEGORIES
    # (field/material) e, quando visível, material físico no local — nunca
    # tarefas de workflow/documentação.
    attention: str = "green"
    operational_tasks_count: int = 0
    overdue_operational_tasks_count: int = 0
    blocked_operational_tasks_count: int = 0
    urgent_operational_tasks_count: int = 0
    next_operational_task: NextOperationalTaskRead | None = None

    # Inventário: `material_visible=False` (sem inventory.view) devolve
    # sempre `has_material_on_site`/`material_sku_count` a `null` — nunca
    # `false`, para nunca revelar por omissão que não há stock a quem não
    # tem permissão para ver stock nenhum.
    material_visible: bool = False
    has_material_on_site: bool | None = None
    material_sku_count: int | None = None

    # Visitas futuras (calendário). `visits_visible=False` (sem calendar.view)
    # => `upcoming_visits_count`/`next_visit` ficam sempre `null`, nunca
    # "0 visitas". Não influenciam `attention`.
    visits_visible: bool = False
    upcoming_visits_count: int | None = None
    next_visit: NextVisitRead | None = None


class MapSupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: str | None
    contact: str | None
    email: str | None
    address: str | None
    lat: float | None
    lon: float | None
    is_preferred: bool
    lead_time_days: int | None
    materials: str
    is_active: bool


class SupplierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    category: str | None = None
    contact: str | None = None
    email: str | None = None
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    is_preferred: bool = False
    lead_time_days: int | None = None
    materials: str = ""


class SupplierUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    category: str | None = None
    contact: str | None = None
    email: str | None = None
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    is_preferred: bool | None = None
    lead_time_days: int | None = None
    materials: str | None = None
    is_active: bool | None = None


class MapPickupPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    supplier_id: uuid.UUID | None
    address: str | None
    lat: float | None
    lon: float | None
    schedule: str | None
    contact: str | None
    materials: str
    notes: str
    is_active: bool


class PickupPointCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    supplier_id: uuid.UUID | None = None
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    schedule: str | None = None
    contact: str | None = None
    materials: str = ""
    notes: str = ""


class PickupPointUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    supplier_id: uuid.UUID | None = None
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    schedule: str | None = None
    contact: str | None = None
    materials: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class ProjectIssueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    description: str
    category: str
    priority: str
    status: str
    assigned_to_person_id: uuid.UUID | None
    due_date: dt.date | None
    lat: float | None
    lon: float | None
    related_task_id: uuid.UUID | None
    notes: str
    visible_on_map: bool
    created_by_person_id: uuid.UUID | None
    created_at: dt.datetime

    project_name: str | None = None


class ProjectIssueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    category: str = "outro"
    priority: str = "medium"
    assigned_to_person_id: uuid.UUID | None = None
    due_date: dt.date | None = None
    lat: float | None = None
    lon: float | None = None
    notes: str = ""
    visible_on_map: bool = True


class ProjectIssueUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    category: str | None = None
    priority: str | None = None
    status: str | None = None
    assigned_to_person_id: uuid.UUID | None = None
    due_date: dt.date | None = None
    lat: float | None = None
    lon: float | None = None
    notes: str | None = None
    visible_on_map: bool | None = None


class ConvertIssueToTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str


class MapConfig(BaseModel):
    provider_enabled: bool
    tile_url: str
    tile_attribution: str


class MapSummaryRead(BaseModel):
    """Duas métricas deliberadamente separadas — ver
    app/services/map.py:compute_map_summary. `map_coverage_percent` é
    cobertura de coordenadas (problema de dados); `operational_clean_percent`
    é estado operacional (attention). Nunca a mesma métrica com dois nomes."""

    visible_active_projects: int
    mapped_projects: int
    unmapped_projects: int
    map_coverage_percent: float
    green_projects: int
    yellow_projects: int
    red_projects: int
    operational_clean_percent: float
    projects_with_material: int


class MapDataResponse(BaseModel):
    config: MapConfig
    projects: list[MapProjectRead]
    projects_without_coordinates: list[MapProjectRead]
    suppliers: list[MapSupplierRead]
    pickup_points: list[MapPickupPointRead]
    issues: list[ProjectIssueRead]
    summary: MapSummaryRead


# --- Otimização de rota (D-065) ---


class RouteStopRef(BaseModel):
    """Só identifica a paragem — as coordenadas e a visibilidade são sempre
    resolvidas no servidor, nunca aceites do cliente."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["project", "supplier", "pickup"]
    id: uuid.UUID


class RouteOptimizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A PRIMEIRA paragem é o ponto de partida e fica sempre em primeiro lugar.
    stops: list[RouteStopRef] = Field(min_length=2, max_length=25)
    round_trip: bool = False


class RouteStopRead(BaseModel):
    kind: str
    id: uuid.UUID
    name: str
    lat: float
    lon: float
    leg_km: float  # desde a paragem anterior (0 na primeira)
    cumulative_km: float


class RouteOptimizationResponse(BaseModel):
    stops: list[RouteStopRead]
    # Só com round_trip: perna de regresso ao ponto de partida (já incluída em
    # total_km, mas não em nenhuma paragem).
    return_leg_km: float | None = None
    round_trip: bool
    total_km: float
    requested_order_km: float  # a mesma rota na ordem em que as paragens foram pedidas
    saved_km: float  # requested_order_km - total_km (nunca negativo)
    method: Literal["exact", "heuristic"]
    # Distância em linha reta (grande círculo) — aproximação, não quilómetros
    # de condução. O frontend deve dizê-lo.
    distance_model: Literal["great_circle"] = "great_circle"


# --- Plano de deslocação (D-066) ---


class TripTaskRead(BaseModel):
    id: uuid.UUID
    title: str
    category: str
    priority: str
    status: str
    due_date: dt.date | None
    is_overdue: bool


class TripIssueRead(BaseModel):
    id: uuid.UUID
    description: str
    category: str
    priority: str
    due_date: dt.date | None


class TripCollectRead(BaseModel):
    """Material que está no local e há a recolher/consumir (D-064)."""

    item_id: uuid.UUID
    item_name: str | None = None
    item_unit: str | None = None
    quantity: Decimal


class TripStopJobs(BaseModel):
    """O que há para fazer numa instalação. Cada secção é `null` quando o
    utilizador não tem a permissão para a ver (nunca uma lista vazia, que
    diria "não há nada")."""

    tasks: list[TripTaskRead] | None = None
    issues: list[TripIssueRead] | None = None
    collect: list[TripCollectRead] | None = None
    next_visit: NextVisitRead | None = None


class TripStopRead(RouteStopRead):
    # Só fornecedores/pontos de recolha: o texto livre dos materiais que fornecem.
    info: str | None = None
    # Só instalações.
    jobs: TripStopJobs | None = None


class TripVisibility(BaseModel):
    tasks: bool
    issues: bool
    material: bool
    visits: bool


class TripSummary(BaseModel):
    """Totais da deslocação. Cada total é `null` quando a secção correspondente
    não é visível ao utilizador (nunca 0)."""

    projects: int
    suppliers: int
    pickup_points: int
    operational_tasks: int | None = None
    overdue_tasks: int | None = None
    issues: int | None = None
    items_to_collect: int | None = None  # linhas de material (SKUs) no local


class TripPlanResponse(RouteOptimizationResponse):
    stops: list[TripStopRead]  # type: ignore[assignment]
    summary: TripSummary
    visibility: TripVisibility
