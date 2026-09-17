"""Percurso de obra de um projeto (D-052): as etapas do processo com datas
previstas, estado calculado e progresso das subtarefas/pontos de contacto.

Regras (as mesmas da plataforma original `solcor-gestao.html`):
- Prazos em **dias úteis** (segunda a sexta) a partir de
  `Project.start_date`; o dia 1 é a própria data de início (ou o dia útil
  seguinte, se calhar a um fim de semana). Feriados não são descontados.
- Uma etapa está concluída quando todas as suas subtarefas estão feitas.
- As dependências **só informam** ("a aguardar etapa N") — nada impede
  marcar trabalho fora de ordem (OPEN_QUESTIONS #19: sem regra de avanço
  de fase confirmada, não se inventa um bloqueio).
- Escrever progresso exige poder editar o projeto (`can_edit_project`):
  `project.edit_all`, ou `project.edit_own_progress` sendo o PM do
  projeto. Cada alteração fica no histórico do projeto.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import uuid

from sqlalchemy.orm import Session

from app.audit.log import record_project_change
from app.models.project import Project, ProjectStageProgress, ProjectSubtaskProgress
from app.models.workflow import Phase, WorkflowStage, WorkflowSubtask
from app.security.permissions import AuthContext, PermissionDenied, can_edit_project
from app.utils.timezones import today_lisbon

STAGE_DONE = "concluida"
STAGE_IN_PROGRESS = "em_curso"
STAGE_OVERDUE = "atrasada"
STAGE_WAITING = "a_aguardar"
STAGE_NOT_STARTED = "por_iniciar"


def business_day(start: dt.date, day_number: int) -> dt.date:
    """Data do dia útil número `day_number` (1 = primeiro dia útil a partir
    de `start`, inclusive)."""
    current = start
    while current.weekday() >= 5:
        current += dt.timedelta(days=1)
    remaining = day_number - 1
    while remaining > 0:
        current += dt.timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


@dataclasses.dataclass
class SubtaskView:
    code: str
    title: str
    is_client_contact: bool
    done: bool
    done_at: dt.datetime | None


@dataclasses.dataclass
class StageView:
    code: str
    number: int
    title: str
    phase_code: str
    responsible_label: str
    responsible_role_code: str | None
    note: str
    depends_on_number: int | None
    start_day: int | None
    end_day: int | None
    planned_start: dt.date | None
    planned_end: dt.date | None
    status: str
    done_count: int
    total_count: int
    subtasks: list[SubtaskView]
    contact_type: str | None
    contact_note: str
    contact_date: dt.date | None
    contact_done: bool
    contact_overdue: bool


@dataclasses.dataclass
class PhaseView:
    code: str
    name: str
    color: str
    done_count: int
    total_count: int


@dataclasses.dataclass
class ProjectWorkflowView:
    project_id: uuid.UUID
    start_date: dt.date | None
    planned_end: dt.date | None
    total_days: int
    progress_percent: int
    done_count: int
    total_count: int
    current_stage_number: int | None
    current_phase_code: str | None
    overdue_stages_count: int
    pending_contacts_count: int
    can_edit: bool
    phases: list[PhaseView]
    stages: list[StageView]


def _stage_status(
    done: int, total: int, planned_end: dt.date | None, dependency_done: bool, today: dt.date
) -> str:
    if total and done == total:
        return STAGE_DONE
    if planned_end is not None and today > planned_end:
        return STAGE_OVERDUE
    if done > 0:
        return STAGE_IN_PROGRESS
    if not dependency_done:
        return STAGE_WAITING
    return STAGE_NOT_STARTED


def build_project_workflow(
    db: Session, project: Project, ctx: AuthContext, today: dt.date | None = None
) -> ProjectWorkflowView:
    today = today or today_lisbon()
    phases = db.query(Phase).order_by(Phase.sort_order).all()
    stages = db.query(WorkflowStage).order_by(WorkflowStage.sort_order).all()
    subtasks = db.query(WorkflowSubtask).order_by(WorkflowSubtask.sort_order).all()
    sub_progress = {
        p.subtask_id: p
        for p in db.query(ProjectSubtaskProgress).filter(ProjectSubtaskProgress.project_id == project.id).all()
    }
    stage_progress = {
        p.stage_id: p
        for p in db.query(ProjectStageProgress).filter(ProjectStageProgress.project_id == project.id).all()
    }

    subs_by_stage: dict[uuid.UUID, list[WorkflowSubtask]] = {}
    for sub in subtasks:
        subs_by_stage.setdefault(sub.stage_id, []).append(sub)
    stage_by_id = {s.id: s for s in stages}
    phase_by_id = {p.id: p for p in phases}
    start = project.start_date

    # Conclusão por etapa primeiro (as dependências precisam dela).
    done_by_stage: dict[uuid.UUID, tuple[int, int]] = {}
    for stage in stages:
        subs = subs_by_stage.get(stage.id, [])
        done = sum(1 for s in subs if sub_progress.get(s.id) and sub_progress[s.id].done)
        done_by_stage[stage.id] = (done, len(subs))

    def is_done(stage_id: uuid.UUID | None) -> bool:
        if stage_id is None:
            return True
        done, total = done_by_stage.get(stage_id, (0, 0))
        return total > 0 and done == total

    stage_views: list[StageView] = []
    for stage in stages:
        done, total = done_by_stage[stage.id]
        planned_start = (
            business_day(start, stage.planned_start_offset_days)
            if start and stage.planned_start_offset_days
            else None
        )
        planned_end = (
            business_day(start, stage.planned_end_offset_days) if start and stage.planned_end_offset_days else None
        )
        dep = stage_by_id.get(stage.depends_on_stage_id) if stage.depends_on_stage_id else None
        progress = stage_progress.get(stage.id)
        contact_done = bool(progress and progress.contact_done)
        contact_date = business_day(start, stage.contact_day) if start and stage.contact_day else None
        stage_views.append(
            StageView(
                code=stage.code,
                number=stage.sort_order,
                title=stage.title,
                phase_code=phase_by_id[stage.phase_id].code,
                responsible_label=stage.responsible_label,
                responsible_role_code=stage.responsible_role_code,
                note=stage.note,
                depends_on_number=dep.sort_order if dep else None,
                start_day=stage.planned_start_offset_days,
                end_day=stage.planned_end_offset_days,
                planned_start=planned_start,
                planned_end=planned_end,
                status=_stage_status(done, total, planned_end, is_done(stage.depends_on_stage_id), today),
                done_count=done,
                total_count=total,
                subtasks=[
                    SubtaskView(
                        code=s.code,
                        title=s.title,
                        is_client_contact=s.is_client_contact,
                        done=bool(sub_progress.get(s.id) and sub_progress[s.id].done),
                        done_at=sub_progress[s.id].done_at if s.id in sub_progress else None,
                    )
                    for s in subs_by_stage.get(stage.id, [])
                ],
                contact_type=stage.contact_type if stage.has_contact_checkpoint else None,
                contact_note=stage.contact_note,
                contact_date=contact_date,
                contact_done=contact_done,
                contact_overdue=bool(
                    stage.has_contact_checkpoint and not contact_done and contact_date and today > contact_date
                ),
            )
        )

    phase_views = []
    for phase in phases:
        in_phase = [s for s in stages if s.phase_id == phase.id]
        phase_views.append(
            PhaseView(
                code=phase.code,
                name=phase.name,
                color=phase.color_hex,
                done_count=sum(done_by_stage[s.id][0] for s in in_phase),
                total_count=sum(done_by_stage[s.id][1] for s in in_phase),
            )
        )

    done_total = sum(d for d, _ in done_by_stage.values())
    all_total = sum(t for _, t in done_by_stage.values())
    current = next((v for v in stage_views if v.status != STAGE_DONE), None)
    total_days = max((s.planned_end_offset_days or 0 for s in stages), default=0)
    return ProjectWorkflowView(
        project_id=project.id,
        start_date=start,
        planned_end=business_day(start, total_days) if start and total_days else None,
        total_days=total_days,
        progress_percent=round(100 * done_total / all_total) if all_total else 0,
        done_count=done_total,
        total_count=all_total,
        current_stage_number=current.number if current else None,
        current_phase_code=current.phase_code if current else None,
        overdue_stages_count=sum(1 for v in stage_views if v.status == STAGE_OVERDUE),
        pending_contacts_count=sum(1 for v in stage_views if v.contact_overdue),
        can_edit=can_edit_project(ctx, project),
        phases=phase_views,
        stages=stage_views,
    )


class WorkflowItemNotFound(Exception):
    pass


def _require_edit(ctx: AuthContext, project: Project) -> None:
    if not can_edit_project(ctx, project):
        raise PermissionDenied("project.edit_own_progress")


def _flag(value: bool) -> str:
    return "feito" if value else "por fazer"


def set_subtask_done(db: Session, ctx: AuthContext, project: Project, subtask_code: str, done: bool) -> bool:
    """Marca/desmarca uma subtarefa. Devolve True se algo mudou."""
    _require_edit(ctx, project)
    sub = db.query(WorkflowSubtask).filter(WorkflowSubtask.code == subtask_code).one_or_none()
    if sub is None:
        raise WorkflowItemNotFound(subtask_code)
    progress = (
        db.query(ProjectSubtaskProgress)
        .filter(ProjectSubtaskProgress.project_id == project.id, ProjectSubtaskProgress.subtask_id == sub.id)
        .one_or_none()
    )
    previous = bool(progress and progress.done)
    if previous == done:
        return False
    if progress is None:
        progress = ProjectSubtaskProgress(project_id=project.id, subtask_id=sub.id)
        db.add(progress)
    progress.done = done
    progress.done_at = dt.datetime.now(dt.timezone.utc) if done else None
    progress.done_by_person_id = ctx.person_id if done else None
    record_project_change(
        db,
        project_id=project.id,
        field_name=f"percurso.{sub.code}",
        old_value=_flag(previous),
        new_value=_flag(done),
        source="ui",
        changed_by_person_id=ctx.person_id,
        note=sub.title,
    )
    db.commit()
    return True


def set_stage_contact_done(db: Session, ctx: AuthContext, project: Project, stage_code: str, done: bool) -> bool:
    _require_edit(ctx, project)
    stage = db.query(WorkflowStage).filter(WorkflowStage.code == stage_code).one_or_none()
    if stage is None or not stage.has_contact_checkpoint:
        raise WorkflowItemNotFound(stage_code)
    progress = (
        db.query(ProjectStageProgress)
        .filter(ProjectStageProgress.project_id == project.id, ProjectStageProgress.stage_id == stage.id)
        .one_or_none()
    )
    previous = bool(progress and progress.contact_done)
    if previous == done:
        return False
    if progress is None:
        progress = ProjectStageProgress(project_id=project.id, stage_id=stage.id)
        db.add(progress)
    progress.contact_done = done
    progress.contact_done_at = dt.datetime.now(dt.timezone.utc) if done else None
    progress.contact_done_by_person_id = ctx.person_id if done else None
    record_project_change(
        db,
        project_id=project.id,
        field_name=f"percurso.{stage.code}.contacto",
        old_value=_flag(previous),
        new_value=_flag(done),
        source="ui",
        changed_by_person_id=ctx.person_id,
        note=f"Contacto com o cliente — {stage.title}",
    )
    db.commit()
    return True
