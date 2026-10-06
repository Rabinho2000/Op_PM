"""Listagem de pessoas usada pelos seletores do frontend.

A lista global só é devolvida a perfis que têm visibilidade global de
projetos ou uma capacidade de gestão que precise de escolher qualquer pessoa.
Os restantes perfis recebem apenas pessoas do seu âmbito efetivo de projetos,
sem email.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.people import Person
from app.models.project import Project
from app.models.task import Task
from app.schemas.people import PersonRead
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, can_manage_support_delegations
from app.services.projects import visible_projects_query

router = APIRouter(prefix="/api/people", tags=["people"])

_GLOBAL_PEOPLE_PERMISSIONS = frozenset(
    {
        "admin.manage_users",
        "absence.view_all",
        "absence.manage_all",
        "absence.approve",
        "performance.manage_goals",
        "migration.resolve",
        "project.edit_all",
        "task.edit_all",
    }
)


def _can_list_global_people(ctx: AuthContext) -> bool:
    return (
        ctx.has_permission("project.view_all")
        or bool(_GLOBAL_PEOPLE_PERMISSIONS.intersection(ctx.permission_codes))
        or can_manage_support_delegations(ctx)
    )


def _filtered_people_query(db: Session, ctx: AuthContext):
    visible_project_ids = visible_projects_query(db, ctx).with_entities(Project.id).subquery()
    visible_project_pm_ids = select(Project.pm_person_id).where(
        Project.id.in_(select(visible_project_ids.c.id)),
        Project.pm_person_id.is_not(None),
    )
    assigned_people = select(Task.assigned_to_person_id).where(
        Task.project_id.in_(select(visible_project_ids.c.id)),
        Task.assigned_to_person_id.is_not(None),
    )
    return db.query(Person).filter(
        or_(
            Person.id == ctx.person_id,
            Person.id.in_(visible_project_pm_ids),
            Person.id.in_(ctx.delegating_pm_ids),
            Person.id.in_(assigned_people),
        )
    )


def _to_read(person: Person, *, include_email: bool) -> PersonRead:
    data = PersonRead.model_validate(person)
    if not include_email:
        data.email = None
    return data


@router.get("", response_model=list[PersonRead])
def list_people(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> list[PersonRead]:
    include_email = _can_list_global_people(ctx)
    query = db.query(Person) if include_email else _filtered_people_query(db, ctx)
    people = query.order_by(Person.display_name.asc()).all()
    return [_to_read(person, include_email=include_email) for person in people]
