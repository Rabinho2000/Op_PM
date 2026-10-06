from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session, selectinload

from app.models.project import Project, ProjectSubtaskProgress
from app.models.workflow import Phase, WorkflowStage
from app.schemas.my_process import MyProcessStageRead
from app.security.permissions import AuthContext, can_update_process_stage
from app.services.process import NO_OVERDUE_STATES, _stage_status
from app.services.projects import visible_projects_query
from app.services.installers import business_day


def list_my_process_stages(db: Session, ctx: AuthContext, today: dt.date) -> list[MyProcessStageRead]:
    projects = visible_projects_query(db, ctx).filter(Project.is_active.is_(True)).options(selectinload(Project.pm)).all()
    stages = (
        db.query(WorkflowStage)
        .options(selectinload(WorkflowStage.subtasks))
        .join(Phase, WorkflowStage.phase_id == Phase.id)
        .order_by(Phase.sort_order, WorkflowStage.sort_order)
        .all()
    )
    if not projects or not stages:
        return []
    project_ids = [p.id for p in projects]
    progress = db.query(ProjectSubtaskProgress).filter(ProjectSubtaskProgress.project_id.in_(project_ids)).all()
    done_by = {(row.project_id, row.subtask_id): bool(row.done) for row in progress}
    result: list[MyProcessStageRead] = []
    for project in projects:
        for stage in stages:
            if not can_update_process_stage(ctx, project, stage):
                continue
            subtasks = sorted(stage.subtasks, key=lambda item: item.sort_order)
            done_count = sum(done_by.get((project.id, subtask.id), False) for subtask in subtasks)
            done = bool(subtasks) and done_count == len(subtasks)
            # A vista pessoal não é a lista de tudo o que o utilizador pode
            # editar: mostra apenas as etapas cuja responsabilidade resolvida
            # é a pessoa autenticada. Um PM fica com as etapas `pm`; Suporte
            # fica com as etapas `support_delegate` dos projetos delegados.
            if done or (
                stage.responsible_rule == "pm"
                and project.pm_person_id != ctx.person_id
            ) or (
                stage.responsible_rule == "support_delegate"
                and project.pm_person_id not in ctx.delegating_pm_ids
            ):
                continue
            if stage.responsible_rule not in {"pm", "support_delegate"}:
                continue
            start = end = None
            if project.start_date is not None:
                if stage.planned_start_offset_days is not None:
                    start = business_day(project.start_date, stage.planned_start_offset_days)
                if stage.planned_end_offset_days is not None:
                    end = business_day(project.start_date, stage.planned_end_offset_days)
            result.append(MyProcessStageRead(
                project_id=project.id,
                project_name=project.name,
                stage_id=stage.id,
                stage_code=stage.code,
                stage_title=stage.title,
                responsible_rule=stage.responsible_rule,
                status=_stage_status(done, start, end, today, project.lifecycle_status in NO_OVERDUE_STATES),
                planned_start=start,
                planned_end=end,
                done_count=done_count,
                total_count=len(subtasks),
            ))
    return result
