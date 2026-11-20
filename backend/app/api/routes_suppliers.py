"""Fornecedores (D-070): listagem com pesquisa e filtros, tipos de material,
criação e edição. Ver `app/services/suppliers.py` para as regras.

Quem vê: `supplier.view` — ou `map.view`, para não retirar a lista a quem já a
via através do mapa. Quem escreve: `supplier.manage`. Um fornecedor nunca é
apagado (há pedidos de material ligados): desativa-se com `is_active=false`.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.supplier import Supplier
from app.schemas.suppliers import (
    SupplierCreate,
    SupplierMaterialTypeRead,
    SupplierRead,
    SupplierUpdate,
)
from app.security.permissions import AuthContext
from app.services import suppliers as service
from app.security.guards import require_permission
from app.security.perm import Perm

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])


# `can_view_suppliers`: `supplier.view`, ou `map.view` (compatibilidade).
require_supplier_view = require_permission(
    Perm.SUPPLIER_VIEW, Perm.MAP_VIEW, detail="Sem permissão para ver os fornecedores."
)
require_supplier_create = require_permission(Perm.SUPPLIER_MANAGE, detail="Sem permissão para criar fornecedores.")
require_supplier_update = require_permission(Perm.SUPPLIER_MANAGE, detail="Sem permissão para editar fornecedores.")


@router.get("", response_model=list[SupplierRead])
def list_suppliers_endpoint(
    q: str | None = Query(default=None, description="Nome, morada, email, materiais ou tipo"),
    material_type: str | None = Query(default=None, description="Nome do tipo de material"),
    company_code: str | None = Query(default=None, description="solcor, verde_milenar ou unclassified"),
    is_active: bool | None = None,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_supplier_view),
) -> list[SupplierRead]:
    if company_code is not None and company_code not in ("solcor", "verde_milenar", "unclassified"):
        raise HTTPException(status_code=422, detail="Código de empresa inválido.")
    suppliers = service.list_suppliers(db, q=q, material_type=material_type, is_active=is_active, company_code=company_code)
    return [SupplierRead.model_validate(s) for s in suppliers]


@router.get("/material-types", response_model=list[SupplierMaterialTypeRead])
def list_material_types_endpoint(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(require_supplier_view)
) -> list[SupplierMaterialTypeRead]:
    return [
        SupplierMaterialTypeRead(id=t.id, name=t.name, active_suppliers=count)
        for t, count in service.list_material_types_with_counts(db)
    ]


@router.get("/{supplier_id}", response_model=SupplierRead)
def get_supplier_endpoint(
    supplier_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_supplier_view)
) -> SupplierRead:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado.")
    return SupplierRead.model_validate(supplier)


@router.post("", response_model=SupplierRead, status_code=201)
def create_supplier_endpoint(
    body: SupplierCreate, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_supplier_create)
) -> SupplierRead:
    if service.find_supplier_by_name(db, body.name) is not None:
        raise HTTPException(status_code=409, detail="Já existe um fornecedor com este nome.")
    supplier = service.create_supplier(db, body.model_dump())
    return SupplierRead.model_validate(supplier)


@router.patch("/{supplier_id}", response_model=SupplierRead)
def update_supplier_endpoint(
    supplier_id: uuid.UUID,
    body: SupplierUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_supplier_update),
) -> SupplierRead:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado.")
    changes = body.model_dump(exclude_unset=True)
    # Campos obrigatórios/booleanos: `null` explícito não faz sentido.
    for required in ("name", "is_active", "is_preferred", "materials", "notes"):
        if required in changes and changes[required] is None:
            raise HTTPException(status_code=422, detail=f"O campo «{required}» não pode ser nulo.")
    new_name = changes.get("name")
    if new_name is not None and service.find_supplier_by_name(db, new_name, exclude_id=supplier.id) is not None:
        raise HTTPException(status_code=409, detail="Já existe um fornecedor com este nome.")
    updated = service.update_supplier(db, supplier, changes)
    return SupplierRead.model_validate(updated)
