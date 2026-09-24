"""Endpoints de projeto: listagem/filtros, detalhe, edição autorizada, e
histórico. Toda a escrita passa por `app/services/projects.py` — nenhuma
rota aqui manipula `Project`/`ProjectHistory` diretamente.
"""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.people import Person
from app.models.project import Project, ProjectHistory
from app.schemas.installers import WorkPlanUpdate
from app.schemas.projects import (
    LifecycleStatusRead,
    ProjectHistoryRead,
    ProjectRead,
    ProjectStatusChange,
    ProjectStatusChangeResult,
    ProjectUpdate,
)
from app.security.current_user import get_auth_context
from app.security.permissions import (
    AuthContext,
    PermissionDenied,
    can_change_project_status,
    can_create_task,
    can_edit_project,
    can_plan_project_work,
)
from app.security.project_fields import PM_EDITABLE_PROJECT_FIELDS
from app.services.installers import PlanError, update_work_plan
from app.services.project_lifecycle import LIFECYCLE_FLOW, LIFECYCLE_STATUS_CODES, LIFECYCLE_STATUSES
from app.services.projects import (
    change_lifecycle_status,
    compute_project_task_summary,
    get_visible_project,
    list_projects,
)
from app.services.projects import update_project as update_project_service

router = APIRouter(prefix="/api/projects", tags=["projects"])

PROJECT_STATUSES = frozenset({"nao_iniciado", "em_curso", "concluido"})


def _editable_fields(ctx: AuthContext, project: Project) -> list[str]:
    """Mesma regra de app/services/projects.py:update_project (D-028)."""
    if not can_edit_project(ctx, project):
        return []
    if ctx.has_permission("project.edit_all"):
        return sorted(ProjectUpdate.model_fields)
    return sorted(PM_EDITABLE_PROJECT_FIELDS)


def _to_read(db: Session, project: Project, ctx: AuthContext) -> ProjectRead:
    data = ProjectRead.model_validate(project)
    data.pm_display_name = project.pm.display_name if project.pm else None
    data.has_pm = project.has_pm
    data.has_email = project.has_email
    data.has_coordinates = project.has_coordinates
    data.has_contact = project.has_contact

    summary = compute_project_task_summary(db, project.id)
    data.status = summary.status
    data.next_task_title = summary.next_task_title
    data.next_task_due_date = summary.next_task_due_date
    data.overdue_tasks_count = summary.overdue_tasks_count
    data.workflow_progress_percent = summary.workflow_progress_percent
    data.photos_pending_warning = summary.photos_pending_warning

    data.editable_fields = _editable_fields(ctx, project)
    data.can_manage_tasks = can_create_task(ctx, project)
    data.can_change_status = can_change_project_status(ctx, project)
    data.can_plan_work = can_plan_project_work(ctx, project)
    data.installer_name = project.installer.name if project.installer else None
    data.installer_team_name = project.installer_team.name if project.installer_team else None
    data.installer_team_leader_name = project.installer_team.leader_name if project.installer_team else None
    return data


