"""Regras de negócio do catálogo de inventário."""
from __future__ import annotations

import json
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory import (
    LOCATION_TYPE_CENTRAL,
    LOCATION_TYPE_PROJECT,
    InventoryCatalogHistory,
    InventoryItem,
    InventoryLocation,
)
from app.models.project import Project
from app.models.supplier import Supplier


class CatalogError(ValueError):
    pass


class DuplicateCatalogValueError(CatalogError):
    pass


class InactiveReferenceError(CatalogError):
    pass


class CentralLocationInvariantError(CatalogError):
    pass


def _raise_catalog_integrity_error(
    exc: IntegrityError, *, location: bool = False, central: bool = False
) -> None:
    message = str(exc.orig).lower()
    if central and (
        "uq_inventory_locations_one_active_central" in message
        or "inventory_locations.location_type" in message
    ):
        raise CentralLocationInvariantError("Só pode existir uma localização central ativa.") from exc
    if "unique" in message or "uq_inventory" in message:
        if location:
            raise DuplicateCatalogValueError("Já existe uma localização com este código.") from exc
        raise DuplicateCatalogValueError("Já existe um artigo com este SKU.") from exc
    raise CatalogError("Não foi possível guardar o catálogo de inventário.") from exc


def _history(
    db: Session,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    changes: dict[str, object],
    actor_person_id: uuid.UUID | None,
) -> None:
    def _json_value(value: object) -> object:
        if isinstance(value, (Decimal, uuid.UUID)):
            return str(value)
        if isinstance(value, dict):
            return {str(key): _json_value(nested) for key, nested in value.items()}
        if isinstance(value, (list, tuple)):
            return [_json_value(nested) for nested in value]
        return value

    serializable = {key: _json_value(value) for key, value in changes.items()}
    db.add(
        InventoryCatalogHistory(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            changes_json=json.dumps(serializable, ensure_ascii=False, sort_keys=True),
            changed_by_person_id=actor_person_id,
        )
    )


def _validate_supplier(db: Session, supplier_id: uuid.UUID | None) -> None:
    if supplier_id is None:
        return
    supplier = db.get(Supplier, supplier_id)
    if supplier is None or not supplier.is_active:
        raise InactiveReferenceError("O fornecedor indicado não existe ou está inativo.")


def _find_item_by_sku(db: Session, sku: str, *, exclude_id: uuid.UUID | None = None) -> InventoryItem | None:
    query = db.query(InventoryItem).filter(func.lower(InventoryItem.sku) == sku.lower())
    if exclude_id is not None:
        query = query.filter(InventoryItem.id != exclude_id)
    return query.one_or_none()


