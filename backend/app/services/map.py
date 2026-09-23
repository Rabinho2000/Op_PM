"""Dados do mapa operacional: um único payload com projetos (com e sem
coordenadas), fornecedores, pontos de recolha e pendências — sempre já
filtrado pela visibilidade do utilizador (nunca a lista completa enviada
para o cliente filtrar). Ver docs/MAP_AND_PLANNING.md.

`attention` (green|yellow|red) é sempre calculado aqui a partir de dados
que o próprio utilizador pode consultar — nunca persistido (ver
docs/DECISIONS.md, "Mapa operacional — attention derivado"). Todo o
carregamento usa um número de queries independente do número de projetos
(nunca uma query de tarefas/inventário por projeto dentro de um ciclo) —
ver `_load_tasks_by_project`/`_load_material_presence_by_project`.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.inventory import (
    MOVEMENT_CONSUMO,
    MOVEMENT_LIBERTA_RESERVA,
    MOVEMENT_RESERVA,
    InventoryMovement,
)
from app.models.map_ops import PickupPoint, ProjectIssue
from app.models.project import Project
from app.models.supplier import Supplier
from app.models.task import (
    OPEN_TASK_STATUSES,
    OPERATIONAL_TASK_CATEGORIES,
    PRIORITY_URGENT,
    STATUS_BLOCKED,
    Task,
)
from app.security.permissions import AuthContext, can_view_project_issue
from app.services.projects import ProjectTaskSummary, compute_project_task_summary_from_tasks, visible_projects_query

ATTENTION_GREEN = "green"
ATTENTION_YELLOW = "yellow"
ATTENTION_RED = "red"


@dataclasses.dataclass
class NextOperationalTask:
    id: uuid.UUID
    title: str
    due_date: dt.date | None
    priority: str


@dataclasses.dataclass
class MapProject:
    project: Project
    task_summary: ProjectTaskSummary
    open_tasks_count: int
    issues_count: int
    attention: str
    operational_tasks_count: int
    overdue_operational_tasks_count: int
    blocked_operational_tasks_count: int
    urgent_operational_tasks_count: int
    next_operational_task: NextOperationalTask | None
    material_visible: bool
    has_material_on_site: bool | None
    material_sku_count: int | None


def _load_tasks_by_project(db: Session, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Task]]:
    """Uma única query para todos os projetos visíveis — nunca uma query
    de tarefas por projeto (o padrão N+1 já conhecido de
    `routes_projects.py`, explicitamente não reproduzido aqui)."""
    by_project: dict[uuid.UUID, list[Task]] = defaultdict(list)
    if not project_ids:
        return by_project
    tasks = db.query(Task).filter(Task.project_id.in_(project_ids)).all()
    for task in tasks:
        by_project[task.project_id].append(task)
    return by_project


def _load_issue_counts_by_project(db: Session, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not project_ids:
        return {}
    rows = (
        db.query(ProjectIssue.project_id, func.count(ProjectIssue.id))
        .filter(ProjectIssue.project_id.in_(project_ids), ProjectIssue.status == "aberta")
        .group_by(ProjectIssue.project_id)
        .all()
    )
    return {project_id: count for project_id, count in rows}


def _load_material_presence_by_project(db: Session, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Número de SKUs com saldo reservado líquido positivo, por projeto —
    uma única query agregada (GROUP BY project_id, item_id), nunca uma
    chamada a `reserved_for_project` por (item, projeto) dentro de um
    ciclo. "Material no local" reaproveita o saldo reservado líquido
    (reserva − liberta_reserva − consumo) já modelado por
    `app/services/inventory.py:reserved_for_project` — este MVP não
    distingue "reservado" de "fisicamente entregue no local" (nenhum
    movimento de entrega dedicado existe ainda); ver docs/DECISIONS.md."""
    if not project_ids:
        return {}
    # SQLite/PostgreSQL portável: soma com sinal via CASE (não `FILTER`,
    # que o SQLite não suporta).
    signed_quantity = case(
        (InventoryMovement.movement_type == MOVEMENT_RESERVA, InventoryMovement.quantity),
        (InventoryMovement.movement_type == MOVEMENT_LIBERTA_RESERVA, -InventoryMovement.quantity),
        (InventoryMovement.movement_type == MOVEMENT_CONSUMO, -InventoryMovement.quantity),
        else_=0,
    )
    reserved_expr = func.sum(signed_quantity)
    rows = (
        db.query(InventoryMovement.project_id, InventoryMovement.item_id, reserved_expr.label("reserved"))
        .filter(
            InventoryMovement.project_id.in_(project_ids),
            InventoryMovement.movement_type.in_((MOVEMENT_RESERVA, MOVEMENT_LIBERTA_RESERVA, MOVEMENT_CONSUMO)),
        )
        .group_by(InventoryMovement.project_id, InventoryMovement.item_id)
        .having(reserved_expr > 0)
        .all()
    )
    sku_counts: dict[uuid.UUID, int] = defaultdict(int)
    for project_id, _item_id, reserved in rows:
        if reserved and Decimal(reserved) > 0:
            sku_counts[project_id] += 1
    return sku_counts


