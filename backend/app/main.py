from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_absences import router as absences_router
from app.api.routes_cable_designs import designs_router as cable_designs_router
from app.api.routes_cable_designs import projects_router as cable_projects_router
from app.api.routes_cable_tool import router as cable_tool_router
from app.api.routes_client_reports import router as client_reports_router
from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_health import router as health_router
from app.api.routes_holidays import router as holidays_router
from app.api.routes_installer_access import router as installer_access_router
from app.api.routes_imports import router as imports_router
from app.api.routes_inventory import project_router as project_inventory_router
from app.api.routes_inventory import router as inventory_router
from app.api.routes_inventory_visual import router as inventory_visual_router
from app.api.routes_material_requests import router as material_requests_router
from app.api.routes_map import router as map_router
from app.api.routes_me import router as me_router
from app.api.routes_migration import router as migration_router
from app.api.routes_people import router as people_router
from app.api.routes_performance import router as performance_router
from app.api.routes_planning import preferences_router as planning_preferences_router
from app.api.routes_planning import router as planning_router
from app.api.routes_project_credentials import router as project_credentials_router
from app.api.routes_project_data import router as project_data_router
from app.api.routes_safety_sheet import router as safety_sheet_router
from app.api.routes_project_sim_cards import router as project_sim_cards_router
from app.api.routes_project_surplus import router as project_surplus_router
from app.api.routes_projects import router as projects_router
from app.api.routes_project_photos import router as project_photos_router
from app.api.routes_project_payments import router as project_payments_router
from app.api.routes_requests import router as requests_router
from app.api.routes_project_list_views import preferences_router as project_list_preferences_router
from app.api.routes_project_list_views import views_router as project_list_views_router
from app.api.routes_process import router as process_router
from app.api.routes_process_alerts import router as process_alerts_router
from app.api.routes_my_process import router as my_process_router
from app.api.routes_support_delegations import router as support_delegations_router
from app.api.routes_installers import router as installers_router
from app.api.routes_suppliers import router as suppliers_router
from app.api.routes_works import router as works_router
from app.api.routes_works_preferences import router as works_preferences_router
from app.api.routes_works_saved_views import router as works_saved_views_router
from app.api.routes_tasks import router as tasks_router
from app.api.routes_task_list_views import preferences_router as task_list_preferences_router
from app.api.routes_task_list_views import views_router as task_list_views_router
from app.api.routes_time_bank import router as time_bank_router
from app.config import get_settings
from app.logging_setup import configure_logging

configure_logging()
settings = get_settings()
_docs_enabled = settings.resolved_api_docs_enabled()

app = FastAPI(
    title=settings.app_name,
    description=(
        "API do Op_PM (autenticação Microsoft Entra ID). Integrações: envio do "
        "relatório semanal por Microsoft Graph quando GRAPH_ENABLED=true "
        "(senão outbox local); ClickUp, Financial e Claude continuam mock. "
        "Ver README.md e docs/DECISIONS.md no repositório."
    ),
    # Fechada por omissão em instâncias com dados reais (API_DOCS_ENABLED).
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
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
app.include_router(client_reports_router)
app.include_router(projects_router)
app.include_router(project_photos_router)
app.include_router(project_payments_router)
app.include_router(requests_router)
app.include_router(cable_projects_router)
app.include_router(cable_designs_router)
app.include_router(cable_tool_router)
app.include_router(project_list_preferences_router)
app.include_router(project_list_views_router)
app.include_router(process_router)
app.include_router(my_process_router)
app.include_router(process_alerts_router)
app.include_router(support_delegations_router)
app.include_router(migration_router)
app.include_router(people_router)
app.include_router(tasks_router)
app.include_router(task_list_preferences_router)
app.include_router(task_list_views_router)
app.include_router(time_bank_router)
app.include_router(installer_access_router)
app.include_router(absences_router)
app.include_router(holidays_router)
app.include_router(dashboard_router)
app.include_router(inventory_router)
app.include_router(inventory_visual_router)
app.include_router(project_inventory_router)
app.include_router(material_requests_router)
app.include_router(project_data_router)
app.include_router(safety_sheet_router)
app.include_router(project_credentials_router)
app.include_router(project_surplus_router)
app.include_router(project_sim_cards_router)
app.include_router(map_router)
app.include_router(suppliers_router)
app.include_router(installers_router)
app.include_router(works_router)
app.include_router(works_preferences_router)
app.include_router(works_saved_views_router)
app.include_router(planning_router)
app.include_router(planning_preferences_router)
app.include_router(performance_router)
app.include_router(imports_router)


@app.get("/")
def root() -> dict:
    return {"app": settings.app_name, "env": settings.app_env, "docs": "/docs" if _docs_enabled else None}
