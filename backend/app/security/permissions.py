"""Verificação de permissões no servidor — nunca confiar num "papel" escolhido
no cliente (esse era exatamente o problema do `solcor-gestao.html` legado,
onde "PM" vs "Chefe" era um `STATE.role` local sem qualquer verificação de
autorização real — ver `.planning/codebase/CONCERNS.md`, C-03, no
repositório legado).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import and_, exists, or_
from sqlalchemy.orm import Session

from app.models.absence import Absence
from app.models.identity import Role, RolePermission, User, UserRole
from app.models.installer_access import InstallerAccessMembership
from app.models.project import Project, ProjectTeamAssignment
from app.models.task import Task
from app.models.workflow import SupportDelegation
from app.security.perm import Perm


# Motivos de recusa que não são permissões do catálogo (aparecem na mensagem
# "Permissão em falta: ..." de algumas respostas 403 e não devem mudar).
DENIED_INSTALLER_READ_ONLY = "installer.read_only"
DENIED_PROJECT_VIEW = "project.view"
DENIED_INSTALLER_VIEW = "installer.view"


class PermissionDenied(Exception):
    """Recusa de autorização. O handler registado em `app.main` (ver
    `app/security/guards.py`) converte-a em 403 com `{"detail": ...}`.

    `permission_code` é um membro de `Perm` (ou, nos poucos casos de recusa
    por âmbito, um dos `DENIED_*` acima ou várias permissões separadas por
    `|`). `detail` fixa o texto do 403 quando quem levanta a exceção já sabe
    qual é; sem ele aplica-se a mensagem da rota (`permission_denied_message`)
    ou, por omissão, `Permissão em falta: <código>`.
    """

    def __init__(self, permission_code: str, *, detail: str | None = None):
        super().__init__(f"Permissão em falta: {permission_code}")
        self.permission_code = permission_code
        self.detail = detail


@dataclass(frozen=True)
class AuthContext:
    user: User
    person_id: UUID
    role_codes: frozenset[str]
    permission_codes: frozenset[str] = field(default_factory=frozenset)
    delegating_pm_ids: frozenset[UUID] = field(default_factory=frozenset)
    active_installer_ids: frozenset[UUID] = field(default_factory=frozenset)

    def has_permission(self, code: Perm) -> bool:
        return code in self.permission_codes

    def require(self, code: Perm) -> None:
        if not self.has_permission(code):
            raise PermissionDenied(code)


def load_auth_context(db: Session, user: User) -> AuthContext:
    role_rows = (
        db.query(Role)
        .join(UserRole, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user.id)
        .all()
    )
    role_ids = [r.id for r in role_rows]
    role_codes = frozenset(r.code for r in role_rows)

    if not role_ids:
        return AuthContext(user=user, person_id=user.person_id, role_codes=frozenset())

    perm_rows = (
        db.query(RolePermission)
        .filter(RolePermission.role_id.in_(role_ids))
        .all()
    )
    permission_codes = frozenset(rp.permission.code for rp in perm_rows)
    delegating_pm_ids: frozenset[UUID] = frozenset()
    if Perm.PROJECT_VIEW_DELEGATED in permission_codes:
        delegating_pm_ids = frozenset(
            pm_person_id
            for (pm_person_id,) in db.query(SupportDelegation.pm_person_id)
            .filter(SupportDelegation.support_person_id == user.person_id)
            .all()
        )
    active_installer_ids: frozenset[UUID] = frozenset()
    if Perm.PROJECT_VIEW_ASSIGNED_INSTALLER in permission_codes:
        active_installer_ids = frozenset(
            installer_id
            for (installer_id,) in db.query(InstallerAccessMembership.installer_id)
            .filter(
                InstallerAccessMembership.person_id == user.person_id,
                InstallerAccessMembership.is_active.is_(True),
            )
            .all()
        )
    return AuthContext(
        user=user,
        person_id=user.person_id,
        role_codes=role_codes,
        permission_codes=permission_codes,
        delegating_pm_ids=delegating_pm_ids,
        active_installer_ids=active_installer_ids,
    )


def can_edit_project(ctx: AuthContext, project: Project) -> bool:
    """Um projeto só pode ser editado por quem tem `project.edit_all`, ou por
    quem tem `project.edit_own_progress` e é o PM atribuído a esse projeto —
    nunca por dedução do "papel" selecionado na UI."""
    if project.deleted_at is not None:
        return False
    if ctx.has_permission(Perm.PROJECT_EDIT_ALL):
        return True
    if ctx.has_permission(Perm.PROJECT_EDIT_OWN_PROGRESS):
        return project.pm_person_id == ctx.person_id
    return False


def can_change_project_status(ctx: AuthContext, project: Project) -> bool:
    """Alterar o estado do ciclo de vida: exige `project.change_status` e que o
    projeto seja visível para o utilizador — o âmbito (todos, ou só os próprios
    como PM) vem daí, sem uma segunda regra."""
    return ctx.has_permission(Perm.PROJECT_CHANGE_STATUS) and (
        can_view_project(ctx, project)
        or (
            ctx.has_permission(Perm.PROJECT_VIEW_ALL_PM_STATUS)
            and project.deleted_at is None
        )
    )


def can_plan_project_work(ctx: AuthContext, project: Project) -> bool:
    """Instalador, equipa e datas da obra: exige `project.plan_work` e que o
    projeto seja visível (todos, ou só os próprios como PM)."""
    return ctx.has_permission(Perm.PROJECT_PLAN_WORK) and can_view_project(ctx, project)


def can_update_process(ctx: AuthContext, project: Project) -> bool:
    """Marcar o progresso do processo: exige `workflow.update_progress` e que o
    projeto seja visível (todos, ou só os próprios como PM)."""
    return ctx.has_permission(Perm.WORKFLOW_UPDATE_PROGRESS) and can_view_project(ctx, project)


def is_delegated_project(ctx: AuthContext, project: Project) -> bool:
    return (
        ctx.has_permission(Perm.PROJECT_VIEW_DELEGATED)
        and project.pm_person_id is not None
        and project.pm_person_id in ctx.delegating_pm_ids
    )


def has_only_delegated_project_scope(ctx: AuthContext) -> bool:
    """Verdadeiro quando a única visibilidade de projetos é por delegação."""
    return (
        ctx.has_permission(Perm.PROJECT_VIEW_DELEGATED)
        and not ctx.has_permission(Perm.PROJECT_VIEW_ALL)
        and not ctx.has_permission(Perm.PROJECT_VIEW_OWN)
    )


def can_update_process_stage(ctx: AuthContext, project: Project, stage) -> bool:
    """Indica se o utilizador pode marcar uma etapa concreta do processo.

    Os âmbitos são aditivos: um PM com Suporte mantém o âmbito próprio como
    PM, enquanto num projeto que só alcança pela delegação fica limitado às
    etapas ``support_delegate``.
    """
    if not ctx.has_permission(Perm.WORKFLOW_UPDATE_PROGRESS):
        return False
    if can_update_process(ctx, project) and (
        ctx.has_permission(Perm.PROJECT_VIEW_ALL)
        or can_edit_project(ctx, project)
        or (ctx.has_permission(Perm.PROJECT_VIEW_OWN) and project.pm_person_id == ctx.person_id)
    ):
        return True
    return is_delegated_project(ctx, project) and stage.responsible_rule == "support_delegate"


def can_manage_support_delegations(ctx: AuthContext) -> bool:
    """Só Administrador e Chefe de Operações podem manter delegações."""
    return bool(ctx.role_codes.intersection({"admin", "administrador", "chefe_operacoes"}))


def can_view_installers(ctx: AuthContext) -> bool:
    """Catálogo global reservado a quem tem âmbito próprio ou global."""
    return ctx.has_permission(Perm.PROJECT_VIEW_ALL) or ctx.has_permission(Perm.PROJECT_VIEW_OWN)


def can_manage_installers(ctx: AuthContext) -> bool:
    return ctx.has_permission(Perm.INSTALLER_MANAGE)


def has_only_installer_project_scope(ctx: AuthContext) -> bool:
    """True when assigned-installer is the only broad project scope.

    The predicate is capability based, so a user with an additional broad role
    keeps the additive behaviour of the existing RBAC model.
    """
    return (
        ctx.has_permission(Perm.PROJECT_VIEW_ASSIGNED_INSTALLER)
        and not ctx.has_permission(Perm.PROJECT_VIEW_ALL)
        and not ctx.has_permission(Perm.PROJECT_VIEW_OWN)
        and not ctx.has_permission(Perm.PROJECT_VIEW_DELEGATED)
    )


def is_installer_readonly_scope(ctx: AuthContext) -> bool:
    return has_only_installer_project_scope(ctx)


def installer_project_scope_conditions(ctx: AuthContext) -> list[object]:
    """Return the SQL predicates for the assigned-installer project scope."""
    if not ctx.has_permission(Perm.PROJECT_VIEW_ASSIGNED_INSTALLER):
        return []
    if not ctx.active_installer_ids:
        return [Project.id.is_(None)]
    assignment_exists = exists().where(
        and_(
            ProjectTeamAssignment.project_id == Project.id,
            ProjectTeamAssignment.installer_id.in_(ctx.active_installer_ids),
        )
    )
    return [
        or_(
            Project.installer_id.in_(ctx.active_installer_ids),
            assignment_exists,
        )
    ]


def project_matches_installer_scope(ctx: AuthContext, project: Project) -> bool:
    if not ctx.has_permission(Perm.PROJECT_VIEW_ASSIGNED_INSTALLER):
        return False
    if project.installer_id in ctx.active_installer_ids:
        return True
    return any(
        assignment.installer_id in ctx.active_installer_ids
        for assignment in (project.team_assignments or [])
    )


def can_view_project(ctx: AuthContext, project: Project) -> bool:
    if project.deleted_at is not None:
        return False
    if ctx.has_permission(Perm.PROJECT_VIEW_ALL):
        return True
    if ctx.has_permission(Perm.PROJECT_VIEW_OWN):
        if project.pm_person_id == ctx.person_id:
            return True
    if is_delegated_project(ctx, project):
        return True
    return project_matches_installer_scope(ctx, project)


def can_view_project_payments(ctx: AuthContext, project: Project) -> bool:
    """Payment visibility is a separate capability within normal project scope."""
    return ctx.has_permission(Perm.PAYMENT_VIEW) and can_view_project(ctx, project)


def can_edit_project_payments(ctx: AuthContext, project: Project) -> bool:
    """Only payment editors may change milestones, and only on visible projects."""
    return ctx.has_permission(Perm.PAYMENT_EDIT) and can_view_project(ctx, project)


def can_view_task(ctx: AuthContext, task: Task) -> bool:
    """Uma tarefa respeita a união dos âmbitos de projeto efetivos.

    O âmbito delegado, quando é o único âmbito de projetos, não pode ser
    furado por uma atribuição direta fora dos projetos delegados.
    """
    if task.project.deleted_at is not None:
        return False
    if ctx.has_permission(Perm.TASK_VIEW_ALL):
        return True
    if has_only_delegated_project_scope(ctx) or is_installer_readonly_scope(ctx):
        return can_view_project(ctx, task.project)
    if task.assigned_to_person_id == ctx.person_id:
        return True
    if ctx.has_permission(Perm.TASK_VIEW_ASSIGNED_INSTALLER):
        return can_view_project(ctx, task.project)
    return can_view_project(ctx, task.project)


def can_edit_task(ctx: AuthContext, task: Task) -> bool:
    """`task.edit_all` edita qualquer tarefa; `task.edit_own` só permite
    tarefas criadas ou atribuídas ao próprio utilizador, dentro do âmbito de
    projeto aplicável quando esse âmbito é exclusivamente delegado."""
    if task.project.deleted_at is not None:
        return False
    if ctx.has_permission(Perm.TASK_EDIT_ALL):
        return True
    if not ctx.has_permission(Perm.TASK_EDIT_OWN):
        return False
    if has_only_delegated_project_scope(ctx) and not is_delegated_project(ctx, task.project):
        return False
    return task.created_by_person_id == ctx.person_id or task.assigned_to_person_id == ctx.person_id


def can_create_task(ctx: AuthContext, project: Project) -> bool:
    if project.deleted_at is not None:
        return False
    if ctx.has_permission(Perm.TASK_EDIT_ALL):
        return True
    if ctx.has_permission(Perm.TASK_EDIT_OWN):
        return project.pm_person_id == ctx.person_id or is_delegated_project(ctx, project)
    return False


def can_view_absence(ctx: AuthContext, absence: Absence) -> bool:
    if ctx.has_permission(Perm.ABSENCE_VIEW_ALL) or ctx.has_permission(Perm.ABSENCE_APPROVE):
        return True
    if ctx.has_permission(Perm.ABSENCE_VIEW_OWN):
        return absence.person_id == ctx.person_id
    return False


def can_approve_absence(ctx: AuthContext) -> bool:
    """A aprovação é uma capacidade separada de gerir/cancelar ausências."""
    return ctx.has_permission(Perm.ABSENCE_APPROVE)


def can_manage_absence(ctx: AuthContext, absence: Absence) -> bool:
    if ctx.has_permission(Perm.ABSENCE_MANAGE_ALL):
        return True
    if ctx.has_permission(Perm.ABSENCE_MANAGE_OWN):
        return absence.person_id == ctx.person_id
    return False


def can_create_absence_for(ctx: AuthContext, person_id: UUID) -> bool:
    if ctx.has_permission(Perm.ABSENCE_MANAGE_ALL):
        return True
    if ctx.has_permission(Perm.ABSENCE_MANAGE_OWN):
        return person_id == ctx.person_id
    return False


# --- MVP de Operações (ver docs/PLAN_OPERATIONS_MVP.md) ---
#
# Padrão comum: uma permissão de domínio (`project.edit_installation_data`,
# `calendar.manage`, `project_issue.manage`, ...) só produz efeito dentro do
# âmbito de projeto que `can_view_project`/`can_edit_project` já define —
# nunca uma segunda lógica de "próprio projeto" duplicada por domínio.


def can_view_project_installation_data(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission(Perm.PROJECT_VIEW_INSTALLATION_DATA) and can_view_project(ctx, project)


def can_edit_project_installation_data(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission(Perm.PROJECT_EDIT_INSTALLATION_DATA) and (
        can_edit_project(ctx, project) or is_delegated_project(ctx, project)
    )


def can_view_project_licensing_data(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission(Perm.PROJECT_VIEW_LICENSING_DATA) and can_view_project(ctx, project)


def can_edit_project_licensing_data(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission(Perm.PROJECT_EDIT_LICENSING_DATA) and (
        can_edit_project(ctx, project) or is_delegated_project(ctx, project)
    )


def can_view_project_communication_data(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission(Perm.PROJECT_VIEW_COMMUNICATION_DATA) and can_view_project(ctx, project)


def can_edit_project_communication_data(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission(Perm.PROJECT_EDIT_COMMUNICATION_DATA) and can_edit_project(ctx, project)


def can_view_project_credentials(ctx: AuthContext, project: Project) -> bool:
    """Lista de credenciais de portais (sem passwords): mesmo âmbito de
    comunicação/M2M — exige `project.view_communication_data`."""
    return ctx.has_permission(Perm.PROJECT_VIEW_COMMUNICATION_DATA) and can_view_project(ctx, project)


def can_edit_project_credentials(ctx: AuthContext, project: Project) -> bool:
    """Criar/editar/remover credenciais: `project.credentials.edit` e o âmbito
    de `can_edit_project` (administrador, chefe, PM do projeto)."""
    return ctx.has_permission(Perm.PROJECT_CREDENTIALS_EDIT) and can_edit_project(ctx, project)


def can_reveal_project_credential(ctx: AuthContext, project: Project) -> bool:
    """Revelar a password: `project.credentials.reveal` e o mesmo âmbito."""
    return ctx.has_permission(Perm.PROJECT_CREDENTIALS_REVEAL) and can_edit_project(ctx, project)


def can_view_project_sim_cards(ctx: AuthContext, project: Project) -> bool:
    """Lista de SIMs (sem PIN/PUK): mesmo âmbito da comunicação/M2M."""
    return ctx.has_permission(Perm.PROJECT_VIEW_COMMUNICATION_DATA) and can_view_project(ctx, project)


def can_edit_project_sim_cards(ctx: AuthContext, project: Project) -> bool:
    """Criar/editar/remover SIMs: `project.edit_communication_data` e `can_edit_project`."""
    return ctx.has_permission(Perm.PROJECT_EDIT_COMMUNICATION_DATA) and can_edit_project(ctx, project)


def can_write_project_sim_secrets(ctx: AuthContext, project: Project) -> bool:
    """Definir/alterar PIN ou PUK: mesma permissão de escrita das passwords de portais."""
    return can_edit_project_credentials(ctx, project)


def can_reveal_project_sim_secrets(ctx: AuthContext, project: Project) -> bool:
    """Ver PIN/PUK: `project.credentials.reveal` e o mesmo âmbito das passwords."""
    return can_reveal_project_credential(ctx, project)


def can_view_project_surplus_contracts(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission(Perm.PROJECT_VIEW_LICENSING_DATA) and can_view_project(ctx, project)


def can_edit_project_surplus_contracts(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission(Perm.PROJECT_EDIT_LICENSING_DATA) and (
        can_edit_project(ctx, project) or is_delegated_project(ctx, project)
    )


def can_manage_central_inventory(ctx: AuthContext) -> bool:
    """Entrada/ajuste no stock físico central — nunca por projeto (o stock
    central é um recurso partilhado por toda a operação, não de um
    projeto). Administrador, Chefe de Operações e PM têm todos esta
    permissão (decisão de negócio confirmada — ver
    docs/PLAN_OPERATIONS_MVP.md secção 4)."""
    return ctx.has_permission(Perm.INVENTORY_MANAGE_CENTRAL)


def can_allocate_inventory_for_project(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission(Perm.INVENTORY_ALLOCATE_PROJECT) and can_edit_project(ctx, project)


def can_consume_inventory_for_project(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission(Perm.INVENTORY_CONSUME_PROJECT) and can_edit_project(ctx, project)


def can_release_inventory_for_project(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission(Perm.INVENTORY_RELEASE_PROJECT) and can_edit_project(ctx, project)


def can_deliver_inventory_for_project(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission(Perm.INVENTORY_DELIVER_PROJECT) and can_edit_project(ctx, project)


def can_collect_inventory_for_project(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission(Perm.INVENTORY_COLLECT_PROJECT) and can_edit_project(ctx, project)


def can_reverse_inventory_movement_for_project(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission(Perm.INVENTORY_REVERSE_PROJECT) and can_edit_project(ctx, project)


def can_manage_material_requirements(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission(Perm.INVENTORY_MANAGE_REQUIREMENTS) and can_edit_project(ctx, project)


def can_view_map(ctx: AuthContext) -> bool:
    return ctx.has_permission(Perm.MAP_VIEW)


def can_manage_suppliers(ctx: AuthContext) -> bool:
    return ctx.has_permission(Perm.SUPPLIER_MANAGE)


def can_view_suppliers(ctx: AuthContext) -> bool:
    """`supplier.view`, ou `map.view` (compatibilidade: a lista já era visível
    a quem via o mapa)."""
    return ctx.has_permission(Perm.SUPPLIER_VIEW) or ctx.has_permission(Perm.MAP_VIEW)


def can_manage_pickup_points(ctx: AuthContext) -> bool:
    return ctx.has_permission(Perm.PICKUP_POINT_MANAGE)


def can_view_project_issue(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission(Perm.PROJECT_ISSUE_VIEW) and can_view_project(ctx, project)


def can_manage_project_issue(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission(Perm.PROJECT_ISSUE_MANAGE) and can_edit_project(ctx, project)


def can_view_calendar_event(
    ctx: AuthContext,
    project: Project | None,
    *,
    assigned_to_person_id: UUID | None = None,
    assigned_to_person_ids: tuple[UUID, ...] | list[UUID] | None = None,
) -> bool:
    if not (
        ctx.has_permission(Perm.CALENDAR_VIEW)
        or ctx.has_permission(Perm.CALENDAR_VIEW_ALL_PM)
        or ctx.has_permission(Perm.WORKS_CALENDAR_VIEW_ASSIGNED_INSTALLER)
    ):
        return False
    if ctx.has_permission(Perm.CALENDAR_VIEW_ALL_PM) and not ctx.has_permission(Perm.PROJECT_VIEW_ALL):
        return project is None or project.deleted_at is None
    if project is None:
        if has_only_delegated_project_scope(ctx) or is_installer_readonly_scope(ctx):
            participants = set(assigned_to_person_ids or ())
            if assigned_to_person_id is not None:
                participants.add(assigned_to_person_id)
            # Scoped external users never receive unrelated internal events.
            return not is_installer_readonly_scope(ctx) and ctx.person_id in participants
        # Mantém o comportamento dos restantes papéis para eventos internos.
        return True
    return can_view_project(ctx, project)


def can_manage_calendar_event(ctx: AuthContext, project: Project | None) -> bool:
    if not ctx.has_permission(Perm.CALENDAR_MANAGE):
        return False
    if project is None:
        if ctx.has_permission(Perm.CALENDAR_VIEW_ALL_PM) and not ctx.has_permission(Perm.PROJECT_VIEW_ALL):
            return False
        return True
    return can_edit_project(ctx, project)


def can_view_performance(ctx: AuthContext) -> bool:
    return ctx.has_permission(Perm.PERFORMANCE_VIEW_ALL) or ctx.has_permission(Perm.PERFORMANCE_VIEW_OWN)


def can_manage_goals(ctx: AuthContext) -> bool:
    return ctx.has_permission(Perm.PERFORMANCE_MANAGE_GOALS)


def can_import_notes(ctx: AuthContext) -> bool:
    return ctx.has_permission(Perm.IMPORT_NOTES)


def can_import_licensing(ctx: AuthContext) -> bool:
    return ctx.has_permission(Perm.IMPORT_LICENSING)


def can_view_time_bank(ctx: AuthContext) -> bool:
    return ctx.has_permission(Perm.TIME_BANK_VIEW_ALL) or ctx.has_permission(Perm.TIME_BANK_VIEW_OWN)


def can_view_time_bank_person(ctx: AuthContext, person_id: UUID) -> bool:
    if ctx.has_permission(Perm.TIME_BANK_VIEW_ALL):
        return True
    return ctx.has_permission(Perm.TIME_BANK_VIEW_OWN) and person_id == ctx.person_id


def can_manage_time_bank(ctx: AuthContext) -> bool:
    return ctx.has_permission(Perm.TIME_BANK_MANAGE_ALL)


def can_log_time_bank_own(ctx: AuthContext) -> bool:
    return ctx.has_permission(Perm.TIME_BANK_LOG_OWN)