def _next_operational_task(tasks: list[Task]) -> NextOperationalTask | None:
    """Determinístico: due_date mais próxima primeiro, sem due_date por
    último, desempate por created_at e depois por id (nunca a ordem
    acidental devolvida pela BD)."""
    open_operational = [
        t for t in tasks if t.category in OPERATIONAL_TASK_CATEGORIES and t.status in OPEN_TASK_STATUSES
    ]
    if not open_operational:
        return None
    chosen = min(
        open_operational,
        key=lambda t: (t.due_date is None, t.due_date or dt.date.max, t.created_at, str(t.id)),
    )
    return NextOperationalTask(id=chosen.id, title=chosen.title, due_date=chosen.due_date, priority=chosen.priority)


def _compute_attention(
    *, operational_open: list[Task], material_visible: bool, has_material_on_site: bool | None
) -> str:
    """Nunca combina workflow/documentação com dívida operacional (ver
    docs/DECISIONS.md) — só `field`/`material` (OPERATIONAL_TASK_CATEGORIES)
    e, quando visível, material físico no local."""
    is_red = any(
        t.status == STATUS_BLOCKED or t.priority == PRIORITY_URGENT or t.is_overdue for t in operational_open
    )
    if is_red:
        return ATTENTION_RED
    if operational_open:
        return ATTENTION_YELLOW
    if material_visible and has_material_on_site:
        return ATTENTION_YELLOW
    return ATTENTION_GREEN


def get_map_projects(db: Session, ctx: AuthContext) -> tuple[list[MapProject], list[MapProject]]:
    """Devolve (com_coordenadas, sem_coordenadas) — sempre a partir de
    `visible_projects_query`, nunca a lista completa de projetos. Número
    de queries fixo, independente do número de projetos: 1 para os
    projetos, 1 para as tarefas, 1 para pendências, 1 para inventário."""
    projects = visible_projects_query(db, ctx).filter(Project.is_active.is_(True)).all()
    project_ids = [p.id for p in projects]

    tasks_by_project = _load_tasks_by_project(db, project_ids)
    issue_counts_by_project = _load_issue_counts_by_project(db, project_ids)
    material_visible = ctx.has_permission("inventory.view")
    # Só executa a query de inventário se o utilizador puder ver o
    # resultado — evita trabalho e, sobretudo, nunca deixa o cálculo
    # depender de dados que o pedido não devolve (ver _compute_attention).
    material_sku_counts = _load_material_presence_by_project(db, project_ids) if material_visible else {}

    with_coords: list[MapProject] = []
    without_coords: list[MapProject] = []
    for project in projects:
        tasks = tasks_by_project.get(project.id, [])
        operational_open = [
            t for t in tasks if t.category in OPERATIONAL_TASK_CATEGORIES and t.status in OPEN_TASK_STATUSES
        ]
        sku_count = material_sku_counts.get(project.id, 0) if material_visible else None
        has_material_on_site = (sku_count is not None and sku_count > 0) if material_visible else None

        entry = MapProject(
            project=project,
            task_summary=compute_project_task_summary_from_tasks(tasks),
            open_tasks_count=sum(1 for t in tasks if t.status in OPEN_TASK_STATUSES),
            issues_count=issue_counts_by_project.get(project.id, 0),
            attention=_compute_attention(
                operational_open=operational_open,
                material_visible=material_visible,
                has_material_on_site=has_material_on_site,
            ),
            operational_tasks_count=len(operational_open),
            overdue_operational_tasks_count=sum(1 for t in operational_open if t.is_overdue),
            blocked_operational_tasks_count=sum(1 for t in operational_open if t.status == STATUS_BLOCKED),
            urgent_operational_tasks_count=sum(1 for t in operational_open if t.priority == PRIORITY_URGENT),
            next_operational_task=_next_operational_task(tasks),
            material_visible=material_visible,
            has_material_on_site=has_material_on_site,
            material_sku_count=sku_count,
        )
        if project.has_coordinates:
            with_coords.append(entry)
        else:
            without_coords.append(entry)
    return with_coords, without_coords


