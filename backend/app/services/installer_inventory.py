from __future__ import annotations

import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.inventory import (
    InventoryItem,
    InventoryLocation,
    InventoryMovement,
    MOVEMENT_CONSUMO,
    MOVEMENT_DEVOLUCAO,
    MOVEMENT_ENTREGA,
    MOVEMENT_LIBERTA_RESERVA,
    MOVEMENT_RECOLHA,
    MOVEMENT_RESERVA,
    ProjectMaterialRequirement,
)
from app.models.project import Project
from app.security.permissions import AuthContext
from app.services.projects import visible_projects_query


def list_installer_inventory(
    db: Session,
    ctx: AuthContext,
    *,
    project_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
):
    visible = visible_projects_query(db, ctx)
    if project_id is not None:
        if visible.filter(Project.id == project_id).one_or_none() is None:
            raise LookupError("Projeto não encontrado.")
        visible = visible.filter(Project.id == project_id)
    visible_ids = visible.with_entities(Project.id).subquery()
    projects = visible.order_by(Project.name, Project.id).all()
    if not projects:
        return [], 0

    keys: dict[tuple[uuid.UUID, uuid.UUID], dict] = {}
    requirements = (
        db.query(ProjectMaterialRequirement, Project, InventoryItem)
        .join(Project, Project.id == ProjectMaterialRequirement.project_id)
        .join(InventoryItem, InventoryItem.id == ProjectMaterialRequirement.item_id)
        .filter(ProjectMaterialRequirement.project_id.in_(select(visible_ids.c.id)))
        .all()
    )
    for requirement, project, item in requirements:
        keys[(project.id, item.id)] = {
            "project_id": project.id,
            "project_name": project.name,
            "item_name": item.name,
            "unit": item.unit,
            "required_quantity": Decimal(requirement.quantity_required or 0),
            "reserved_quantity": Decimal("0"),
            "consumed_quantity": Decimal("0"),
            "delivered_quantity": Decimal("0"),
        }

    movement_rows = (
        db.query(InventoryMovement.project_id, InventoryMovement.item_id, InventoryMovement.movement_type, func.sum(InventoryMovement.quantity))
        .join(Project, Project.id == InventoryMovement.project_id)
        .filter(InventoryMovement.project_id.in_(select(visible_ids.c.id)))
        .group_by(InventoryMovement.project_id, InventoryMovement.item_id, InventoryMovement.movement_type)
        .all()
    )
    item_ids = {item_id for _project_id, item_id, _kind, _quantity in movement_rows}
    items = {item.id: item for item in db.query(InventoryItem).filter(InventoryItem.id.in_(item_ids)).all()} if item_ids else {}
    project_names = {project.id: project.name for project in projects}
    for project_key, item_id, movement_type, quantity in movement_rows:
        if item_id not in items or project_key not in project_names:
            continue
        key = (project_key, item_id)
        row = keys.setdefault(
            key,
            {
                "project_id": project_key,
                "project_name": project_names[project_key],
                "item_name": items[item_id].name,
                "unit": items[item_id].unit,
                "required_quantity": Decimal("0"),
                "reserved_quantity": Decimal("0"),
                "consumed_quantity": Decimal("0"),
                "delivered_quantity": Decimal("0"),
            },
        )
        amount = Decimal(quantity or 0)
        if movement_type == MOVEMENT_RESERVA:
            row["reserved_quantity"] += amount
        elif movement_type == MOVEMENT_LIBERTA_RESERVA:
            row["reserved_quantity"] -= amount
        elif movement_type == MOVEMENT_CONSUMO:
            row["consumed_quantity"] += amount
        elif movement_type == MOVEMENT_DEVOLUCAO:
            row["consumed_quantity"] -= amount
        elif movement_type == MOVEMENT_ENTREGA:
            row["delivered_quantity"] += amount
        elif movement_type == MOVEMENT_RECOLHA:
            row["delivered_quantity"] -= amount

    labels: dict[uuid.UUID, list[str]] = defaultdict(list)
    for location in (
        db.query(InventoryLocation)
        .filter(
            InventoryLocation.project_id.in_(select(visible_ids.c.id)),
            InventoryLocation.is_active.is_(True),
        )
        .order_by(InventoryLocation.name, InventoryLocation.id)
        .all()
    ):
        labels[location.project_id].append(location.name)
    rows = []
    for row in sorted(keys.values(), key=lambda item: (item["project_name"], item["item_name"], str(item["project_id"]))):
        row["locations"] = [{"label": label} for label in labels.get(row["project_id"], [])]
        rows.append(row)
    total = len(rows)
    return rows[offset : offset + limit], total
