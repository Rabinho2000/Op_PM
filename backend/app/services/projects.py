"""Camada de serviço para leitura/escrita de projetos — ponto único onde a
API verifica permissões e gera histórico. Nenhuma rota deve escrever
diretamente num `Project` sem passar por aqui (ver
`app/api/routes_projects.py`).
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, or_
from sqlalchemy.orm import Query, Session

from app.audit.log import record_project_change
from app.models.project import Project
from app.schemas.projects import ProjectUpdate
from app.security.permissions import AuthContext, PermissionDenied, can_edit_project, can_view_project
from app.security.project_fields import PM_EDITABLE_PROJECT_FIELDS


def visible_projects_query(db: Session, ctx: AuthContext) -> Query:
    """Restringe a query à visibilidade do utilizador — nunca devolve tudo
    e filtra depois em Python (evita esquecer o filtro nalgum sítio)."""
    if ctx.has_permission("project.view_all"):
        return db.query(Project)
    if ctx.has_permission("project.view_own"):
        return db.query(Project).filter(Project.pm_person_id == ctx.person_id)
    # Sem nenhuma das duas permissões: nada visível.
    return db.query(Project).filter(False)


def list_projects(
    db: Session,
    ctx: AuthContext,
    *,
    pm_person_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    search: str | None = None,
) -> list[Project]:
    query = visible_projects_query(db, ctx)
    if pm_person_id is not None:
        query = query.filter(Project.pm_person_id == pm_person_id)
    if is_active is not None:
        query = query.filter(Project.is_active == is_active)
    if search:
        pattern = f"%{search.strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(Project.name).like(pattern),
                func.lower(Project.client_name).like(pattern),
                func.lower(Project.client_contact).like(pattern),
            )
        )
    return query.order_by(Project.name.asc()).all()


def get_visible_project(db: Session, ctx: AuthContext, project_id: uuid.UUID) -> Project | None:
    project = db.get(Project, project_id)
    if project is None:
        return None
    if not can_view_project(ctx, project):
        return None
    return project


def update_project(
    db: Session,
    *,
    project: Project,
    changes: ProjectUpdate,
    ctx: AuthContext,
) -> Project:
    """Só isto escreve num `Project` a partir da API. Verifica permissão
    primeiro (nunca confia no chamador já ter verificado); gera uma
    entrada de `project_history` por campo efetivamente alterado — nunca
    uma escrita silenciosa.

    Restrição de campo (D-028): quem só tem `project.edit_own_progress`
    (nunca `project.edit_all`) está limitado à allowlist explícita
    `PM_EDITABLE_PROJECT_FIELDS` — nunca pode tocar em `name`,
    `client_email`, `client_contact`, `pm_person_id`, `is_active`, ou
    qualquer outro campo administrativo, mesmo que seja o PM do projeto.
    Um pedido com QUALQUER campo fora da allowlist é rejeitado por
    inteiro, antes de qualquer escrita — nunca aplica só os campos
    permitidos e ignora os outros em silêncio."""
    if not can_edit_project(ctx, project):
        raise PermissionDenied("project.edit_all|project.edit_own_progress")

    # exclude_unset: um campo omitido do pedido nunca é tocado; um campo
    # presente com valor `null` limpa-o explicitamente — distinção
    # importante para não apagar dados por omissão de um campo no body.
    changed_fields = changes.model_dump(exclude_unset=True)

    if not ctx.has_permission("project.edit_all"):
        # Chegou aqui só com project.edit_own_progress (can_edit_project já
        # garantiu que é o PM deste projeto) — restringe à allowlist.
        disallowed_fields = sorted(set(changed_fields) - PM_EDITABLE_PROJECT_FIELDS)
        if disallowed_fields:
            raise PermissionDenied(
                f"project.edit_all (campos administrativos não permitidos a "
                f"project.edit_own_progress: {', '.join(disallowed_fields)})"
            )

    for field_name, new_value in changed_fields.items():
        old_value = getattr(project, field_name)
        if old_value == new_value:
            continue
        record_project_change(
            db,
            project_id=project.id,
            field_name=field_name,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(new_value) if new_value is not None else None,
            source="ui",
            changed_by_person_id=ctx.person_id,
            note="Edição manual via API.",
        )
        setattr(project, field_name, new_value)

    db.commit()
    db.refresh(project)
    return project
