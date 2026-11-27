"""Endpoints de projeto: listagem/filtros, detalhe, edição autorizada, e
histórico. Toda a escrita passa por `app/services/projects.py` — nenhuma
rota aqui manipula `Project`/`ProjectHistory` diretamente.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.people import Person
from app.models.project import Project, ProjectHistory, ProjectTeamAssignment
from app.schemas.installers import (
    TeamAssignmentCreate,
    TeamAssignmentRead,
    TeamAssignmentUpdate,
    WorkPlanUpdate,
)
from app.schemas.projects import (
    LifecycleStatusRead,
    ProjectCreate,
    ProjectEligibleManagerRead,
    ProjectHistoryRead,
    ProjectNameCandidate,
    ProjectDelete,
    ProjectRead,
    ProjectStatusChange,
    ProjectStatusChangeResult,
    ProjectUpdate,
)
from app.security.current_user import get_auth_context
from app.security.permissions import (
    AuthContext,
    can_change_project_status,
    can_create_task,
    can_edit_project,
    can_view_project,
    can_view_project_payments,
    can_plan_project_work,
    can_edit_project_payments,
    is_installer_readonly_scope,
    can_edit_project_credentials,
    can_reveal_project_credential,
    can_edit_project_sim_cards,
    can_reveal_project_sim_secrets,
    can_edit_project_surplus_contracts,
)
from app.security.project_fields import PM_EDITABLE_PROJECT_FIELDS
from app.services.installers import PlanError, update_work_plan
from app.services.process import progress_percent_by_project
from app.services.project_lifecycle import LIFECYCLE_FLOW, LIFECYCLE_STATUS_CODES, LIFECYCLE_STATUSES
from app.services.project_payments import payment_summaries_by_project
from app.services.projects import (
    DuplicateProjectName,
    change_lifecycle_status,
    check_project_name,
    compute_project_task_summary,
    create_project,
    eligible_project_managers,
    delete_project,
    get_project_channel_project,
    get_visible_project,
    list_projects_channel,
    restore_project,
    visible_projects_query,
)
from app.services.projects import update_project as update_project_service
from app.services.team_assignments import (
    AssignmentError,
    create_project_assignment,
    delete_project_assignment,
    list_project_assignments,
    update_project_assignment,
)
from app.security.perm import Perm
from app.security.guards import permission_denied_message
from app.security.guards import require_permission
from app.api.deps import visible_project_or_404

router = APIRouter(prefix="/api/projects", tags=["projects"])

PROJECT_STATUSES = frozenset({"nao_iniciado", "em_curso", "concluido"})


def _editable_fields(ctx: AuthContext, project: Project) -> list[str]:
    """Mesma regra de app/services/projects.py:update_project (D-028)."""
    if not can_edit_project(ctx, project):
        return []
    if ctx.has_permission(Perm.PROJECT_EDIT_ALL):
        return sorted(ProjectUpdate.model_fields)
    return sorted(PM_EDITABLE_PROJECT_FIELDS)


def _require_installer_mutation_scope(ctx: AuthContext) -> None:
    """The pure installer channel is read-only before any resource lookup."""
    if is_installer_readonly_scope(ctx):
        raise HTTPException(status_code=403, detail="O papel externo tem acesso somente de leitura.")


# Texto do 403 quando o serviço chamado pela rota levanta `PermissionDenied`
# (o handler de `app.main` produz o `{"detail": ...}`).
_deny_create = permission_denied_message("Não tem permissão para criar projetos.")
_deny_plan_work = permission_denied_message("Sem permissão para planear a obra deste projeto.")

# Allowlist mínima para um PM fora do âmbito normal do projeto (`project.view_all_pm_status`):
# identificação, ciclo de vida (o `status` deriva das tarefas: fica no valor por omissão), PM, potência e as flags `can_*`. Tudo o resto do DTO (contactos,
# morada/coordenadas, notas, cartão M2M, resumos derivados de tarefas, obra/instalador, fotografia,
# pagamentos) volta ao valor por omissão do schema.
_FOREIGN_PM_READABLE_FIELDS = frozenset({
    "id", "name", "lifecycle_status", "is_active", "created_at", "updated_at",
    "power_kwp", "pm_person_id", "pm_display_name", "has_pm", "editable_fields",
    "can_manage_tasks", "can_view_project_scope", "can_change_status", "can_plan_work",
    "can_edit_project_photo", "can_delete", "can_restore", "can_edit_credentials",
    "can_reveal_credentials", "can_edit_sim_cards", "can_reveal_sim_secrets",
    "can_edit_surplus_contracts", "can_edit_payments",
})
_REQUIRED_FIELD_BLANKS: dict[str, object] = {"notes": "", "work_dates_estimated": False}


def _redact_foreign_pm_project(data: ProjectRead) -> None:
    """Redige o DTO (já separado do ORM) do PM que só lê o registo base de projeto alheio."""
    for name, field in ProjectRead.model_fields.items():
        if name in _FOREIGN_PM_READABLE_FIELDS:
            continue
        value = (
            _REQUIRED_FIELD_BLANKS.get(name)
            if field.is_required()
            else field.get_default(call_default_factory=True)
        )
        setattr(data, name, value)


_COMPUTE = object()  # "calcular só para este projeto" (por oposição a `None` = sem catálogo)
_PAYMENTS_COMPUTE = object()


def _to_read(
    db: Session,
    project: Project,
    ctx: AuthContext,
    process_percents: dict[uuid.UUID, int] | None | object = _COMPUTE,
    payment_summaries: dict[uuid.UUID, dict[str, bool]] | None | object = _PAYMENTS_COMPUTE,
    *,
    include_payments: bool = True,
) -> ProjectRead:
    """`process_percents`: percentagem do processo de vários projetos, já calculada (a listagem
    calcula-a uma vez para todos, sem uma query por projeto). Omitido, calcula-se só para este;
    `None` = catálogo do processo ainda não carregado."""
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
    # D-074: o progresso vem do processo (subtarefas feitas / total do catálogo). Sem catálogo
    # carregado, mantém-se a alternativa antiga (as tarefas padrão).
    if process_percents is _COMPUTE:
        process_percents = progress_percent_by_project(db, [project.id])
    data.workflow_progress_percent = (
        process_percents[project.id]  # type: ignore[index]
        if process_percents is not None and project.id in process_percents  # type: ignore[operator]
        else summary.workflow_progress_percent
    )
    data.photos_pending_warning = summary.photos_pending_warning

    data.editable_fields = _editable_fields(ctx, project)
    data.can_manage_tasks = can_create_task(ctx, project)
    data.can_view_project_scope = can_view_project(ctx, project)
    data.can_change_status = can_change_project_status(ctx, project)
    data.can_plan_work = can_plan_project_work(ctx, project)
    data.has_project_photo = project.primary_photo_storage_name is not None
    data.can_edit_project_photo = can_edit_project(ctx, project)
    data.can_delete = ctx.has_permission(Perm.PROJECT_DELETE) and project.deleted_at is None
    data.can_restore = ctx.has_permission(Perm.PROJECT_RESTORE) and project.deleted_at is not None
    data.can_edit_credentials = can_edit_project_credentials(ctx, project)
    data.can_reveal_credentials = can_reveal_project_credential(ctx, project)
    data.can_edit_sim_cards = can_edit_project_sim_cards(ctx, project)
    data.can_reveal_sim_secrets = can_reveal_project_sim_secrets(ctx, project)
    data.can_edit_surplus_contracts = can_edit_project_surplus_contracts(ctx, project)
    data.can_edit_payments = can_edit_project_payments(ctx, project)
    if include_payments and ctx.has_permission(Perm.PAYMENT_VIEW):
        summaries = (
            payment_summaries_by_project(db, ctx=ctx, projects=[project])
            if payment_summaries is _PAYMENTS_COMPUTE
            else cast(dict[uuid.UUID, dict[str, bool]] | None, payment_summaries)
        )
        data.payments = (
            summaries.get(project.id, {
                "adjudicacao": False,
                "entrada_obra": False,
                "fim_obra": False,
                "certificado_final": False,
            })
            if summaries is not None and can_view_project_payments(ctx, project)
            else None
        )
    else:
        data.payments = None
    data.installer_name = project.installer.name if project.installer else None
    data.installer_team_name = project.installer_team.name if project.installer_team else None
    data.installer_team_leader_name = project.installer_team.leader_name if project.installer_team else None
    if project.deleted_at is None and not data.can_view_project_scope:
        _redact_foreign_pm_project(data)
    if is_installer_readonly_scope(ctx):
        # External read model contains business context only; never expose
        # contact, admin/audit, integration, or foreign-person fields.
        data.client_contact = None
        data.client_email = None
        data.power_raw = None
        data.pm_person_id = None
        data.pm_display_name = None
        data.has_email = False
        data.has_contact = False
        data.clickup_status_mirror = None
        data.role = None
        data.equipment_notes = None
        data.injection_notes = None
        data.om_notes = None
        data.commercial_assumptions = None
        data.upac_registration = None
        data.m2m_card = None
        data.upac_connection_date_raw = None
        data.award_year_raw = None
        data.notes = ""
        data.editable_fields = []
        data.can_manage_tasks = False
        data.can_change_status = False
        data.can_plan_work = False
        data.can_edit_credentials = False
        data.can_reveal_credentials = False
        data.can_edit_sim_cards = False
        data.can_reveal_sim_secrets = False
        data.can_edit_surplus_contracts = False
        if project.installer_id not in ctx.active_installer_ids:
            data.installer_id = None
            data.installer_team_id = None
            data.installer_name = None
            data.installer_team_name = None
            data.installer_team_leader_name = None
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
    projects = list_projects_channel(
        db,
        ctx,
        pm_person_id=pm_person_id,
        is_active=is_active,
        search=q,
        start_from=start_from,
        start_to=start_to,
        lifecycle_statuses=lifecycle_status,
    )
    if status is not None:
        # `status` deriva das tarefas e fica redigido (valor por omissão) fora do âmbito normal do
        # utilizador: com este filtro ativo esses projetos ficam sempre excluídos (como nos filtros de
        # data), sem filtrar sobre o valor redigido nem calcular o resumo das suas tarefas.
        normal_ids = {pid for (pid,) in visible_projects_query(db, ctx).with_entities(Project.id)}
        projects = [p for p in projects if p.id in normal_ids]
    percents = progress_percent_by_project(db, [p.id for p in projects])
    payments = (
        payment_summaries_by_project(db, ctx=ctx, projects=projects)
        if ctx.has_permission(Perm.PAYMENT_VIEW)
        else None
    )
    result = [_to_read(db, p, ctx, percents, payments) for p in projects]
    # Estado derivado da checklist e dos estados finais do ciclo de vida
    # (compute_project_task_summary), por isso o filtro aplica-se depois do
    # cálculo — nunca uma segunda regra.
    if status is not None:
        result = [r for r in result if r.status == status]
    return result


@router.get(
    "/check-name",
    response_model=list[ProjectNameCandidate],
    dependencies=[Depends(_deny_create)],
)
def check_project_name_endpoint(
    name: str = Query(min_length=1, max_length=512),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[ProjectNameCandidate]:
    _require_installer_mutation_scope(ctx)
    if not name.strip():
        raise HTTPException(status_code=422, detail="O nome do projeto não pode estar vazio.")
    candidates = check_project_name(db, name=name.strip(), ctx=ctx)
    return [ProjectNameCandidate(id=project.id, name=project.name) for project in candidates]


@router.get(
    "/eligible-managers",
    response_model=list[ProjectEligibleManagerRead],
    dependencies=[Depends(_deny_create)],
)
def eligible_project_managers_endpoint(
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[ProjectEligibleManagerRead]:
    _require_installer_mutation_scope(ctx)
    ctx.require(Perm.PROJECT_EDIT_ALL)
    return [
        ProjectEligibleManagerRead(id=person_id, display_name=name)
        for person_id, name in eligible_project_managers(db)
    ]


@router.post(
    "",
    response_model=ProjectRead,
    status_code=201,
    dependencies=[Depends(_deny_create)],
)
def create_project_endpoint(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectRead:
    _require_installer_mutation_scope(ctx)
    try:
        project = create_project(db, body=body, ctx=ctx, commit=False)
        result = _to_read(db, project, ctx)
        result.model_dump(mode="json")
        db.commit()
        return result
    except DuplicateProjectName as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        db.rollback()
        raise


@router.get("/lifecycle-statuses", response_model=list[LifecycleStatusRead])
def list_lifecycle_statuses_endpoint(
    ctx: AuthContext = Depends(get_auth_context),
) -> list[LifecycleStatusRead]:
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


@router.get("/deleted", response_model=list[ProjectRead])
def list_deleted_projects_endpoint(
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(
        require_permission(Perm.PROJECT_RESTORE, detail="Sem permissão para ver projetos apagados.")
    ),
) -> list[ProjectRead]:
    projects = db.query(Project).filter(Project.deleted_at.is_not(None)).order_by(Project.deleted_at.desc()).all()
    return [_to_read(db, project, ctx, include_payments=False) for project in projects]


@router.get("/{project_id}", response_model=ProjectRead)
def get_project_endpoint(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectRead:
    project = get_project_channel_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")
    return _to_read(db, project, ctx)


@router.patch(
    "/{project_id}",
    response_model=ProjectRead,
    # O texto inclui, quando aplicável, a lista de campos administrativos
    # recusados (D-028) — não é uma fuga de informação sensível, o próprio
    # pedido já continha esses campos.
    dependencies=[Depends(permission_denied_message("Sem permissão para editar este projeto", with_reason=True))],
)
def update_project_endpoint(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectRead:
    _require_installer_mutation_scope(ctx)
    project = db.query(Project).filter(Project.id == project_id, Project.deleted_at.is_(None)).one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    updated = update_project_service(db, project=project, changes=body, ctx=ctx)
    return _to_read(db, updated, ctx)


@router.delete(
    "/{project_id}",
    status_code=204,
    dependencies=[Depends(permission_denied_message("Sem permissão para apagar projetos."))],
)
def delete_project_endpoint(
    project_id: uuid.UUID,
    body: ProjectDelete,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(
        require_permission(Perm.PROJECT_DELETE, detail="Sem permissão para apagar projetos.")
    ),
) -> None:
    project = db.query(Project).filter(Project.id == project_id, Project.deleted_at.is_(None)).one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    try:
        delete_project(db, project=project, reason=body.reason, ctx=ctx)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post(
    "/{project_id}/restore",
    response_model=ProjectRead,
    dependencies=[Depends(permission_denied_message("Sem permissão para restaurar projetos."))],
)
def restore_project_endpoint(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(
        require_permission(Perm.PROJECT_RESTORE, detail="Sem permissão para restaurar projetos.")
    ),
) -> ProjectRead:
    project = db.query(Project).filter(Project.id == project_id, Project.deleted_at.is_not(None)).one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto apagado não encontrado.")
    restored = restore_project(db, project=project, ctx=ctx)
    return _to_read(db, restored, ctx)


@router.patch(
    "/{project_id}/status",
    response_model=ProjectStatusChangeResult,
    dependencies=[Depends(permission_denied_message("Sem permissão para alterar o estado deste projeto."))],
)
def change_project_status_endpoint(
    project_id: uuid.UUID,
    body: ProjectStatusChange,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectStatusChangeResult:
    _require_installer_mutation_scope(ctx)
    # 404 (não 403) fora do canal Projetos: nunca revela projeto apagado.
    project = get_project_channel_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")
    if body.lifecycle_status not in LIFECYCLE_STATUS_CODES:
        raise HTTPException(status_code=422, detail=f"Estado de projeto inválido: {body.lifecycle_status!r}")
    updated, warning = change_lifecycle_status(
        db, project=project, new_status=body.lifecycle_status, note=body.note, ctx=ctx
    )
    return ProjectStatusChangeResult(project=_to_read(db, updated, ctx), warning=warning)


@router.patch(
    "/{project_id}/work-plan",
    response_model=ProjectRead,
    dependencies=[Depends(_deny_plan_work)],
)
def update_work_plan_endpoint(
    project_id: uuid.UUID,
    body: WorkPlanUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectRead:
    """Instalador, equipa e datas da obra (D-071). 404 fora do âmbito, 403 sem
    `project.plan_work`, 422 quando uma regra não se cumpre."""
    _require_installer_mutation_scope(ctx)
    project = visible_project_or_404(db, ctx, project_id)
    try:
        updated = update_work_plan(db, project=project, changes=body.model_dump(exclude_unset=True), ctx=ctx)
    except PlanError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _to_read(db, updated, ctx)




def _assignment_read(data, *, scoped: bool = False) -> TeamAssignmentRead:
    assignment = data.assignment
    team = assignment.team
    installer = team.installer if team is not None else None
    return TeamAssignmentRead(
        id=assignment.id,
        project_id=assignment.project_id,
        installer_id=assignment.installer_id,
        team_id=assignment.team_id,
        start_date=assignment.start_date,
        end_date=assignment.end_date,
        note="" if scoped else assignment.note,
        created_by_person_id=None if scoped else assignment.created_by_person_id,
        team_name=team.name if team else None,
        installer_name=installer.name if installer else None,
        team_leader_name=None if scoped else (team.leader_name if team else None),
        team_leader_phone=None if scoped else (team.leader_phone if team else None),
        warning=data.warning,
    )


@router.get(
    "/{project_id}/team-assignments",
    response_model=list[TeamAssignmentRead],
    dependencies=[Depends(_deny_plan_work)],
)
def list_team_assignments_endpoint(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[TeamAssignmentRead]:
    project = visible_project_or_404(db, ctx, project_id)
    return [
        _assignment_read(item, scoped=is_installer_readonly_scope(ctx))
        for item in list_project_assignments(db, project=project, ctx=ctx)
    ]


@router.post(
    "/{project_id}/team-assignments",
    response_model=TeamAssignmentRead,
    status_code=201,
    dependencies=[Depends(_deny_plan_work)],
)
def create_team_assignment_endpoint(
    project_id: uuid.UUID,
    body: TeamAssignmentCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> TeamAssignmentRead:
    _require_installer_mutation_scope(ctx)
    project = visible_project_or_404(db, ctx, project_id)
    try:
        result = create_project_assignment(
            db,
            project=project,
            team_id=body.team_id,
            start_date=body.start_date,
            end_date=body.end_date,
            note=body.note,
            ctx=ctx,
        )
    except AssignmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _assignment_read(result)


@router.patch(
    "/{project_id}/team-assignments/{assignment_id}",
    response_model=TeamAssignmentRead,
    dependencies=[Depends(_deny_plan_work)],
)
def update_team_assignment_endpoint(
    project_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: TeamAssignmentUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> TeamAssignmentRead:
    _require_installer_mutation_scope(ctx)
    project = visible_project_or_404(db, ctx, project_id)
    assignment = (
        db.query(ProjectTeamAssignment)
        .filter(ProjectTeamAssignment.id == assignment_id, ProjectTeamAssignment.project_id == project_id)
        .one_or_none()
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Afectação não encontrada.")
    try:
        result = update_project_assignment(
            db, project=project, assignment=assignment, changes=body.model_dump(exclude_unset=True), ctx=ctx
        )
    except AssignmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _assignment_read(result)


@router.delete(
    "/{project_id}/team-assignments/{assignment_id}",
    status_code=204,
    dependencies=[Depends(_deny_plan_work)],
)
def delete_team_assignment_endpoint(
    project_id: uuid.UUID,
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> None:
    _require_installer_mutation_scope(ctx)
    project = visible_project_or_404(db, ctx, project_id)
    assignment = (
        db.query(ProjectTeamAssignment)
        .filter(ProjectTeamAssignment.id == assignment_id, ProjectTeamAssignment.project_id == project_id)
        .one_or_none()
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Afectação não encontrada.")
    delete_project_assignment(db, project=project, assignment=assignment, ctx=ctx)


@router.get("/{project_id}/history", response_model=list[ProjectHistoryRead])
def get_project_history_endpoint(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[ProjectHistoryRead]:
    project = get_visible_project(db, ctx, project_id)
    if project is None and ctx.has_permission(Perm.PROJECT_RESTORE):
        # O histórico do projeto apagado é uma superfície de auditoria
        # restrita: não o tornar visível via get_visible_project, que oculta
        # deliberadamente todas as linhas apagadas na operação normal.
        project = (
            db.query(Project)
            .filter(Project.id == project_id, Project.deleted_at.is_not(None))
            .one_or_none()
        )
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")

    if is_installer_readonly_scope(ctx):
        raise HTTPException(status_code=403, detail="O histórico administrativo não está disponível neste canal.")

    entries = (
        db.query(ProjectHistory)
        .filter(ProjectHistory.project_id == project_id)
        .order_by(ProjectHistory.changed_at.desc())
        .all()
    )
    result: list[ProjectHistoryRead] = []
    for entry in entries:
        if entry.field_name.startswith("payment.") and not ctx.has_permission(Perm.PAYMENT_VIEW):
            continue
        data = ProjectHistoryRead.model_validate(entry)
        if entry.changed_by_person_id:
            person = db.get(Person, entry.changed_by_person_id)
            data.changed_by_person_name = person.display_name if person else None
        result.append(data)
    return result
