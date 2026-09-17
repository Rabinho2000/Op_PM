from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_absences import router as absences_router
from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_health import router as health_router
from app.api.routes_inventory import project_router as project_inventory_router
from app.api.routes_inventory import router as inventory_router
from app.api.routes_map import router as map_router
from app.api.routes_me import router as me_router
from app.api.routes_migration import router as migration_router
from app.api.routes_people import router as people_router
from app.api.routes_performance import router as performance_router
from app.api.routes_planning import router as planning_router
from app.api.routes_project_data import router as project_data_router
from app.api.routes_projects import router as projects_router
from app.api.routes_tasks import router as tasks_router
from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description=(
        "Fase 1 — autenticação real, CRUD de projetos, resolução de "
        "migração. Nenhuma integração externa real ativa ainda "
        "(Graph/ClickUp/Financial/Claude continuam mock/fallback); "
        "nenhum dado de produção migrado. Ver docs/ARCHITECTURE_PROPOSAL.md "
        "e docs/DECISIONS.md no repositório."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.resolved_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(me_router)
app.include_router(projects_router)
app.include_router(migration_router)
app.include_router(people_router)
app.include_router(tasks_router)
app.include_router(absences_router)
app.include_router(dashboard_router)
app.include_router(inventory_router)
app.include_router(project_inventory_router)
app.include_router(project_data_router)
app.include_router(map_router)
app.include_router(planning_router)
app.include_router(performance_router)


@app.get("/")
def root() -> dict:
    return {"app": settings.app_name, "env": settings.app_env, "docs": "/docs"}
