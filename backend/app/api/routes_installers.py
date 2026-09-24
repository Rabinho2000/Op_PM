"""Instaladores e equipas (D-071). Ver `app/services/installers.py`.

Ver: quem consegue ver projetos (o nome do instalador faz parte da obra). Gerir
instaladores e equipas: `installer.manage`. Nunca se apagam — desativam-se, para
o histórico das obras continuar a fazer sentido.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.installer import Installer, InstallerTeam
from app.schemas.installers import (
    InstallerCreate,
    InstallerRead,
    InstallerTeamRead,
    InstallerUpdate,
    TeamCreate,
    TeamUpdate,
)
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, can_manage_installers, can_view_installers
from app.services import installers as service
from app.utils.text import normalize_key

router = APIRouter(prefix="/api/installers", tags=["installers"])


def _require_view(ctx: AuthContext) -> None:
    if not can_view_installers(ctx):
        raise HTTPException(status_code=403, detail="Sem permissão para ver os instaladores.")


def _require_manage(ctx: AuthContext) -> None:
    if not can_manage_installers(ctx):
        raise HTTPException(status_code=403, detail="Sem permissão para gerir instaladores e equipas.")


def _to_read(installer: Installer, by_installer: dict, by_team: dict) -> InstallerRead:
    return InstallerRead(
        id=installer.id,
        name=installer.name,
        is_active=installer.is_active,
        project_count=by_installer.get(installer.id, 0),
        teams=[
            InstallerTeamRead(
                id=t.id,
                name=t.name,
                leader_name=t.leader_name,
                leader_phone=t.leader_phone,
                is_active=t.is_active,
                project_count=by_team.get(t.id, 0),
            )
            for t in installer.teams
        ],
    )


def _read_one(db: Session, installer: Installer) -> InstallerRead:
    by_installer, by_team = service.project_counts_by_installer(db)
    return _to_read(installer, by_installer, by_team)


@router.get("", response_model=list[InstallerRead])
def list_installers_endpoint(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> list[InstallerRead]:
    _require_view(ctx)
    by_installer, by_team = service.project_counts_by_installer(db)
    installers = db.query(Installer).order_by(Installer.name_key).all()
    return [_to_read(i, by_installer, by_team) for i in installers]


@router.post("", response_model=InstallerRead, status_code=201)
def create_installer_endpoint(
    body: InstallerCreate, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> InstallerRead:
    _require_manage(ctx)
    if service.find_installer_by_name(db, body.name) is not None:
        raise HTTPException(status_code=409, detail="Já existe um instalador com este nome.")
    installer = Installer(name=body.name, name_key=normalize_key(body.name))
    db.add(installer)
    db.commit()
    db.refresh(installer)
    return _read_one(db, installer)


@router.patch("/{installer_id}", response_model=InstallerRead)
def update_installer_endpoint(
    installer_id: uuid.UUID,
    body: InstallerUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> InstallerRead:
    _require_manage(ctx)
    installer = db.get(Installer, installer_id)
    if installer is None:
        raise HTTPException(status_code=404, detail="Instalador não encontrado.")
    changes = body.model_dump(exclude_unset=True)
    for required in ("name", "is_active"):
        if required in changes and changes[required] is None:
            raise HTTPException(status_code=422, detail=f"O campo «{required}» não pode ser nulo.")
    if "name" in changes:
        if service.find_installer_by_name(db, changes["name"], exclude_id=installer.id) is not None:
            raise HTTPException(status_code=409, detail="Já existe um instalador com este nome.")
        installer.name = changes["name"]
        installer.name_key = normalize_key(changes["name"])
    if "is_active" in changes:
        installer.is_active = changes["is_active"]
    db.commit()
    db.refresh(installer)
    return _read_one(db, installer)


@router.post("/{installer_id}/teams", response_model=InstallerRead, status_code=201)
def create_team_endpoint(
    installer_id: uuid.UUID,
    body: TeamCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> InstallerRead:
    _require_manage(ctx)
    installer = db.get(Installer, installer_id)
    if installer is None:
        raise HTTPException(status_code=404, detail="Instalador não encontrado.")
    if service.find_team_by_name(db, installer.id, body.name) is not None:
        raise HTTPException(status_code=409, detail="Este instalador já tem uma equipa com este nome.")
    db.add(
        InstallerTeam(
            installer_id=installer.id,
            name=body.name,
            name_key=normalize_key(body.name),
            leader_name=body.leader_name,
            leader_phone=body.leader_phone,
        )
    )
    db.commit()
    db.refresh(installer)
    return _read_one(db, installer)


@router.patch("/{installer_id}/teams/{team_id}", response_model=InstallerRead)
def update_team_endpoint(
    installer_id: uuid.UUID,
    team_id: uuid.UUID,
    body: TeamUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> InstallerRead:
    _require_manage(ctx)
    team = db.get(InstallerTeam, team_id)
    if team is None or team.installer_id != installer_id:
        raise HTTPException(status_code=404, detail="Equipa não encontrada neste instalador.")
    changes = body.model_dump(exclude_unset=True)
    for required in ("name", "is_active"):
        if required in changes and changes[required] is None:
            raise HTTPException(status_code=422, detail=f"O campo «{required}» não pode ser nulo.")
    if "name" in changes:
        if service.find_team_by_name(db, installer_id, changes["name"], exclude_id=team.id) is not None:
            raise HTTPException(status_code=409, detail="Este instalador já tem uma equipa com este nome.")
        team.name = changes["name"]
        team.name_key = normalize_key(changes["name"])
    for field_name in ("leader_name", "leader_phone", "is_active"):
        if field_name in changes:
            setattr(team, field_name, changes[field_name])
    db.commit()
    installer = db.get(Installer, installer_id)
    db.refresh(installer)
    return _read_one(db, installer)
