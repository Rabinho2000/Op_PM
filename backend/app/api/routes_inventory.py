"""Endpoints de inventário central e de projeto. Toda a escrita passa por
`app/services/inventory.py` — nenhuma rota aqui manipula `InventoryMovement`
diretamente. Ver docs/INVENTORY_RULES.md para o contrato de negócio.
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.inventory import (
    MOVEMENT_AJUSTE,
    MOVEMENT_ENTRADA,
    InventoryCatalogHistory,
    InventoryItem,
    InventoryLocation,
    InventoryMovement,
    ProjectMaterialRequirement,
)
from app.models.people import Person
from app.models.project import Project
from app.schemas.inventory import (
    InventoryItemRead,
    InventoryLocationRead,
    InventoryMovementCreate,
    InventoryMovementRead,
    ProjectInventoryOperationCreate,
    ProjectInventorySummary,
    ProjectMaterialRequirementCreate,
    ProjectMaterialRequirementRead,
    ProjectMaterialRequirementUpdate,
    ProjectOnSiteRead,
)
from app.schemas.inventory_catalog import (
    InventoryCatalogHistoryRead,
    InventoryItemCreate,
    InventoryItemUpdate,
    InventoryLocationCreate,
    InventoryLocationUpdate,
    OpeningStockCreate,
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
    IdempotencyConflictError,
    InactiveInventoryReferenceError,
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
from app.services.projects import visible_projects_query
from app.services.inventory_catalog import (
    CatalogError,
    CentralLocationInvariantError,
    DuplicateCatalogValueError,
    InactiveReferenceError,
    create_inventory_item,
    create_inventory_location,
    deactivate_inventory_item,
    deactivate_inventory_location,
    update_inventory_item_atomic,
    update_inventory_location_atomic,
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


def _require_catalog(ctx: AuthContext) -> None:
    _require(ctx, "inventory.manage_catalog")


def _visible_project_ids(db: Session, ctx: AuthContext):
    return visible_projects_query(db, ctx).with_entities(Project.id).subquery()


def _filter_project_scope(query, project_column, db: Session, ctx: AuthContext):
    """Mantém stock sem projeto visível e restringe o restante ao âmbito de
    projetos efetivo. `inventory.manage_central`/`manage_catalog` não ampliam
    esta leitura: só `project.view_all` é global."""
    if ctx.has_permission("project.view_all"):
        return query
    project_ids = _visible_project_ids(db, ctx)
    return query.filter(
        or_(
            project_column.is_(None),
            project_column.in_(select(project_ids.c.id)),
        )
    )


def _filter_catalog_history_scope(query, db: Session, ctx: AuthContext):
    """Artigo de catálogo é global; histórico de localização segue o projeto
    associado à localização, incluindo a localização central sem projeto."""
    if ctx.has_permission("project.view_all"):
        return query
    project_ids = _visible_project_ids(db, ctx)
    return query.outerjoin(
        InventoryLocation,
        and_(
            InventoryCatalogHistory.entity_type == "location",
            InventoryCatalogHistory.entity_id == InventoryLocation.id,
        ),
    ).filter(
        or_(
            InventoryCatalogHistory.entity_type == "item",
            and_(
                InventoryCatalogHistory.entity_type == "location",
                or_(
                    InventoryLocation.project_id.is_(None),
                    InventoryLocation.project_id.in_(select(project_ids.c.id)),
                ),
            ),
        )
    )


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
    query = _filter_project_scope(db.query(InventoryLocation), InventoryLocation.project_id, db, ctx)
    return [InventoryLocationRead.model_validate(location) for location in query.order_by(InventoryLocation.name).all()]


@router.post("/locations", response_model=InventoryLocationRead, status_code=201)
def create_location_endpoint(
    body: InventoryLocationCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> InventoryLocationRead:
    _require_catalog(ctx)
    try:
        location = create_inventory_location(db, data=body.model_dump(), actor_person_id=ctx.person_id)
    except (DuplicateCatalogValueError, CentralLocationInvariantError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except InactiveReferenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CatalogError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return InventoryLocationRead.model_validate(location)


@router.patch("/locations/{location_id}", response_model=InventoryLocationRead)
def update_location_endpoint(
    location_id: uuid.UUID,
    body: InventoryLocationUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> InventoryLocationRead:
    _require_catalog(ctx)
    location = db.get(InventoryLocation, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Localização de inventário não encontrada.")
    changes = body.model_dump(exclude_unset=True)
    requested_active = changes.get("is_active")
    deactivate = requested_active is False
    if deactivate:
        changes.pop("is_active")
    try:
        location = update_inventory_location_atomic(
            db,
            location=location,
            changes=changes,
            deactivate=deactivate,
            actor_person_id=ctx.person_id,
        )
    except (DuplicateCatalogValueError, CentralLocationInvariantError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except InactiveReferenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CatalogError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return InventoryLocationRead.model_validate(location)


@router.post("/locations/{location_id}/deactivate", response_model=InventoryLocationRead)
def deactivate_location_endpoint(
    location_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> InventoryLocationRead:
    _require_catalog(ctx)
    location = db.get(InventoryLocation, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Localização de inventário não encontrada.")
    try:
        location = deactivate_inventory_location(db, location=location, actor_person_id=ctx.person_id)
    except CentralLocationInvariantError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CatalogError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return InventoryLocationRead.model_validate(location)


@router.post("/opening-stock", response_model=InventoryMovementRead, status_code=201)
def opening_stock_endpoint(
    body: OpeningStockCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> InventoryMovementRead:
    if not can_manage_central_inventory(ctx):
        raise HTTPException(status_code=403, detail="Sem permissão para registar stock inicial.")
    item = db.get(InventoryItem, body.item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Artigo de inventário não encontrado.")
    try:
        movement = enter_stock(
            db,
            item=item,
            quantity=body.quantity,
            created_by_person_id=ctx.person_id,
            reference=body.reference,
            idempotency_key=body.idempotency_key,
        )
    except InventoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _movement_to_read(db, movement)


@router.get("/catalog-history", response_model=list[InventoryCatalogHistoryRead])
def catalog_history_endpoint(
    entity_id: uuid.UUID | None = None,
    entity_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[InventoryCatalogHistoryRead]:
    _require(ctx, "inventory.view")
    query = _filter_catalog_history_scope(db.query(InventoryCatalogHistory), db, ctx)
    if entity_id is not None:
        query = query.filter(InventoryCatalogHistory.entity_id == entity_id)
    if entity_type is not None:
        if entity_type not in {"item", "location"}:
            raise HTTPException(status_code=422, detail="Tipo de entidade inválido.")
        query = query.filter(InventoryCatalogHistory.entity_type == entity_type)
    entries = query.order_by(InventoryCatalogHistory.changed_at.desc()).all()
    person_ids = {entry.changed_by_person_id for entry in entries}
    person_ids.discard(None)
    people = (
        {person.id: person.display_name for person in db.query(Person).filter(Person.id.in_(person_ids)).all()}
        if person_ids
        else {}
    )
    result = []
    for entry in entries:
        try:
            changes = json.loads(entry.changes_json)
        except json.JSONDecodeError:
            changes = {}
        result.append(
            InventoryCatalogHistoryRead(
                id=entry.id,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                action=entry.action,
                changes=changes if isinstance(changes, dict) else {},
                changed_by_person_id=entry.changed_by_person_id,
                changed_by_person_name=people.get(entry.changed_by_person_id),
                changed_at=entry.changed_at,
            )
        )
    return result


@router.post("/items", response_model=InventoryItemRead, status_code=201)
def create_item_endpoint(
    body: InventoryItemCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> InventoryItemRead:
    _require_catalog(ctx)
    try:
        item = create_inventory_item(db, data=body.model_dump(), actor_person_id=ctx.person_id)
    except DuplicateCatalogValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except InactiveReferenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CatalogError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _item_to_read(db, item)


@router.patch("/items/{item_id}", response_model=InventoryItemRead)
def update_item_endpoint(
    item_id: uuid.UUID,
    body: InventoryItemUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> InventoryItemRead:
    _require_catalog(ctx)
    item = db.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Artigo de inventário não encontrado.")
    changes = body.model_dump(exclude_unset=True)
    requested_active = changes.get("is_active")
    deactivate = requested_active is False
    if deactivate:
        changes.pop("is_active")
    try:
        item = update_inventory_item_atomic(
            db,
            item=item,
            changes=changes,
            deactivate=deactivate,
            actor_person_id=ctx.person_id,
        )
    except DuplicateCatalogValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except InactiveReferenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CatalogError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _item_to_read(db, item)


@router.post("/items/{item_id}/deactivate", response_model=InventoryItemRead)
def deactivate_item_endpoint(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> InventoryItemRead:
    _require_catalog(ctx)
    item = db.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Artigo de inventário não encontrado.")
    try:
        item = deactivate_inventory_item(db, item=item, actor_person_id=ctx.person_id)
    except CatalogError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _item_to_read(db, item)


@router.get("/movements", response_model=list[InventoryMovementRead])
def list_movements_endpoint(
    item_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    movement_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[InventoryMovementRead]:
    _require(ctx, "inventory.view")
    query = _filter_project_scope(db.query(InventoryMovement), InventoryMovement.project_id, db, ctx)
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
                location_id=body.location_id,
            )
        elif body.movement_type == MOVEMENT_AJUSTE:
            movement = adjust_stock(
                db,
                item=item,
                delta=body.quantity,
                created_by_person_id=ctx.person_id,
                reference=body.reference,
                idempotency_key=body.idempotency_key,
                location_id=body.location_id,
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
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except InactiveInventoryReferenceError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
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
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
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
