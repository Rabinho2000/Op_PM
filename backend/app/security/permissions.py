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
    return AuthContext(
        user=user, person_id=user.person_id, role_codes=role_codes, permission_codes=permission_codes
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


def can_view_project(ctx: AuthContext, project: Project) -> bool:
    if ctx.has_permission("project.view_all"):
        return True
    if ctx.has_permission("project.view_own"):
        return project.pm_person_id == ctx.person_id
    return False


def can_view_task(ctx: AuthContext, task: Task) -> bool:
    """Uma tarefa é visível a quem tem `task.view_all` (ex. PM — vê tarefas
    de todos os projetos, não só os seus), a quem consegue ver o projeto a
    que pertence, ou a quem lhe está atribuída diretamente (mesmo que não
    seja o PM do projeto — ex. um técnico atribuído pontualmente)."""
    if ctx.has_permission("task.view_all"):
        return True
    if task.assigned_to_person_id == ctx.person_id:
        return True
    return can_view_project(ctx, task.project)


def can_edit_task(ctx: AuthContext, task: Task) -> bool:
    """`task.edit_all` (Chefe/Administrador) edita qualquer tarefa.
    `task.edit_own` (PM) só edita tarefas que criou ou que lhe estão
    atribuídas — nunca por ser o PM do projeto (um PM vê agora todas as
    tarefas via `task.view_all`, mas isso não lhe dá direito de escrita
    sobre tarefas de outra pessoa nesse projeto)."""
    if ctx.has_permission("task.edit_all"):
        return True
    if ctx.has_permission("task.edit_own"):
        return task.created_by_person_id == ctx.person_id or task.assigned_to_person_id == ctx.person_id
    return False


def can_create_task(ctx: AuthContext, project: Project) -> bool:
    if ctx.has_permission("task.edit_all"):
        return True
    if ctx.has_permission("task.edit_own"):
        return project.pm_person_id == ctx.person_id
    return False


def can_view_absence(ctx: AuthContext, absence: Absence) -> bool:
    if ctx.has_permission("absence.view_all"):
        return True
    if ctx.has_permission("absence.view_own"):
        return absence.person_id == ctx.person_id
    return False


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
