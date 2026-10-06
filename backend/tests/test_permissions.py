"""Permissões reais aplicadas no servidor — nunca um 'papel' escolhido no
cliente. Ver app/security/permissions.py."""
from __future__ import annotations

from app.models.identity import User
from app.models.people import Person
from app.models.project import Project
from app.security.permissions import can_edit_project, can_view_project, load_auth_context
from app.services.projects import visible_projects_query


def test_pm_can_edit_only_own_project(db_session):
    db = db_session
    pm_user = db.query(User).filter(User.email == "pm.um.sintetico@example.invalid").one()
    ctx = load_auth_context(db, pm_user)

    own_project = db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()
    assert can_edit_project(ctx, own_project) is True

    unrelated_project = db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()
    assert unrelated_project.pm_person_id is None
    assert can_edit_project(ctx, unrelated_project) is False


def test_pm_cannot_view_projects_outside_scope_without_view_all(db_session):
    db = db_session
    pm_user = db.query(User).filter(User.email == "pm.um.sintetico@example.invalid").one()
    ctx = load_auth_context(db, pm_user)

    assert "project.view_all" not in ctx.permission_codes
    unrelated_project = db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()
    assert can_view_project(ctx, unrelated_project) is False


def test_pm_visible_projects_query_returns_only_assigned_projects(db_session):
    pm_user = db_session.query(User).filter(User.email == "pm.um.sintetico@example.invalid").one()
    ctx = load_auth_context(db_session, pm_user)

    visible = visible_projects_query(db_session, ctx).all()
    assert visible
    assert all(project.pm_person_id == ctx.person_id for project in visible)


def test_consulta_visible_projects_query_returns_all_projects(db_session):
    consulta = db_session.query(User).filter(User.email == "comercial.sintetico@example.invalid").one()
    ctx = load_auth_context(db_session, consulta)

    visible_ids = {project.id for project in visible_projects_query(db_session, ctx).all()}
    all_ids = {project.id for project in db_session.query(Project).all()}
    assert "project.view_all" in ctx.permission_codes
    assert visible_ids == all_ids


def test_chefe_operacoes_can_edit_any_project(db_session):
    db = db_session
    chefe = db.query(User).filter(User.email == "chefe.sintetico@example.invalid").one()
    ctx = load_auth_context(db, chefe)

    assert "project.edit_all" in ctx.permission_codes
    for project in db.query(Project).all():
        assert can_edit_project(ctx, project) is True


def test_comercial_cannot_edit_any_project(db_session):
    db = db_session
    comercial = db.query(User).filter(User.email == "comercial.sintetico@example.invalid").one()
    ctx = load_auth_context(db, comercial)

    assert "project.view_all" in ctx.permission_codes
    for project in db.query(Project).all():
        assert can_edit_project(ctx, project) is False


def test_user_without_role_has_no_permissions(db_session):
    """Um utilizador sem `UserRole` associado não herda nada por omissão —
    a ausência de papel nunca deve significar acesso total."""
    db = db_session
    # Simula um "utilizador fantasma" sem papéis, sem tocar nos dados seedados.
    orphan_person = Person(display_name="Pessoa Sintética Órfã", is_active=True)
    db.add(orphan_person)
    db.flush()
    orphan = User(person_id=orphan_person.id, email="orfao.sintetico@example.invalid", is_active=True)
    db.add(orphan)
    db.flush()
    ctx = load_auth_context(db, orphan)
    assert ctx.permission_codes == frozenset()
    db.rollback()
