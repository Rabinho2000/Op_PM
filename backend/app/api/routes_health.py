from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "app_env": settings.app_env,
        "database_dialect": db.bind.dialect.name if db.bind else "unknown",
        # Informativo para o frontend (D-051): o banner "modo demonstração"
        # e o login de desenvolvimento só fazem sentido quando o próprio
        # backend os aceita — a barreira real continua em
        # app/config.py e app/security/current_user.py.
        "demo_mode": settings.demo_mode and settings.app_env == "local",
        "dev_login_available": settings.app_env in ("local", "test") and not settings.auth_enabled,
        "integrations": {
            "graph_enabled": settings.graph_enabled,
            "clickup_enabled": settings.clickup_enabled,
            "financial_enabled": settings.financial_enabled,
            "claude_enabled": settings.claude_enabled,
        },
    }