def create_inventory_item(
    db: Session,
    *,
    data: dict[str, object],
    actor_person_id: uuid.UUID | None,
) -> InventoryItem:
    sku = str(data["sku"])
    if _find_item_by_sku(db, sku) is not None:
        raise DuplicateCatalogValueError("Já existe um artigo com este SKU.")
    _validate_supplier(db, data.get("preferred_supplier_id"))  # type: ignore[arg-type]
    item = InventoryItem(**data)
    try:
        db.add(item)
        db.flush()
        _history(
            db,
            entity_type="item",
            entity_id=item.id,
            action="create",
            changes=data,
            actor_person_id=actor_person_id,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _raise_catalog_integrity_error(exc)
    db.refresh(item)
    return item


def update_inventory_item(
    db: Session,
    *,
    item: InventoryItem,
    changes: dict[str, object],
    actor_person_id: uuid.UUID | None,
) -> InventoryItem:
    return update_inventory_item_atomic(
        db,
        item=item,
        changes=changes,
        deactivate=False,
        actor_person_id=actor_person_id,
    )


def deactivate_inventory_item(
    db: Session,
    *,
    item: InventoryItem,
    actor_person_id: uuid.UUID | None,
) -> InventoryItem:
    return update_inventory_item_atomic(
        db,
        item=item,
        changes={},
        deactivate=True,
        actor_person_id=actor_person_id,
    )


def update_inventory_item_atomic(
    db: Session,
    *,
    item: InventoryItem,
    changes: dict[str, object],
    deactivate: bool,
    actor_person_id: uuid.UUID | None,
) -> InventoryItem:
    """Apply an edit and optional deactivation in one transaction."""
    locked_item = db.execute(
        select(InventoryItem).where(InventoryItem.id == item.id).with_for_update()
    ).scalar_one_or_none()
    if locked_item is None:
        raise CatalogError("O artigo de inventário não existe.")
    db.refresh(locked_item)
    item = locked_item
    if "sku" in changes:
        sku = str(changes["sku"])
        if _find_item_by_sku(db, sku, exclude_id=item.id) is not None:
            raise DuplicateCatalogValueError("Já existe um artigo com este SKU.")
    if "preferred_supplier_id" in changes:
        _validate_supplier(db, changes["preferred_supplier_id"])  # type: ignore[arg-type]

    edit_changes: dict[str, object] = {}
    for field_name, new_value in changes.items():
        old_value = getattr(item, field_name)
        if old_value != new_value:
            edit_changes[field_name] = {"old": old_value, "new": new_value}
            setattr(item, field_name, new_value)

    deactivate_changes: dict[str, object] = {}
    if deactivate and item.is_active:
        deactivate_changes = {"is_active": {"old": True, "new": False}}
        item.is_active = False

    try:
        if edit_changes or deactivate_changes:
            db.flush()
            if edit_changes:
                _history(
                    db,
                    entity_type="item",
                    entity_id=item.id,
                    action="edit",
                    changes=edit_changes,
                    actor_person_id=actor_person_id,
                )
            if deactivate_changes:
                _history(
                    db,
                    entity_type="item",
                    entity_id=item.id,
                    action="deactivate",
                    changes=deactivate_changes,
                    actor_person_id=actor_person_id,
                )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _raise_catalog_integrity_error(exc)
    db.refresh(item)
    return item


def _find_location_by_code(
    db: Session, code: str, *, exclude_id: uuid.UUID | None = None
) -> InventoryLocation | None:
    query = db.query(InventoryLocation).filter(func.lower(InventoryLocation.code) == code.lower())
    if exclude_id is not None:
        query = query.filter(InventoryLocation.id != exclude_id)
    return query.one_or_none()


def _active_central_locations(db: Session) -> list[InventoryLocation]:
    return (
        db.query(InventoryLocation)
        .filter(
            InventoryLocation.location_type == LOCATION_TYPE_CENTRAL,
            InventoryLocation.is_active.is_(True),
        )
        .all()
    )


def _validate_location_reference(
    db: Session, *, location_type: str, project_id: uuid.UUID | None
) -> None:
    if location_type == LOCATION_TYPE_PROJECT:
        if project_id is None:
            raise CatalogError("Uma localização de projeto tem de indicar o projeto.")
        project = db.get(Project, project_id)
        if project is None or not project.is_active:
            raise InactiveReferenceError("O projeto indicado não existe ou está inativo.")
    elif project_id is not None:
        raise CatalogError("Só uma localização de projeto pode indicar um projeto.")


def _validate_exactly_one_active_central(db: Session, *, proposed_active_central_count: int) -> None:
    if proposed_active_central_count != 1:
        raise CentralLocationInvariantError("Tem de existir exatamente uma localização central ativa.")


def create_inventory_location(
    db: Session,
    *,
    data: dict[str, object],
    actor_person_id: uuid.UUID | None,
) -> InventoryLocation:
    code = str(data["code"])
    if _find_location_by_code(db, code) is not None:
        raise DuplicateCatalogValueError("Já existe uma localização com este código.")
    location_type = str(data["location_type"])
    project_id = data.get("project_id")  # type: ignore[assignment]
    _validate_location_reference(db, location_type=location_type, project_id=project_id)  # type: ignore[arg-type]
    active_central_count = len(_active_central_locations(db))
    if location_type == LOCATION_TYPE_CENTRAL:
        if active_central_count != 0:
            raise CentralLocationInvariantError("Só pode existir uma localização central ativa.")
    elif active_central_count != 1:
        raise CentralLocationInvariantError("Crie primeiro uma localização central ativa.")
    location = InventoryLocation(**data)
    try:
        db.add(location)
        db.flush()
        _history(
            db,
            entity_type="location",
            entity_id=location.id,
            action="create",
            changes={**data, "is_active": True},
            actor_person_id=actor_person_id,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _raise_catalog_integrity_error(
            exc,
            location=True,
            central=location_type == LOCATION_TYPE_CENTRAL,
        )
    db.refresh(location)
    return location


def update_inventory_location(
    db: Session,
    *,
    location: InventoryLocation,
    changes: dict[str, object],
    actor_person_id: uuid.UUID | None,
) -> InventoryLocation:
    return update_inventory_location_atomic(
        db,
        location=location,
        changes=changes,
        deactivate=False,
        actor_person_id=actor_person_id,
    )


def update_inventory_location_atomic(
    db: Session,
    *,
    location: InventoryLocation,
    changes: dict[str, object],
    deactivate: bool,
    actor_person_id: uuid.UUID | None,
) -> InventoryLocation:
    """Apply a location edit and optional deactivation in one commit."""
    locked_location = db.execute(
        select(InventoryLocation).where(InventoryLocation.id == location.id).with_for_update()
    ).scalar_one_or_none()
    if locked_location is None:
        raise CatalogError("A localização de inventário não existe.")
    db.refresh(locked_location)
    location = locked_location
    if "code" in changes:
        code = str(changes["code"])
        if _find_location_by_code(db, code, exclude_id=location.id) is not None:
            raise DuplicateCatalogValueError("Já existe uma localização com este código.")

    location_type = str(changes.get("location_type", location.location_type))
    project_id = changes.get("project_id", location.project_id)  # type: ignore[assignment]
    requested_active = changes.get("is_active", location.is_active)
    final_active = bool(requested_active) and not deactivate
    _validate_location_reference(db, location_type=location_type, project_id=project_id)  # type: ignore[arg-type]

    active_centrals = _active_central_locations(db)
    proposed_active_central_count = len(active_centrals)
    if location.id in {current.id for current in active_centrals}:
        proposed_active_central_count -= 1
    if final_active and location_type == LOCATION_TYPE_CENTRAL:
        proposed_active_central_count += 1
    _validate_exactly_one_active_central(db, proposed_active_central_count=proposed_active_central_count)

    edit_changes: dict[str, object] = {}
    for field_name, new_value in changes.items():
        old_value = getattr(location, field_name)
        if old_value != new_value:
            edit_changes[field_name] = {"old": old_value, "new": new_value}
            setattr(location, field_name, new_value)

    deactivate_changes: dict[str, object] = {}
    if deactivate and location.is_active:
        deactivate_changes = {"is_active": {"old": True, "new": False}}
        location.is_active = False

    try:
        if edit_changes or deactivate_changes:
            db.flush()
            if edit_changes:
                _history(
                    db,
                    entity_type="location",
                    entity_id=location.id,
                    action="edit",
                    changes=edit_changes,
                    actor_person_id=actor_person_id,
                )
            if deactivate_changes:
                _history(
                    db,
                    entity_type="location",
                    entity_id=location.id,
                    action="deactivate",
                    changes=deactivate_changes,
                    actor_person_id=actor_person_id,
                )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _raise_catalog_integrity_error(
            exc,
            location=True,
            central=final_active and location_type == LOCATION_TYPE_CENTRAL,
        )
    db.refresh(location)
    return location


def deactivate_inventory_location(
    db: Session,
    *,
    location: InventoryLocation,
    actor_person_id: uuid.UUID | None,
) -> InventoryLocation:
    return update_inventory_location_atomic(
        db,
        location=location,
        changes={},
        deactivate=True,
        actor_person_id=actor_person_id,
    )
