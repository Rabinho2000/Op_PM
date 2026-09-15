"""Endpoint único do dashboard inicial — um pedido devolve todos os
indicadores já calculados e já filtrados pela visibilidade do utilizador
autenticado (ver app/services/dashboard.py). O frontend nunca calcula
métricas a partir de listas completas — só apresenta o que este endpoint
devolve.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.dashboard import DashboardSummary
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext
from app.services.dashboard import compute_dashboard_summary

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def get_dashboard_summary(
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> DashboardSummary:
    return compute_dashboard_summary(db, ctx)
