from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.installer_access import InstallerInventoryPage, InstallerInventoryRow
from app.schemas.installers import InstallerAccessInstallerRead, InstallerAccessTeamRead
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext
from app.services.installer_access import list_assigned_installers
from app.services.installer_inventory import list_installer_inventory

router = APIRouter(prefix="/api/installer-access", tags=["installer-access"])


@router.get("/teams", response_model=list[InstallerAccessInstallerRead])
def assigned_teams_endpoint(
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    if not ctx.has_permission("installer_team.view_assigned_installer"):
        raise HTTPException(status_code=403, detail="Sem permissão para ver as equipas associadas.")
    return [
        InstallerAccessInstallerRead(
            id=installer.id,
            name=installer.name,
            is_active=installer.is_active,
            teams=[
                InstallerAccessTeamRead(
                    id=team.id,
                    installer_id=installer.id,
                    name=team.name,
                    is_active=team.is_active,
                )
                for team in sorted(installer.teams, key=lambda item: (item.name_key, str(item.id)))
            ],
        )
        for installer in list_assigned_installers(db, ctx)
    ]


@router.get("/inventory", response_model=InstallerInventoryPage)
def assigned_inventory_endpoint(
    project_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    if not ctx.has_permission("inventory.view_assigned_installer"):
        raise HTTPException(status_code=403, detail="Sem permissão para ver o inventário associado.")
    try:
        items, total = list_installer_inventory(db, ctx, project_id=project_id, limit=limit, offset=offset)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.") from exc
    return InstallerInventoryPage(
        items=[InstallerInventoryRow.model_validate(item) for item in items],
        total=total,
        offset=offset,
        limit=limit,
    )
