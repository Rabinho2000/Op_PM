"""Endpoints de inventário central e de projeto. Toda a escrita passa por
`app/services/inventory.py` — nenhuma rota aqui manipula `InventoryMovement`
diretamente. Ver docs/INVENTORY_RULES.md para o contrato de negócio.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.inventory import (
    MOVEMENT_AJUSTE,
    MOVEMENT_ENTRADA,
    InventoryItem,
    InventoryLocation,
    InventoryMovement,
    ProjectMaterialRequirement,
)
from app.models.project import Project
from app.schemas.inventory import (
    InventoryItemRead,
    InventoryLocationRead,
    InventoryMovementCreate,
    InventoryMovementRead,
    ProjectInventoryOperationCreate,
    ProjectInventorySummary,
    ProjectMaterialRequirementCreate,
    ProjectOnSiteRead,
    ProjectMaterialRequirementRead,
    ProjectMaterialRequirementUpdate,
)
from app.security.current_user import get_auth_context
from app.security.permissions import (
    AuthContext,
    PermissionDenied,
    can_allocate_inventory_for_project,
    can_collect_inventory_for_project,
    can_consume_inventory_for_project,
    can_deliver_inventory_for_project,
    can_manage_central_inventory,
    can_manage_material_requirements,
    can_release_inventory_for_project,
    can_view_project,
)
from app.services.inventory import (
    InsufficientReservationError,
    InsufficientStockError,
    InventoryError,
    adjust_stock,
    collect_from_project,
    consume_from_project,
    create_material_requirement,
    deliver_to_project,
    enter_stock,
    item_balance,
    material_requirement_status,
    on_site_balances_by_project,
    release_reservation,
    reserve_for_project,
    return_to_stock,
    update_material_requirement,
)

router = APIRouter(prefix="/api/inventory", tags=["inventory"])
project_router = APIRouter(prefix="/api/projects/{project_id}/inventory", tags=["inventory"])


def _item_to_read(db: Session, item: InventoryItem) -> InventoryItemRead:
    data = InventoryItemRead.model_validate(item)
    balance = item_balance(db, item)
    data.physical_stock = balance.physical_stock
    data.available_stock = balance.available_stock
    data.total_reserved = balance.total_reserved
    data.below_min_stock = balance.physical_stock < item.min_stock
    return data


def _movement_to_read(db: Session, movement: InventoryMovement) -> InventoryMovementRead:
    data = InventoryMovementRead.model_validate(movement)
    item = db.get(InventoryItem, movement.item_id)
    data.item_name = item.name if item else None
    if movement.project_id:
        project = db.get(Project, movement.project_id)
        data.project_name = project.name if project else None
    return data


def _require(ctx: AuthContext, permission_code: str) -> None:
    try:
        ctx.require(permission_code)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=f"Sem permissão: {exc}")


def _get_project_or_404(db: Session, project_id: uuid.UUID, ctx: AuthContext) -> Project:
    project = db.get(Project, project_id)
    if project is None or not can_view_project(ctx, project):
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")
    return project


@router.get("/summary", response_model=list[InventoryItemRead])
def inventory_summary_endpoint(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> list[InventoryItemRead]:
    _require(ctx, "inventory.view")
    items = db.query(InventoryItem).filter(InventoryItem.is_active.is_(True)).order_by(InventoryItem.name).all()
    return [_item_to_read(db, item) for item in items]


@router.get("/items", response_model=list[InventoryItemRead])
def list_items_endpoint(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> list[InventoryItemRead]:
    _require(ctx, "inventory.view")
    items = db.query(InventoryItem).order_by(InventoryItem.name).all()
    return [_item_to_read(db, item) for item in items]


@router.get("/locations", response_model=list[InventoryLocationRead])
def list_locations_endpoint(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> list[InventoryLocationRead]:
    _require(ctx, "inventory.view")
    return db.query(InventoryLocation).order_by(InventoryLocation.name).all()


@router.get("/movements", response_model=list[InventoryMovementRead])
def list_movements_endpoint(
    item_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    movement_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[InventoryMovementRead]:
    _require(ctx, "inventory.view")
    query = db.query(InventoryMovement)
    if item_id is not None:
        query = query.filter(InventoryMovement.item_id == item_id)
    if project_id is not None:
        query = query.filter(InventoryMovement.project_id == project_id)
    if movement_type is not None:
        query = query.filter(InventoryMovement.movement_type == movement_type)
    movements = query.order_by(InventoryMovement.created_at.desc()).all()
    return [_movement_to_read(db, m) for m in movements]


@router.post("/movements", response_model=InventoryMovementRead, status_code=201)
def create_central_movement_endpoint(
    body: InventoryMovementCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> InventoryMovementRead:
    if not can_manage_central_inventory(ctx):
        raise HTTPException(status_code=403, detail="Sem permissão para alterar o stock central.")
    item = db.get(InventoryItem, body.item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item de inventário não encontrado.")
    try:
        if body.movement_type == MOVEMENT_ENTRADA:
            movement = enter_stock(
                db,
                item=item,
                quantity=body.quantity,
                created_by_person_id=ctx.person_id,
                reference=body.reference,
                unit_cost=body.unit_cost,
                idempotency_key=body.idempotency_key,
            )
        elif body.movement_type == MOVEMENT_AJUSTE:
            movement = adjust_stock(
                db,
                item=item,
                delta=body.quantity,
                created_by_person_id=ctx.person_id,
                reference=body.reference,
                idempotency_key=body.idempotency_key,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Tipo de movimento '{body.movement_type}' não é suportado aqui — use "
                    "/api/projects/{id}/inventory/reserve|consume|release."
                ),
            )
    except InsufficientStockError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except InventoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _movement_to_read(db, movement)


@project_router.get("", response_model=ProjectInventorySummary)
def project_inventory_summary_endpoint(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectInventorySummary:
    project = _get_project_or_404(db, project_id, ctx)
    _require(ctx, "inventory.view")

    requirements = (
        db.query(ProjectMaterialRequirement)
        .filter(ProjectMaterialRequirement.project_id == project.id)
        .all()
    )
    requirement_reads = []
    for req in requirements:
        item = db.get(InventoryItem, req.item_id)
        status = material_requirement_status(
            db, project_id=project.id, item=item, quantity_required=req.quantity_required
        )
        data = ProjectMaterialRequirementRead.model_validate(req)
        data.item_name = item.name if item else None
        data.item_unit = item.unit if item else None
        data.reserved = status.reserved
        data.consumed = status.consumed
        data.missing = status.missing
        data.available_stock_sufficient = status.available_stock_sufficient
        requirement_reads.append(data)

    reservations = (
        db.query(InventoryMovement)
        .filter(InventoryMovement.project_id == project.id)
        .order_by(InventoryMovement.created_at.desc())
        .all()
    )
    on_site_balances = on_site_balances_by_project(db, [project.id]).get(project.id, {})
    items_by_id = (
        {i.id: i for i in db.query(InventoryItem).filter(InventoryItem.id.in_(list(on_site_balances))).all()}
        if on_site_balances
        else {}
    )
    on_site = [
        ProjectOnSiteRead(
            item_id=item_id,
            item_name=items_by_id[item_id].name if item_id in items_by_id else None,
            item_unit=items_by_id[item_id].unit if item_id in items_by_id else None,
            quantity=quantity,
        )
        for item_id, quantity in sorted(
            on_site_balances.items(), key=lambda kv: (items_by_id[kv[0]].name if kv[0] in items_by_id else "", str(kv[0]))
        )
    ]
    return ProjectInventorySummary(
        project_id=project.id,
        requirements=requirement_reads,
        reservations=[_movement_to_read(db, m) for m in reservations],
        on_site=on_site,
    )


@project_router.post("/requirements", response_model=ProjectMaterialRequirementRead, status_code=201)
def create_requirement_endpoint(
    project_id: uuid.UUID,
    body: ProjectMaterialRequirementCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectMaterialRequirementRead:
    project = _get_project_or_404(db, project_id, ctx)
    if not can_manage_material_requirements(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para gerir necessidades deste projeto.")
    item = db.get(InventoryItem, body.item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item de inventário não encontrado.")
    try:
        requirement = create_material_requirement(
            db,
            project_id=project.id,
            item_id=item.id,
            quantity_required=body.quantity_required,
            notes=body.notes,
            created_by_person_id=ctx.person_id,
        )
    except InventoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    status = material_requirement_status(
        db, project_id=project.id, item=item, quantity_required=requirement.quantity_required
    )
    data = ProjectMaterialRequirementRead.model_validate(requirement)
    data.item_name = item.name
    data.item_unit = item.unit
    data.reserved = status.reserved
    data.consumed = status.consumed
    data.missing = status.missing
    data.available_stock_sufficient = status.available_stock_sufficient
    return data


@project_router.patch("/requirements/{requirement_id}", response_model=ProjectMaterialRequirementRead)
def update_requirement_endpoint(
    project_id: uuid.UUID,
    requirement_id: uuid.UUID,
    body: ProjectMaterialRequirementUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectMaterialRequirementRead:
    project = _get_project_or_404(db, project_id, ctx)
    if not can_manage_material_requirements(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para gerir necessidades deste projeto.")
    requirement = db.get(ProjectMaterialRequirement, requirement_id)
    if requirement is None or requirement.project_id != project.id:
        raise HTTPException(status_code=404, detail="Necessidade de material não encontrada.")
    try:
        updated = update_material_requirement(
            db, requirement=requirement, quantity_required=body.quantity_required, notes=body.notes
        )
    except InventoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    item = db.get(InventoryItem, updated.item_id)
    status = material_requirement_status(
        db, project_id=project.id, item=item, quantity_required=updated.quantity_required
    )
    data = ProjectMaterialRequirementRead.model_validate(updated)
    data.item_name = item.name if item else None
    data.item_unit = item.unit if item else None
    data.reserved = status.reserved
    data.consumed = status.consumed
    data.missing = status.missing
    data.available_stock_sufficient = status.available_stock_sufficient
    return data


def _project_operation(
    *,
    project_id: uuid.UUID,
    body: ProjectInventoryOperationCreate,
    db: Session,
    ctx: AuthContext,
    permission_check,
    operation,
) -> InventoryMovementRead:
    project = _get_project_or_404(db, project_id, ctx)
    if not permission_check(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para esta operação de inventário no projeto.")
    item = db.get(InventoryItem, body.item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item de inventário não encontrado.")
    try:
        movement = operation(
            db,
            item=item,
            project_id=project.id,
            quantity=body.quantity,
            created_by_person_id=ctx.person_id,
            reference=body.reference,
            idempotency_key=body.idempotency_key,
        )
    except (InsufficientStockError, InsufficientReservationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except InventoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _movement_to_read(db, movement)


@project_router.post("/reserve", response_model=InventoryMovementRead, status_code=201)
def reserve_endpoint(
    project_id: uuid.UUID,
    body: ProjectInventoryOperationCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> InventoryMovementRead:
    return _project_operation(
        project_id=project_id,
        body=body,
        db=db,
        ctx=ctx,
        permission_check=can_allocate_inventory_for_project,
        operation=reserve_for_project,
    )


@project_router.post("/consume", response_model=InventoryMovementRead, status_code=201)
def consume_endpoint(
    project_id: uuid.UUID,
    body: ProjectInventoryOperationCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> InventoryMovementRead:
    return _project_operation(
        project_id=project_id,
        body=body,
        db=db,
        ctx=ctx,
        permission_check=can_consume_inventory_for_project,
        operation=consume_from_project,
    )


@project_router.post("/release", response_model=InventoryMovementRead, status_code=201)
def release_endpoint(
    project_id: uuid.UUID,
    body: ProjectInventoryOperationCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> InventoryMovementRead:
    return _project_operation(
        project_id=project_id,
        body=body,
        db=db,
        ctx=ctx,
        permission_check=can_release_inventory_for_project,
        operation=release_reservation,
    )


@project_router.post("/return", response_model=InventoryMovementRead, status_code=201)
def return_endpoint(
    project_id: uuid.UUID,
    body: ProjectInventoryOperationCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> InventoryMovementRead:
    # Devolução usa a mesma permissão que consumo (é a operação inversa).
    return _project_operation(
        project_id=project_id,
        body=body,
        db=db,
        ctx=ctx,
        permission_check=can_consume_inventory_for_project,
        operation=return_to_stock,
    )


@project_router.post("/deliver", response_model=InventoryMovementRead, status_code=201)
def deliver_endpoint(
    project_id: uuid.UUID,
    body: ProjectInventoryOperationCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> InventoryMovementRead:
    """Material que passou a estar na instalação (D-064). Sem limite pela
    reserva; não altera stock central nem reserva."""
    return _project_operation(
        project_id=project_id,
        body=body,
        db=db,
        ctx=ctx,
        permission_check=can_deliver_inventory_for_project,
        operation=deliver_to_project,
    )


@project_router.post("/collect", response_model=InventoryMovementRead, status_code=201)
def collect_endpoint(
    project_id: uuid.UUID,
    body: ProjectInventoryOperationCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> InventoryMovementRead:
    """Material que deixou de estar na instalação (D-064). Não pode exceder o
    que está no local; não liberta a reserva."""
    return _project_operation(
        project_id=project_id,
        body=body,
        db=db,
        ctx=ctx,
        permission_check=can_collect_inventory_for_project,
        operation=collect_from_project,
    )