@router.get("", response_model=list[ProjectRead])
def list_projects_endpoint(
    pm_person_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    q: str | None = Query(default=None, description="Pesquisa por nome/cliente/contacto"),
    status: str | None = Query(default=None, description="nao_iniciado | em_curso | concluido"),
    start_from: dt.date | None = Query(default=None, description="Data de início a partir de (inclusive)"),
    start_to: dt.date | None = Query(default=None, description="Data de início até (inclusive)"),
    lifecycle_status: list[str] | None = Query(
        default=None, description="Estado do ciclo de vida (repetível: mostra os que estiverem em qualquer um)"
    ),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[ProjectRead]:
    if status is not None and status not in PROJECT_STATUSES:
        raise HTTPException(status_code=400, detail=f"Estado de projeto inválido: {status!r}")
    invalid = sorted(set(lifecycle_status or []) - LIFECYCLE_STATUS_CODES)
    if invalid:
        raise HTTPException(status_code=400, detail=f"Estado do ciclo de vida inválido: {', '.join(invalid)}")
    projects = list_projects(
        db,
        ctx,
        pm_person_id=pm_person_id,
        is_active=is_active,
        search=q,
        start_from=start_from,
        start_to=start_to,
        lifecycle_statuses=lifecycle_status,
    )
    result = [_to_read(db, p, ctx) for p in projects]
    # O estado é derivado das tarefas (compute_project_task_summary), por
    # isso o filtro aplica-se depois do cálculo — nunca uma segunda regra.
    if status is not None:
        result = [r for r in result if r.status == status]
    return result


@router.get("/lifecycle-statuses", response_model=list[LifecycleStatusRead])
def list_lifecycle_statuses_endpoint(ctx: AuthContext = Depends(get_auth_context)) -> list[LifecycleStatusRead]:
    """Lista única de estados (código, rótulo, posição na sequência normal) —
    a UI lê-a daqui em vez de a duplicar."""
    return [
        LifecycleStatusRead(
            code=code,
            label=label,
            flow_position=LIFECYCLE_FLOW.index(code) + 1 if code in LIFECYCLE_FLOW else None,
        )
        for code, label in LIFECYCLE_STATUSES
    ]


@router.get("/{project_id}", response_model=ProjectRead)
def get_project_endpoint(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectRead:
    project = get_visible_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")
    return _to_read(db, project, ctx)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project_endpoint(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectRead:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    try:
        updated = update_project_service(db, project=project, changes=body, ctx=ctx)
    except PermissionDenied as exc:
        # str(exc) inclui, quando aplicável, a lista de campos
        # administrativos recusados (D-028) — não é uma fuga de
        # informação sensível, o próprio pedido já continha esses campos.
        raise HTTPException(status_code=403, detail=f"Sem permissão para editar este projeto: {exc}")
    return _to_read(db, updated, ctx)


@router.patch("/{project_id}/status", response_model=ProjectStatusChangeResult)
def change_project_status_endpoint(
    project_id: uuid.UUID,
    body: ProjectStatusChange,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectStatusChangeResult:
    # 404 (não 403) fora do âmbito: nunca revela que o projeto existe.
    project = get_visible_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")
    if body.lifecycle_status not in LIFECYCLE_STATUS_CODES:
        raise HTTPException(status_code=422, detail=f"Estado de projeto inválido: {body.lifecycle_status!r}")
    try:
        updated, warning = change_lifecycle_status(
            db, project=project, new_status=body.lifecycle_status, note=body.note, ctx=ctx
        )
    except PermissionDenied:
        raise HTTPException(status_code=403, detail="Sem permissão para alterar o estado deste projeto.")
    return ProjectStatusChangeResult(project=_to_read(db, updated, ctx), warning=warning)


@router.patch("/{project_id}/work-plan", response_model=ProjectRead)
def update_work_plan_endpoint(
    project_id: uuid.UUID,
    body: WorkPlanUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectRead:
    """Instalador, equipa e datas da obra (D-071). 404 fora do âmbito, 403 sem
    `project.plan_work`, 422 quando uma regra não se cumpre."""
    project = get_visible_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")
    try:
        updated = update_work_plan(db, project=project, changes=body.model_dump(exclude_unset=True), ctx=ctx)
    except PermissionDenied:
        raise HTTPException(status_code=403, detail="Sem permissão para planear a obra deste projeto.")
    except PlanError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _to_read(db, updated, ctx)


@router.get("/{project_id}/history", response_model=list[ProjectHistoryRead])
def get_project_history_endpoint(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[ProjectHistoryRead]:
    project = get_visible_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")

    entries = (
        db.query(ProjectHistory)
        .filter(ProjectHistory.project_id == project_id)
        .order_by(ProjectHistory.changed_at.desc())
        .all()
    )
    result: list[ProjectHistoryRead] = []
    for entry in entries:
        data = ProjectHistoryRead.model_validate(entry)
        if entry.changed_by_person_id:
            person = db.get(Person, entry.changed_by_person_id)
            data.changed_by_person_name = person.display_name if person else None
        result.append(data)
    return result
