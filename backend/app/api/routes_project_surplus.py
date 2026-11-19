"""Contratos de venda de excedente por projeto (0..n).

Âmbito: leitura = `project.view_licensing_data` + visibilidade do projeto;
escrita = `project.edit_licensing_data` + âmbito de edição (ver
app/security/permissions.py). Remoção lógica, com histórico append-only.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.no_echo_route import NoEchoRoute
from app.db import get_db
from app.schemas.project_data import SurplusContractCreate, SurplusContractRead, SurplusContractUpdate
from app.security.current_user import get_auth_context
from app.security.permissions import (
    AuthContext,
    can_edit_project_surplus_contracts,
    can_view_project_surplus_contracts,
)
from app.services.project_data import (
    create_surplus_contract,
    delete_surplus_contract,
    get_surplus_contract,
    list_surplus_contracts,
    update_surplus_contract,
)
from app.api.deps import get_visible_project_or_404
from app.models.project import Project

router = APIRouter(prefix="/api/projects", tags=["project-surplus"], route_class=NoEchoRoute)


@router.get("/{project_id}/surplus-contracts", response_model=list[SurplusContractRead])
def list_surplus_endpoint(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    project: Project = Depends(get_visible_project_or_404),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[SurplusContractRead]:
    if not can_view_project_surplus_contracts(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para ver contratos de excedente.")
    return [SurplusContractRead.model_validate(c) for c in list_surplus_contracts(db, project_id)]


@router.post("/{project_id}/surplus-contracts", response_model=SurplusContractRead, status_code=201)
def create_surplus_endpoint(
    project_id: uuid.UUID,
    body: SurplusContractCreate,
    db: Session = Depends(get_db),
    project: Project = Depends(get_visible_project_or_404),
    ctx: AuthContext = Depends(get_auth_context),
) -> SurplusContractRead:
    if not can_edit_project_surplus_contracts(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para editar contratos de excedente.")
    contract = create_surplus_contract(
        db,
        project_id=project_id,
        values=body.model_dump(exclude_unset=True),
        changed_by_person_id=ctx.person_id,
    )
    return SurplusContractRead.model_validate(contract)


@router.patch("/{project_id}/surplus-contracts/{contract_id}", response_model=SurplusContractRead)
def update_surplus_endpoint(
    project_id: uuid.UUID,
    contract_id: uuid.UUID,
    body: SurplusContractUpdate,
    db: Session = Depends(get_db),
    project: Project = Depends(get_visible_project_or_404),
    ctx: AuthContext = Depends(get_auth_context),
) -> SurplusContractRead:
    if not can_edit_project_surplus_contracts(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para editar contratos de excedente.")
    contract = get_surplus_contract(db, project_id, contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Contrato de excedente não encontrado.")
    contract = update_surplus_contract(
        db,
        contract=contract,
        changes=body.model_dump(exclude_unset=True),
        changed_by_person_id=ctx.person_id,
    )
    return SurplusContractRead.model_validate(contract)


@router.delete("/{project_id}/surplus-contracts/{contract_id}", status_code=204)
def delete_surplus_endpoint(
    project_id: uuid.UUID,
    contract_id: uuid.UUID,
    db: Session = Depends(get_db),
    project: Project = Depends(get_visible_project_or_404),
    ctx: AuthContext = Depends(get_auth_context),
) -> None:
    if not can_edit_project_surplus_contracts(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para editar contratos de excedente.")
    contract = get_surplus_contract(db, project_id, contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Contrato de excedente não encontrado.")
    delete_surplus_contract(db, contract=contract, deleted_by_person_id=ctx.person_id)
