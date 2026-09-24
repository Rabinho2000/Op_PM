"""Fornecedores e tipos de material (D-070). Toda a escrita passa por aqui —
as rotas e o comando de carregamento inicial usam as mesmas funções, por isso
a normalização de nomes e de tipos é uma só."""
from __future__ import annotations

import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.supplier import Supplier, SupplierMaterialType, supplier_material_type_links
from app.utils.text import clean_display, normalize_key


def get_or_create_material_types(db: Session, names: list[str]) -> list[SupplierMaterialType]:
    """Devolve os tipos pedidos, criando os que ainda não existem. Duplicados
    (mesmo nome normalizado) e nomes vazios são ignorados."""
    result: list[SupplierMaterialType] = []
    seen: set[str] = set()
    for raw in names:
        display = clean_display(raw)
        key = normalize_key(display)
        if not key or key in seen:
            continue
        seen.add(key)
        material_type = db.query(SupplierMaterialType).filter(SupplierMaterialType.name_key == key).one_or_none()
        if material_type is None:
            material_type = SupplierMaterialType(name=display, name_key=key)
            db.add(material_type)
            db.flush()
        result.append(material_type)
    return result


def find_supplier_by_name(db: Session, name: str, *, exclude_id: uuid.UUID | None = None) -> Supplier | None:
    key = normalize_key(name)
    query = db.query(Supplier)
    if exclude_id is not None:
        query = query.filter(Supplier.id != exclude_id)
    for supplier in query.all():
        if normalize_key(supplier.name) == key:
            return supplier
    return None


def list_suppliers(
    db: Session,
    *,
    q: str | None = None,
    material_type: str | None = None,
    is_active: bool | None = None,
) -> list[Supplier]:
    query = db.query(Supplier)
    if is_active is not None:
        query = query.filter(Supplier.is_active.is_(is_active))
    if material_type:
        key = normalize_key(material_type)
        query = query.filter(
            Supplier.id.in_(
                db.query(supplier_material_type_links.c.supplier_id)
                .join(
                    SupplierMaterialType,
                    SupplierMaterialType.id == supplier_material_type_links.c.material_type_id,
                )
                .filter(SupplierMaterialType.name_key == key)
            )
        )
    suppliers = query.order_by(func.lower(Supplier.name)).all()
    if q and q.strip():
        # Pesquisa sem maiúsculas nem acentos ("betao" encontra "Betão"). Feita
        # em Python porque o SQL não normaliza acentos de forma portável, e a
        # lista de fornecedores é pequena; os tipos já vêm carregados (selectin).
        needle = normalize_key(q)
        suppliers = [s for s in suppliers if needle in _search_haystack(s)]
    return suppliers


def _search_haystack(supplier: Supplier) -> str:
    parts = [
        supplier.name,
        supplier.address,
        supplier.email,
        supplier.website,
        supplier.contact,
        supplier.materials,
        *(t.name for t in supplier.material_types),
    ]
    return normalize_key(" ".join(p for p in parts if p))


def list_material_types_with_counts(db: Session) -> list[tuple[SupplierMaterialType, int]]:
    """Todos os tipos, com o número de fornecedores **ativos** de cada um."""
    counts = dict(
        db.query(supplier_material_type_links.c.material_type_id, func.count(Supplier.id))
        .join(Supplier, Supplier.id == supplier_material_type_links.c.supplier_id)
        .filter(Supplier.is_active.is_(True))
        .group_by(supplier_material_type_links.c.material_type_id)
        .all()
    )
    types = db.query(SupplierMaterialType).order_by(SupplierMaterialType.name_key).all()
    return [(t, counts.get(t.id, 0)) for t in types]


def create_supplier(db: Session, data: dict) -> Supplier:
    material_types = data.pop("material_types", [])
    supplier = Supplier(**data)
    supplier.material_types = get_or_create_material_types(db, material_types)
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


def update_supplier(db: Session, supplier: Supplier, changes: dict) -> Supplier:
    material_types = changes.pop("material_types", None)
    for field_name, value in changes.items():
        setattr(supplier, field_name, value)
    if material_types is not None:
        supplier.material_types = get_or_create_material_types(db, material_types)
    db.commit()
    db.refresh(supplier)
    return supplier
