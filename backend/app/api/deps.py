"""Dependências FastAPI partilhadas entre routers (autorização e projeto visível)."""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.project import Project
from app.security.current_user import get_auth_context
from app.security.guards import require_permission
from app.security.perm import Perm
from app.security.permissions import AuthContext
from app.services.projects import get_visible_project

# Inventário: o texto do 403 sempre foi `Sem permissão: Permissão em falta: <código>`.
require_inventory_view = require_permission(Perm.INVENTORY_VIEW, detail="Sem permissão", with_reason=True)
require_inventory_catalog = require_permission(Perm.INVENTORY_MANAGE_CATALOG, detail="Sem permissão", with_reason=True)


# --- projeto visível -------------------------------------------------------

PROJECT_NOT_FOUND = "Projeto não encontrado ou sem permissão para o ver."


def visible_project_or_404(db: Session, ctx: AuthContext, project_id: uuid.UUID) -> Project:
    """O projeto, se existir, não estiver apagado e o utilizador o puder ver
    (mesmo âmbito SQL das listagens). Caso contrário 404 — nunca 403, para não
    revelar a existência de projetos fora do âmbito. Um projeto apagado
    logicamente conta como inexistente."""
    project = get_visible_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=PROJECT_NOT_FOUND)
    return project


def get_visible_project_or_404(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> Project:
    """Dependência: `project: Project = Depends(get_visible_project_or_404)` numa
    rota com `{project_id}` no caminho. Corre antes das dependências declaradas
    depois dela (p.ex. `require_permission`), por isso um projeto invisível dá
    404 mesmo a quem não tem a permissão."""
    return visible_project_or_404(db, ctx, project_id)
