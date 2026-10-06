"""Verificação de permissões no servidor — nunca confiar num "papel" escolhido
no cliente (esse era exatamente o problema do `solcor-gestao.html` legado,
onde "PM" vs "Chefe" era um `STATE.role` local sem qualquer verificação de
autorização real — ver `.planning/codebase/CONCERNS.md`, C-03, no
repositório legado).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.absence import Absence
from app.models.identity import Role, RolePermission, User, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.workflow import SupportDelegation


class PermissionDenied(Exception):
    def __init__(self, permission_code: str):
        super().__init__(f"Permissão em falta: {permission_code}")
        self.permission_code = permission_code


@dataclass(frozen=True)
class AuthContext:
    user: User
    person_id: UUID
    role_codes: frozenset[str]
    permission_codes: frozenset[str] = field(default_factory=frozenset)
    delegating_pm_ids: frozenset[UUID] = field(default_factory=frozenset)

    def has_permission(self, code: str) -> bool:
        return code in self.permission_codes

    def require(self, code: str) -> None:
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
    delegating_pm_ids = frozenset()
    if "project.view_delegated" in permission_codes:
        delegating_pm_ids = frozenset(
            pm_person_id
            for (pm_person_id,) in db.query(SupportDelegation.pm_person_id)
            .filter(SupportDelegation.support_person_id == user.person_id)
            .all()
        )
    return AuthContext(
        user=user,
        person_id=user.person_id,
        role_codes=role_codes,
        permission_codes=permission_codes,
        delegating_pm_ids=delegating_pm_ids,
    )


def can_edit_project(ctx: AuthContext, project: Project) -> bool:
    """Um projeto só pode ser editado por quem tem `project.edit_all`, ou por
    quem tem `project.edit_own_progress` e é o PM atribuído a esse projeto —
    nunca por dedução do "papel" selecionado na UI."""
    if ctx.has_permission("project.edit_all"):
        return True
    if ctx.has_permission("project.edit_own_progress"):
        return project.pm_person_id == ctx.person_id
    return False


def can_change_project_status(ctx: AuthContext, project: Project) -> bool:
    """Alterar o estado do ciclo de vida: exige `project.change_status` e que o
    projeto seja visível para o utilizador — o âmbito (todos, ou só os próprios
    como PM) vem daí, sem uma segunda regra."""
    return ctx.has_permission("project.change_status") and can_view_project(ctx, project)


def can_plan_project_work(ctx: AuthContext, project: Project) -> bool:
    """Instalador, equipa e datas da obra: exige `project.plan_work` e que o
    projeto seja visível (todos, ou só os próprios como PM)."""
    return ctx.has_permission("project.plan_work") and can_view_project(ctx, project)


def can_update_process(ctx: AuthContext, project: Project) -> bool:
    """Marcar o progresso do processo: exige `workflow.update_progress` e que o
    projeto seja visível (todos, ou só os próprios como PM)."""
    return ctx.has_permission("workflow.update_progress") and can_view_project(ctx, project)


def is_delegated_project(ctx: AuthContext, project: Project) -> bool:
    return (
        ctx.has_permission("project.view_delegated")
        and project.pm_person_id is not None
        and project.pm_person_id in ctx.delegating_pm_ids
    )


def has_only_delegated_project_scope(ctx: AuthContext) -> bool:
    """Verdadeiro quando a única visibilidade de projetos é por delegação."""
    return (
        ctx.has_permission("project.view_delegated")
        and not ctx.has_permission("project.view_all")
        and not ctx.has_permission("project.view_own")
    )


def can_update_process_stage(ctx: AuthContext, project: Project, stage) -> bool:
    """Indica se o utilizador pode marcar uma etapa concreta do processo.

    Os âmbitos são aditivos: um PM com Suporte mantém o âmbito próprio como
    PM, enquanto num projeto que só alcança pela delegação fica limitado às
    etapas ``support_delegate``.
    """
    if not ctx.has_permission("workflow.update_progress"):
        return False
    if can_update_process(ctx, project) and (
        ctx.has_permission("project.view_all")
        or can_edit_project(ctx, project)
        or (ctx.has_permission("project.view_own") and project.pm_person_id == ctx.person_id)
    ):
        return True
    return is_delegated_project(ctx, project) and stage.responsible_rule == "support_delegate"


def can_manage_support_delegations(ctx: AuthContext) -> bool:
    """Só Administrador e Chefe de Operações podem manter delegações."""
    return bool(ctx.role_codes.intersection({"admin", "administrador", "chefe_operacoes"}))


def can_view_installers(ctx: AuthContext) -> bool:
    """Catálogo global reservado a quem tem âmbito próprio ou global."""
    return ctx.has_permission("project.view_all") or ctx.has_permission("project.view_own")


def can_manage_installers(ctx: AuthContext) -> bool:
    return ctx.has_permission("installer.manage")


def can_view_project(ctx: AuthContext, project: Project) -> bool:
    if ctx.has_permission("project.view_all"):
        return True
    if ctx.has_permission("project.view_own"):
        if project.pm_person_id == ctx.person_id:
            return True
    return is_delegated_project(ctx, project)


def can_view_task(ctx: AuthContext, task: Task) -> bool:
    """Uma tarefa respeita a união dos âmbitos de projeto efetivos.

    O âmbito delegado, quando é o único âmbito de projetos, não pode ser
    furado por uma atribuição direta fora dos projetos delegados.
    """
    if ctx.has_permission("task.view_all"):
        return True
    if has_only_delegated_project_scope(ctx):
        return can_view_project(ctx, task.project)
    if task.assigned_to_person_id == ctx.person_id:
        return True
    return can_view_project(ctx, task.project)


def can_edit_task(ctx: AuthContext, task: Task) -> bool:
    """`task.edit_all` edita qualquer tarefa; `task.edit_own` só permite
    tarefas criadas ou atribuídas ao próprio utilizador, dentro do âmbito de
    projeto aplicável quando esse âmbito é exclusivamente delegado."""
    if ctx.has_permission("task.edit_all"):
        return True
    if not ctx.has_permission("task.edit_own"):
        return False
    if has_only_delegated_project_scope(ctx) and not is_delegated_project(ctx, task.project):
        return False
    return task.created_by_person_id == ctx.person_id or task.assigned_to_person_id == ctx.person_id


def can_create_task(ctx: AuthContext, project: Project) -> bool:
    if ctx.has_permission("task.edit_all"):
        return True
    if ctx.has_permission("task.edit_own"):
        return project.pm_person_id == ctx.person_id or is_delegated_project(ctx, project)
    return False


def can_view_absence(ctx: AuthContext, absence: Absence) -> bool:
    if ctx.has_permission("absence.view_all") or ctx.has_permission("absence.approve"):
        return True
    if ctx.has_permission("absence.view_own"):
        return absence.person_id == ctx.person_id
    return False


def can_approve_absence(ctx: AuthContext) -> bool:
    """A aprovação é uma capacidade separada de gerir/cancelar ausências."""
    return ctx.has_permission("absence.approve")


def can_manage_absence(ctx: AuthContext, absence: Absence) -> bool:
    if ctx.has_permission("absence.manage_all"):
        return True
    if ctx.has_permission("absence.manage_own"):
        return absence.person_id == ctx.person_id
    return False


def can_create_absence_for(ctx: AuthContext, person_id: UUID) -> bool:
    if ctx.has_permission("absence.manage_all"):
        return True
    if ctx.has_permission("absence.manage_own"):
        return person_id == ctx.person_id
    return False


# --- MVP de Operações (ver docs/PLAN_OPERATIONS_MVP.md) ---
#
# Padrão comum: uma permissão de domínio (`project.edit_installation_data`,
# `calendar.manage`, `project_issue.manage`, ...) só produz efeito dentro do
# âmbito de projeto que `can_view_project`/`can_edit_project` já define —
# nunca uma segunda lógica de "próprio projeto" duplicada por domínio.


def can_view_project_installation_data(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission("project.view_installation_data") and can_view_project(ctx, project)


def can_edit_project_installation_data(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission("project.edit_installation_data") and (
        can_edit_project(ctx, project) or is_delegated_project(ctx, project)
    )


def can_view_project_licensing_data(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission("project.view_licensing_data") and can_view_project(ctx, project)


def can_edit_project_licensing_data(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission("project.edit_licensing_data") and (
        can_edit_project(ctx, project) or is_delegated_project(ctx, project)
    )


def can_view_project_communication_data(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission("project.view_communication_data") and can_view_project(ctx, project)


def can_edit_project_communication_data(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission("project.edit_communication_data") and can_edit_project(ctx, project)


def can_manage_central_inventory(ctx: AuthContext) -> bool:
    """Entrada/ajuste no stock físico central — nunca por projeto (o stock
    central é um recurso partilhado por toda a operação, não de um
    projeto). Administrador, Chefe de Operações e PM têm todos esta
    permissão (decisão de negócio confirmada — ver
    docs/PLAN_OPERATIONS_MVP.md secção 4)."""
    return ctx.has_permission("inventory.manage_central")


def can_allocate_inventory_for_project(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission("inventory.allocate_project") and can_edit_project(ctx, project)


def can_consume_inventory_for_project(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission("inventory.consume_project") and can_edit_project(ctx, project)


def can_release_inventory_for_project(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission("inventory.release_project") and can_edit_project(ctx, project)


def can_deliver_inventory_for_project(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission("inventory.deliver_project") and can_edit_project(ctx, project)


def can_collect_inventory_for_project(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission("inventory.collect_project") and can_edit_project(ctx, project)


def can_manage_material_requirements(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission("inventory.manage_requirements") and can_edit_project(ctx, project)


def can_view_map(ctx: AuthContext) -> bool:
    return ctx.has_permission("map.view")


def can_manage_suppliers(ctx: AuthContext) -> bool:
    return ctx.has_permission("supplier.manage")


def can_view_suppliers(ctx: AuthContext) -> bool:
    """`supplier.view`, ou `map.view` (compatibilidade: a lista já era visível
    a quem via o mapa)."""
    return ctx.has_permission("supplier.view") or ctx.has_permission("map.view")


def can_manage_pickup_points(ctx: AuthContext) -> bool:
    return ctx.has_permission("pickup_point.manage")


def can_view_project_issue(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission("project_issue.view") and can_view_project(ctx, project)


def can_manage_project_issue(ctx: AuthContext, project: Project) -> bool:
    return ctx.has_permission("project_issue.manage") and can_edit_project(ctx, project)


def can_view_calendar_event(
    ctx: AuthContext,
    project: Project | None,
    *,
    assigned_to_person_id: UUID | None = None,
) -> bool:
    if not ctx.has_permission("calendar.view"):
        return False
    if project is None:
        if has_only_delegated_project_scope(ctx):
            return assigned_to_person_id == ctx.person_id
        # Mantém o comportamento dos restantes papéis para eventos internos.
        return True
    return can_view_project(ctx, project)


def can_manage_calendar_event(ctx: AuthContext, project: Project | None) -> bool:
    if not ctx.has_permission("calendar.manage"):
        return False
    if project is None:
        return True
    return can_edit_project(ctx, project)


def can_view_performance(ctx: AuthContext) -> bool:
    return ctx.has_permission("performance.view_all") or ctx.has_permission("performance.view_own")


def can_manage_goals(ctx: AuthContext) -> bool:
    return ctx.has_permission("performance.manage_goals")


def can_import_notes(ctx: AuthContext) -> bool:
    return ctx.has_permission("import.notes")


def can_import_licensing(ctx: AuthContext) -> bool:
    return ctx.has_permission("import.licensing")