@dataclasses.dataclass
class MapSummary:
    visible_active_projects: int
    mapped_projects: int
    unmapped_projects: int
    map_coverage_percent: float
    green_projects: int
    yellow_projects: int
    red_projects: int
    operational_clean_percent: float
    projects_with_material: int


def compute_map_summary(with_coords: list[MapProject], without_coords: list[MapProject]) -> MapSummary:
    """Duas métricas deliberadamente separadas (nunca uma só "limpeza"
    enganadora — ver docs/DECISIONS.md): cobertura de coordenadas
    (`map_coverage_percent`) é um problema de dados, distinto do estado
    operacional (`operational_clean_percent`). Ambas sobre o mesmo
    denominador: projetos ativos visíveis (mapeados + sem coordenadas)."""
    all_entries = with_coords + without_coords
    total = len(all_entries)
    mapped = len(with_coords)
    green = sum(1 for e in all_entries if e.attention == ATTENTION_GREEN)
    yellow = sum(1 for e in all_entries if e.attention == ATTENTION_YELLOW)
    red = sum(1 for e in all_entries if e.attention == ATTENTION_RED)
    with_material = sum(1 for e in all_entries if e.has_material_on_site)
    return MapSummary(
        visible_active_projects=total,
        mapped_projects=mapped,
        unmapped_projects=total - mapped,
        map_coverage_percent=round(100 * mapped / total, 1) if total else 0.0,
        green_projects=green,
        yellow_projects=yellow,
        red_projects=red,
        operational_clean_percent=round(100 * green / total, 1) if total else 0.0,
        projects_with_material=with_material,
    )


def get_visible_suppliers(db: Session) -> list[Supplier]:
    return db.query(Supplier).filter(Supplier.is_active.is_(True)).order_by(Supplier.name).all()


def get_visible_pickup_points(db: Session) -> list[PickupPoint]:
    return db.query(PickupPoint).filter(PickupPoint.is_active.is_(True)).order_by(PickupPoint.name).all()


def get_visible_issues(db: Session, ctx: AuthContext) -> list[ProjectIssue]:
    """Filtra sempre por `can_view_project_issue` — nunca a lista completa
    de pendências, mesmo as marcadas `visible_on_map=True`."""
    issues = (
        db.query(ProjectIssue)
        .filter(ProjectIssue.visible_on_map.is_(True))
        .order_by(ProjectIssue.created_at.desc())
        .all()
    )
    return [issue for issue in issues if can_view_project_issue(ctx, issue.project)]


def list_project_issues(db: Session, project_id: uuid.UUID) -> list[ProjectIssue]:
    return (
        db.query(ProjectIssue)
        .filter(ProjectIssue.project_id == project_id)
        .order_by(ProjectIssue.created_at.desc())
        .all()
    )


def create_project_issue(
    db: Session,
    *,
    project_id: uuid.UUID,
    description: str,
    category: str,
    priority: str,
    lat: float | None,
    lon: float | None,
    notes: str,
    created_by_person_id: uuid.UUID | None,
) -> ProjectIssue:
    issue = ProjectIssue(
        project_id=project_id,
        description=description,
        category=category,
        priority=priority,
        lat=lat,
        lon=lon,
        notes=notes,
        created_by_person_id=created_by_person_id,
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return issue


def update_project_issue(db: Session, *, issue: ProjectIssue, changes: dict) -> ProjectIssue:
    for field_name, value in changes.items():
        setattr(issue, field_name, value)
    db.commit()
    db.refresh(issue)
    return issue


def convert_issue_to_task(
    db: Session, *, issue: ProjectIssue, title: str, created_by_person_id: uuid.UUID | None
) -> Task:
    """Cria uma `Task` a partir da pendência e liga `related_task_id` —
    nunca duplica a entidade: a pendência continua a existir para controlo
    do mapa, a tarefa passa a ser o item de trabalho a executar."""
    task = Task(
        project_id=issue.project_id,
        title=title,
        task_type="custom",
        description=issue.description,
        priority=issue.priority,
        assigned_to_person_id=issue.assigned_to_person_id,
        due_date=issue.due_date,
        created_by_person_id=created_by_person_id,
    )
    db.add(task)
    db.flush()
    issue.related_task_id = task.id
    db.commit()
    db.refresh(task)
    return task
