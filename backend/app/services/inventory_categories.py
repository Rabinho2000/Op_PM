"""Vocabulário de categorias de inventário: leitura, criação e resolução.

O vocabulário é aberto: categorias de origem (`INVENTORY_CATEGORIES`, também
semeadas na tabela) + categorias criadas por utilizadores + valores já usados
por artigos. Um artigo só pode receber uma categoria deste vocabulário.
"""
from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory import INVENTORY_CATEGORIES, InventoryCategory, InventoryItem
from app.schemas.inventory_catalog import (
    LEGACY_INVENTORY_CATEGORY_ALIASES,
    RESERVED_UNASSIGNED_INVENTORY_CATEGORY,
    InventoryCategoryError,
    InventoryCategoryKeyTooLongError as InventoryCategoryKeyTooLongError,
    inventory_category_key,
    inventory_category_key_for_read,
    is_reserved_unassigned_inventory_category,
    normalize_inventory_category,
    normalize_inventory_category_name,
    normalize_inventory_category_for_read,
    validate_inventory_category_input,
)

RESERVED_CATEGORY_MESSAGE = (
    "A categoria 'Outros/Sem categoria' é reservada; utilize 'Outros' para o grupo incorporado."
)
UNKNOWN_CATEGORY_MESSAGE = "Categoria inexistente. Escolha uma categoria da lista ou crie-a primeiro."


class DuplicateInventoryCategoryError(InventoryCategoryError):
    pass


class UnknownInventoryCategoryError(InventoryCategoryError):
    pass


class ReservedInventoryCategoryError(InventoryCategoryError):
    pass


def list_inventory_category_names(db: Session) -> list[str]:
    """Categorias de origem, criadas e já usadas por artigos, sem duplicados.

    Valores históricos de artigos entram na lista sem migração de dados.
    """
    names: list[str] = []
    keys: set[str] = set()

    def add(value: str | None) -> None:
        category = normalize_inventory_category_for_read(value) if value else None
        if not category:
            return
        key = inventory_category_key_for_read(category)
        if key not in keys:
            keys.add(key)
            names.append(category)

    for category in INVENTORY_CATEGORIES:
        add(category)
    for (name,) in db.query(InventoryCategory.name).order_by(InventoryCategory.name).all():
        add(name)
    used = (
        db.query(InventoryItem.category)
        .filter(InventoryItem.category.is_not(None))
        .distinct()
        .order_by(InventoryItem.category)
        .all()
    )
    for (category,) in used:
        add(category)
    return names


def resolve_category_name(db: Session, value: object) -> str:
    """Nome canónico de uma categoria que já existe no vocabulário.

    Aceita também categorias legadas só com pontuação (já gravadas), que a
    criação rejeita. Levanta `InventoryCategoryError` se a entrada exceder os
    limites ou a categoria não existir.
    """
    try:
        cleaned = validate_inventory_category_input(value, required=True)
    except InventoryCategoryKeyTooLongError:
        raise
    except ValueError:
        cleaned = normalize_inventory_category_name(value, required=True)
    assert cleaned is not None
    canonical = normalize_inventory_category(cleaned)
    assert canonical is not None
    key = inventory_category_key_for_read(canonical)
    for name in list_inventory_category_names(db):
        if inventory_category_key_for_read(name) == key:
            return name
    raise UnknownInventoryCategoryError(UNKNOWN_CATEGORY_MESSAGE)


def resolve_inventory_category(db: Session, value: object) -> str | None:
    """Nome canónico da categoria a atribuir a um artigo (None = sem categoria).

    Levanta `InventoryCategoryError` se a entrada for inválida, reservada ou
    não existir no vocabulário.
    """
    cleaned = validate_inventory_category_input(value)
    if cleaned is None:
        return None
    if is_reserved_unassigned_inventory_category(cleaned):
        raise ReservedInventoryCategoryError(RESERVED_CATEGORY_MESSAGE)
    return resolve_category_name(db, cleaned)


def create_inventory_category(
    db: Session,
    *,
    name: str,
    actor_person_id: uuid.UUID | None,
) -> InventoryCategory:
    cleaned = validate_inventory_category_input(name, required=True)
    assert cleaned is not None
    key = inventory_category_key(cleaned)

    # O nome normalizado não pode coincidir com uma categoria de origem, um
    # alias, uma categoria criada, uma categoria já usada por artigos nem com
    # o rótulo reservado do grupo "Outros".
    taken = {inventory_category_key_for_read(value) for value in list_inventory_category_names(db)}
    taken.update(inventory_category_key(alias) for alias in LEGACY_INVENTORY_CATEGORY_ALIASES)
    taken.add(inventory_category_key(RESERVED_UNASSIGNED_INVENTORY_CATEGORY))
    if key in taken:
        raise DuplicateInventoryCategoryError("Já existe uma categoria com este nome.")

    category = InventoryCategory(
        name=cleaned, normalized_key=key, created_by_person_id=actor_person_id
    )
    try:
        db.add(category)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateInventoryCategoryError("Já existe uma categoria com este nome.") from exc
    db.refresh(category)
    return category
