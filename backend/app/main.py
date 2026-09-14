from __future__ import annotations

from fastapi import FastAPI

from app.api.routes_health import router as health_router
from app.api.routes_me import router as me_router
from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description=(
        "Fase 0 — fundação técnica. Sem integrações reais ativas; ver "
        "docs/ARCHITECTURE_PROPOSAL.md e docs/DECISIONS.md no repositório."
    ),
)

app.include_router(health_router)
app.include_router(me_router)


@app.get("/")
def root() -> dict:
    return {"app": settings.app_name, "env": settings.app_env, "docs": "/docs"}
