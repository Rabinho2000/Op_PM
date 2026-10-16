"""Endpoint único do dashboard inicial — um pedido devolve todos os
indicadores já calculados e já filtrados pela visibilidade do utilizador
autenticado (ver app/services/dashboard.py). O frontend nunca calcula
métricas a partir de listas completas — só apresenta o que este endpoint
devolve.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.dashboard import DashboardSummary
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, is_installer_readonly_scope
from app.services.dashboard import compute_dashboard_summary

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def get_dashboard_summary(
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> DashboardSummary:
    if is_installer_readonly_scope(ctx):
        raise HTTPException(status_code=403, detail="Sem permissão para ver o dashboard.")
    return compute_dashboard_summary(db, ctx)
