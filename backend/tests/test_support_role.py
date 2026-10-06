from __future__ import annotations

import datetime as dt

from app.models.identity import User
from app.models.people import Person
from app.models.project import Project, ProjectSubtaskProgress
from app.models.task import Task
from app.security.permissions import (
    AuthContext,
    can_create_task,
    can_edit_project,
    can_edit_task,
    can_view_project,
    can_view_task,
)
from app.services.projects import visible_projects_query
from app.services.tasks import visible_tasks_query
from app.services.my_process import list_my_process_stages
from app.models.workflow import Phase, SupportDelegation, SupportDelegationHistory, WorkflowStage, WorkflowSubtask
from app.services.support_delegations import delete_delegation, upsert_delegation


def _scenario(db_session):
    support = Person(display_name="Suporte de Operações")
    delegated_pm = Person(display_name="PM Delegado")
    outside_pm = Person(display_name="PM Fora da Delegação")
    third_person = Person(display_name="Outra Pessoa")
    db_session.add_all([support, delegated_pm, outside_pm, third_person])
    db_session.flush()

    delegated_project = Project(name="Projeto Delegado", pm_person_id=delegated_pm.id)
    outside_project = Project(name="Projeto Não Delegado", pm_person_id=outside_pm.id)
    db_session.add_all([delegated_project, outside_project])
    db_session.flush()

    support_user = User(person_id=support.id, email="suporte@example.invalid")
    support_ctx = AuthContext(
        user=support_user,
        person_id=support.id,
        role_codes=frozenset({"suporte_operacoes"}),
        permission_codes=frozenset({"task.view_own", "task.edit_own", "project.view_delegated", "workflow.update_progress"}),
        delegating_pm_ids=frozenset({delegated_pm.id}),
    )
    return support, delegated_pm, outside_pm, third_person, delegated_project, outside_project, support_ctx


def test_support_can_view_only_delegated_project_even_when_assigned(db_session):
    support, _, outside_pm, third_person, delegated_project, outside_project, support_ctx = _scenario(db_session)
    delegated_task = Task(
        project_id=delegated_project.id,
        title="Tarefa no projeto delegado",
        created_by_person_id=third_person.id,
        assigned_to_person_id=third_person.id,
    )
    outside_task = Task(
        project_id=outside_project.id,
        title="Tarefa fora da delegação",
        created_by_person_id=support.id,
        assigned_to_person_id=support.id,
    )
    db_session.add_all([delegated_task, outside_task])
    db_session.flush()

    assert can_view_task(support_ctx, delegated_task) is True
    assert outside_project.pm_person_id == outside_pm.id
    assert can_view_task(support_ctx, outside_task) is False


def test_support_can_edit_only_own_or_assigned_task_in_delegated_project(db_session):
    support, _, _, third_person, delegated_project, outside_project, support_ctx = _scenario(db_session)
    delegated_created = Task(
        project_id=delegated_project.id,
        title="Tarefa criada pelo suporte",
        created_by_person_id=support.id,
        assigned_to_person_id=third_person.id,
    )
    delegated_assigned = Task(
        project_id=delegated_project.id,
        title="Tarefa atribuída ao suporte",
        created_by_person_id=third_person.id,
        assigned_to_person_id=support.id,
    )
    delegated_third_party = Task(
        project_id=delegated_project.id,
        title="Tarefa de terceiro",
        created_by_person_id=third_person.id,
        assigned_to_person_id=third_person.id,
    )
    outside_support_task = Task(
        project_id=outside_project.id,
        title="Tarefa fora da delegação do suporte",
        created_by_person_id=support.id,
        assigned_to_person_id=support.id,
    )
    db_session.add_all([delegated_created, delegated_assigned, delegated_third_party, outside_support_task])
    db_session.flush()

    assert can_edit_task(support_ctx, delegated_created) is True
    assert can_edit_task(support_ctx, delegated_assigned) is True
    assert can_edit_task(support_ctx, delegated_third_party) is False
    assert can_edit_task(support_ctx, outside_support_task) is False


def test_support_visible_projects_query_and_edit_scope_only_follow_delegations(db_session):
    _, _, _, _, delegated_project, outside_project, support_ctx = _scenario(db_session)

    visible_ids = {project.id for project in visible_projects_query(db_session, support_ctx).all()}
    assert visible_ids == {delegated_project.id}
    assert can_view_project(support_ctx, delegated_project) is True
    assert can_view_project(support_ctx, outside_project) is False
    assert can_edit_project(support_ctx, delegated_project) is False


def test_support_visible_tasks_query_returns_only_delegated_project_ids(db_session):
    support, _, _, third_person, delegated_project, outside_project, support_ctx = _scenario(db_session)
    delegated_task = Task(
        project_id=delegated_project.id,
        title="Visível ao suporte",
        created_by_person_id=third_person.id,
    )
    outside_task = Task(
        project_id=outside_project.id,
        title="Atribuída ao suporte mas fora do âmbito",
        created_by_person_id=support.id,
        assigned_to_person_id=support.id,
    )
    db_session.add_all([delegated_task, outside_task])
    db_session.flush()

    visible_ids = {task.id for task in visible_tasks_query(db_session, support_ctx).all()}

    assert visible_ids == {delegated_task.id}


def test_pm_with_view_all_still_sees_task_outside_own_project(db_session):
    _, delegated_pm, _, third_person, _, outside_project, _ = _scenario(db_session)
    task = Task(
        project_id=outside_project.id,
        title="Tarefa fora do projeto do PM",
        created_by_person_id=third_person.id,
    )
    db_session.add(task)
    db_session.flush()
    pm_ctx = AuthContext(
        user=User(person_id=delegated_pm.id, email="pm@example.invalid"),
        person_id=delegated_pm.id,
        role_codes=frozenset({"project_manager"}),
        permission_codes=frozenset({"task.view_all"}),
    )

    assert can_view_task(pm_ctx, task) is True


