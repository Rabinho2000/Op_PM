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
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, can_manage_suppliers, can_view_suppliers
from app.services import suppliers as service

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])


def _require_view(ctx: AuthContext) -> None:
    if not can_view_suppliers(ctx):
        raise HTTPException(status_code=403, detail="Sem permissão para ver os fornecedores.")


def _require_manage(ctx: AuthContext, action: str) -> None:
    if not can_manage_suppliers(ctx):
        raise HTTPException(status_code=403, detail=f"Sem permissão para {action} fornecedores.")


@router.get("", response_model=list[SupplierRead])
def list_suppliers_endpoint(
    q: str | None = Query(default=None, description="Nome, morada, email, materiais ou tipo"),
    material_type: str | None = Query(default=None, description="Nome do tipo de material"),
    is_active: bool | None = None,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[SupplierRead]:
    _require_view(ctx)
    suppliers = service.list_suppliers(db, q=q, material_type=material_type, is_active=is_active)
    return [SupplierRead.model_validate(s) for s in suppliers]


@router.get("/material-types", response_model=list[SupplierMaterialTypeRead])
def list_material_types_endpoint(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> list[SupplierMaterialTypeRead]:
    _require_view(ctx)
    return [
        SupplierMaterialTypeRead(id=t.id, name=t.name, active_suppliers=count)
        for t, count in service.list_material_types_with_counts(db)
    ]


@router.get("/{supplier_id}", response_model=SupplierRead)
def get_supplier_endpoint(
    supplier_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> SupplierRead:
    _require_view(ctx)
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado.")
    return SupplierRead.model_validate(supplier)


@router.post("", response_model=SupplierRead, status_code=201)
def create_supplier_endpoint(
    body: SupplierCreate, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> SupplierRead:
    _require_manage(ctx, "criar")
    if service.find_supplier_by_name(db, body.name) is not None:
        raise HTTPException(status_code=409, detail="Já existe um fornecedor com este nome.")
    supplier = service.create_supplier(db, body.model_dump())
    return SupplierRead.model_validate(supplier)


@router.patch("/{supplier_id}", response_model=SupplierRead)
def update_supplier_endpoint(
    supplier_id: uuid.UUID,
    body: SupplierUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> SupplierRead:
    _require_manage(ctx, "editar")
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