def test_pm_with_edit_own_still_edits_task_created_outside_own_project(db_session):
    _, delegated_pm, _, _, _, outside_project, _ = _scenario(db_session)
    task = Task(
        project_id=outside_project.id,
        title="Tarefa criada pelo PM fora do seu projeto",
        created_by_person_id=delegated_pm.id,
    )
    db_session.add(task)
    db_session.flush()
    pm_ctx = AuthContext(
        user=User(person_id=delegated_pm.id, email="pm@example.invalid"),
        person_id=delegated_pm.id,
        role_codes=frozenset({"project_manager"}),
        permission_codes=frozenset({"task.edit_own"}),
    )

    assert can_edit_task(pm_ctx, task) is True


def test_support_can_create_task_only_in_delegated_projects(db_session):
    _, _, _, _, delegated_project, outside_project, support_ctx = _scenario(db_session)

    assert can_create_task(support_ctx, delegated_project) is True
    assert can_create_task(support_ctx, outside_project) is False


def test_support_my_process_stages_contains_only_support_delegate_stages(db_session):
    _, _, _, _, delegated_project, outside_project, support_ctx = _scenario(db_session)
    delegated_project.start_date = dt.date(2026, 1, 5)
    outside_project.start_date = dt.date(2026, 1, 5)
    stages = list_my_process_stages(db_session, support_ctx, dt.date(2026, 1, 6))
    assert stages
    assert all(stage.responsible_rule == "support_delegate" for stage in stages)
    assert all(stage.project_id == delegated_project.id for stage in stages)
    assert outside_project.id not in {stage.project_id for stage in stages}


def test_my_process_stages_resolves_owner_and_excludes_completed_or_inactive_projects(db_session):
    support, delegated_pm, _, _, delegated_project, outside_project, support_ctx = _scenario(db_session)
    phase = Phase(code="my-process-phase", name="Fase", sort_order=1)
    support_stage = WorkflowStage(
        phase=phase, code="my-support-stage", title="Suporte", responsible_rule="support_delegate",
        planned_start_offset_days=1, planned_end_offset_days=3, sort_order=1,
    )
    support_subtask = WorkflowSubtask(stage=support_stage, code="my-support-stage.0", title="Tarefa", sort_order=1)
    pm_stage = WorkflowStage(
        phase=phase, code="my-pm-stage", title="PM", responsible_rule="pm",
        planned_start_offset_days=1, planned_end_offset_days=3, sort_order=2,
    )
    pm_subtask = WorkflowSubtask(stage=pm_stage, code="my-pm-stage.0", title="Tarefa", sort_order=1)
    db_session.add_all([phase, support_stage, support_subtask, pm_stage, pm_subtask])
    delegated_project.start_date = dt.date(2026, 1, 5)
    outside_project.start_date = dt.date(2026, 1, 5)
    db_session.flush()

    # O suporte recebe apenas etapas support_delegate dos projetos delegados;
    # etapas PM e o projeto fora do âmbito são invisíveis.
    support_stages = list_my_process_stages(db_session, support_ctx, dt.date(2026, 1, 6))
    support_stage_result = next(stage for stage in support_stages if stage.stage_code == "my-support-stage")
    assert support_stage_result.status == "active"

    db_session.add(ProjectSubtaskProgress(project_id=delegated_project.id, subtask_id=support_subtask.id, done=True))
    db_session.flush()
    assert all(stage.stage_code != "my-support-stage" for stage in list_my_process_stages(db_session, support_ctx, dt.date(2026, 1, 6)))

    pm_ctx = AuthContext(
        user=User(person_id=delegated_pm.id, email="pm@example.invalid"),
        person_id=delegated_pm.id,
        role_codes=frozenset({"project_manager"}),
        permission_codes=frozenset({"project.view_own", "project.edit_own_progress", "workflow.update_progress"}),
    )
    stages = list_my_process_stages(db_session, pm_ctx, dt.date(2026, 1, 6))
    pm_stage_result = next(stage for stage in stages if stage.stage_code == "my-pm-stage")
    assert pm_stage_result.status == "active"

    delegated_project.is_active = False
    db_session.flush()
    assert all(stage.project_id != delegated_project.id for stage in list_my_process_stages(db_session, pm_ctx, dt.date(2026, 1, 6)))


def test_support_delegation_audit_is_transactional_and_idempotent(db_session):
    support, delegated_pm, _, _, _, _, _ = _scenario(db_session)
    admin_ctx = AuthContext(
        user=User(person_id=support.id, email="admin@example.invalid"),
        person_id=support.id,
        role_codes=frozenset({"admin"}),
        permission_codes=frozenset({"admin.manage_users"}),
    )

    upsert_delegation(db_session, pm_person_id=delegated_pm.id, support_person_id=support.id, ctx=admin_ctx)
    assert db_session.query(SupportDelegationHistory).count() == 1
    db_session.flush()
    upsert_delegation(db_session, pm_person_id=delegated_pm.id, support_person_id=support.id, ctx=admin_ctx)
    upsert_delegation(db_session, pm_person_id=delegated_pm.id, support_person_id=support.id, ctx=admin_ctx)
    assert db_session.query(SupportDelegationHistory).count() == 1
    delete_delegation(db_session, pm_person_id=delegated_pm.id, ctx=admin_ctx)
    assert [row.action for row in db_session.query(SupportDelegationHistory).all()] == ["created", "deleted"]
