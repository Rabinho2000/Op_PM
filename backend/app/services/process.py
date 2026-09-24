"""O processo de um projeto (D-073): o catálogo (fases → etapas → subtarefas) com o
progresso do projeto, os prazos calculados e o responsável **resolvido por projeto**.

- Prazos: `start_date` do projeto + os dias úteis da etapa (o mesmo cálculo do
  legado e da janela da obra, D-071). Sem `start_date` não há datas.
- Estado da etapa: `done` (todas as subtarefas feitas), `overdue` (o fim planeado já
  passou), `active` (hoje está dentro da janela), `upcoming`, `no_date`.
- Responsável (`WorkflowStage.responsible_rule`):
  - `role`: o papel (quem o tem, nomeado se houver);
  - `pm`: o PM do projeto;
  - `support_delegate`: a pessoa de suporte delegada para o PM do projeto
    (`SupportDelegation`), ou o próprio PM se não houver delegação;
  - `installer`: o instalador da obra;
  - `team_leader`: o chefe da equipa atribuída.
  Um dado em falta (sem PM, sem instalador, sem equipa/chefe) fica `unresolved`.
- Escrever progresso exige `workflow.update_progress` no âmbito do projeto; cada
  alteração grava uma entrada em `project_history`, e repetir o mesmo valor não faz nada.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.audit.log import record_project_change
from app.models.identity import Role, User, UserRole
from app.models.people import Person
from app.models.project import Project, ProjectStageProgress, ProjectSubtaskProgress
from app.models.workflow import Phase, SupportDelegation, WorkflowStage, WorkflowSubtask
from app.schemas.process import (
    ProcessContactRead,
    ProcessPhaseRead,
    ProcessRead,
    ProcessResponsibleRead,
    ProcessStageRead,
    ProcessSubtaskRead,
    ProcessSummary,
)
from app.security.permissions import AuthContext, PermissionDenied, can_update_process
from app.services.installers import business_day


class ProcessError(ValueError):
    """Erro de regra de negócio — mensagem segura para mostrar."""


def _role_holders(db: Session, role_codes: set[str]) -> dict[str, list[str]]:
    if not role_codes:
        return {}
    rows = (
        db.query(Role.code, Person.display_name)
        .join(UserRole, UserRole.role_id == Role.id)
        .join(User, User.id == UserRole.user_id)
        .join(Person, Person.id == User.person_id)
        .filter(Role.code.in_(role_codes), User.is_active.is_(True), Person.is_active.is_(True))
        .order_by(Person.display_name)
        .all()
    )
    holders: dict[str, list[str]] = {}
    for code, name in rows:
        holders.setdefault(code, []).append(name)
    return holders


def _resolve_responsible(
    stage: WorkflowStage,
    project: Project,
    role_holders: dict[str, list[str]],
    support_name: str | None,
) -> ProcessResponsibleRead:
    label = stage.responsible_label or "—"
    rule = stage.responsible_rule
    pm_name = project.pm.display_name if project.pm else None
    if rule == "role":
        return ProcessResponsibleRead(rule=rule, label=label, names=role_holders.get(stage.responsible_role_code or "", []), unresolved=False)
    if rule == "pm":
        return ProcessResponsibleRead(rule=rule, label=label, names=[pm_name] if pm_name else [], unresolved=pm_name is None)
    if rule == "support_delegate":
        if support_name:
            return ProcessResponsibleRead(rule=rule, label=label, names=[support_name], unresolved=False, delegated=True)
        return ProcessResponsibleRead(rule=rule, label=label, names=[pm_name] if pm_name else [], unresolved=pm_name is None)
    if rule == "installer":
        name = project.installer.name if project.installer else None
        return ProcessResponsibleRead(rule=rule, label=label, names=[name] if name else [], unresolved=name is None)
    if rule == "team_leader":
        leader = project.installer_team.leader_name if project.installer_team else None
        return ProcessResponsibleRead(rule=rule, label=label, names=[leader] if leader else [], unresolved=leader is None)
    return ProcessResponsibleRead(rule=rule, label=label, names=[], unresolved=True)


# Projetos já entregues ou certificados: as etapas por fazer não são trabalho em atraso
# (estão à espera da inspeção/certificado, ou nunca foram registadas) — D-075.
NO_OVERDUE_STATES = frozenset({"entregue_cliente", "certificado_final"})


def _stage_status(
    done: bool, start: dt.date | None, end: dt.date | None, today: dt.date, hide_overdue: bool = False
) -> str:
    """`pending` ("por concluir") no lugar de `overdue`/`active`/`upcoming`/`no_date` quando o
    projeto já foi entregue: um projeto entregue nunca tem etapas "em atraso"."""
    if done:
        return "done"
    if hide_overdue:
        return "pending"
    if start is None or end is None:
        return "no_date"
    if today > end:
        return "overdue"
    if today >= start:
        return "active"
    return "upcoming"


def build_project_process(db: Session, project: Project, ctx: AuthContext, today: dt.date) -> ProcessRead:
    phases = (
        db.query(Phase)
        .options(selectinload(Phase.stages).selectinload(WorkflowStage.subtasks))
        .order_by(Phase.sort_order)
        .all()
    )
    subtask_progress = {
        p.subtask_id: p for p in db.query(ProjectSubtaskProgress).filter(ProjectSubtaskProgress.project_id == project.id)
    }
    stage_progress = {
        p.stage_id: p for p in db.query(ProjectStageProgress).filter(ProjectStageProgress.project_id == project.id)
    }
    stage_by_id = {s.id: s for phase in phases for s in phase.stages}

    person_ids = {p.done_by_person_id for p in subtask_progress.values() if p.done_by_person_id}
    names = {p.id: p.display_name for p in db.query(Person).filter(Person.id.in_(person_ids)).all()} if person_ids else {}
    holders = _role_holders(db, {s.responsible_role_code for s in stage_by_id.values() if s.responsible_rule == "role" and s.responsible_role_code})
    support_name = None
    if project.pm_person_id is not None:
        delegation = db.query(SupportDelegation).filter(SupportDelegation.pm_person_id == project.pm_person_id).one_or_none()
        if delegation is not None:
            support = db.get(Person, delegation.support_person_id)
            support_name = support.display_name if support else None

    hide_overdue = project.lifecycle_status in NO_OVERDUE_STATES
    total_done = total_all = stages_done = stages_total = overdue_stages = overdue_contacts = 0
    phase_reads: list[ProcessPhaseRead] = []
    for phase in phases:
        stage_reads: list[ProcessStageRead] = []
        for stage in sorted(phase.stages, key=lambda s: s.sort_order):
            subtasks = sorted(stage.subtasks, key=lambda s: s.sort_order)
            subtask_reads = []
            done_count = 0
            for subtask in subtasks:
                progress = subtask_progress.get(subtask.id)
                done = bool(progress and progress.done)
                done_count += done
                subtask_reads.append(
                    ProcessSubtaskRead(
                        id=subtask.id,
                        code=subtask.code,
                        title=subtask.title,
                        done=done,
                        done_at=progress.done_at if done and progress else None,
                        done_by_display_name=names.get(progress.done_by_person_id) if done and progress and progress.done_by_person_id else None,
                        source=progress.source if done and progress else "ui",
                    )
                )
            stage_done = bool(subtasks) and done_count == len(subtasks)
            start = end = None
            if project.start_date is not None and stage.planned_start_offset_days and stage.planned_end_offset_days:
                start = business_day(project.start_date, stage.planned_start_offset_days)
                end = business_day(project.start_date, stage.planned_end_offset_days)
            status = _stage_status(stage_done, start, end, today, hide_overdue)

            contact = None
            if stage.has_contact_checkpoint and stage.contact_day:
                cp = stage_progress.get(stage.id)
                contact_done = bool(cp and cp.contact_done)
                planned = business_day(project.start_date, stage.contact_day) if project.start_date else None
                contact_overdue = not hide_overdue and not contact_done and planned is not None and planned < today
                overdue_contacts += contact_overdue
                contact = ProcessContactRead(
                    day=stage.contact_day,
                    kind=stage.contact_kind or "contacto",
                    note=stage.contact_note,
                    planned_date=planned,
                    done=contact_done,
                    done_at=cp.contact_done_at if contact_done and cp else None,
                    overdue=contact_overdue,
                    source=cp.source if contact_done and cp else "ui",
                )
            dep = stage_by_id.get(stage.depends_on_stage_id) if stage.depends_on_stage_id else None
            stage_reads.append(
                ProcessStageRead(
                    id=stage.id,
                    code=stage.code,
                    title=stage.title,
                    note=stage.note,
                    responsible=_resolve_responsible(stage, project, holders, support_name),
                    depends_on_code=dep.code if dep else None,
                    start_day=stage.planned_start_offset_days,
                    end_day=stage.planned_end_offset_days,
                    planned_start=start,
                    planned_end=end,
                    status=status,
                    done_count=done_count,
                    total_count=len(subtasks),
                    contact=contact,
                    subtasks=subtask_reads,
                )
            )
            total_done += done_count
            total_all += len(subtasks)
            stages_done += stage_done
            stages_total += 1
            overdue_stages += status == "overdue"
        phase_reads.append(
            ProcessPhaseRead(
                id=phase.id,
                code=phase.code,
                name=phase.name,
                color=phase.color_hex,
                done_count=sum(s.done_count for s in stage_reads),
                total_count=sum(s.total_count for s in stage_reads),
                stages=stage_reads,
            )
        )

    return ProcessRead(
        project_id=project.id,
        start_date=project.start_date,
        has_catalog=stages_total > 0,
        can_update=can_update_process(ctx, project),
        phases=[p for p in phase_reads if p.stages],
        summary=ProcessSummary(
            done=total_done,
            total=total_all,
            percent=round(100 * total_done / total_all) if total_all else 0,
            stages_done=stages_done,
            stages_total=stages_total,
            overdue_stages=overdue_stages,
            overdue_contacts=overdue_contacts,
        ),
    )


def progress_percent_by_project(db: Session, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, int] | None:
    """Percentagem do processo (subtarefas feitas / total do catálogo) de vários projetos, em
    **duas queries** (nunca uma por projeto). `None` se o catálogo ainda não foi carregado —
    quem chama usa então a alternativa antiga (as tarefas padrão)."""
    total = db.query(func.count(WorkflowSubtask.id)).scalar() or 0
    if total == 0:
        return None
    if not project_ids:
        return {}
    rows = (
        db.query(ProjectSubtaskProgress.project_id, func.count(ProjectSubtaskProgress.id))
        .filter(ProjectSubtaskProgress.project_id.in_(project_ids), ProjectSubtaskProgress.done.is_(True))
        .group_by(ProjectSubtaskProgress.project_id)
        .all()
    )
    done = dict(rows)
    return {pid: round(100 * done.get(pid, 0) / total) for pid in project_ids}


# --- escrita -----------------------------------------------------------------


def set_subtask_done(db: Session, *, project: Project, subtask_id: uuid.UUID, done: bool, ctx: AuthContext) -> None:
    if not can_update_process(ctx, project):
        raise PermissionDenied("workflow.update_progress")
    subtask = db.get(WorkflowSubtask, subtask_id)
    if subtask is None:
        raise ProcessError("Subtarefa não encontrada.")
    progress = (
        db.query(ProjectSubtaskProgress)
        .filter(ProjectSubtaskProgress.project_id == project.id, ProjectSubtaskProgress.subtask_id == subtask.id)
        .one_or_none()
    )
    was_done = bool(progress and progress.done)
    if was_done == done:
        return
    now = dt.datetime.now(dt.timezone.utc)
    if progress is None:
        progress = ProjectSubtaskProgress(project_id=project.id, subtask_id=subtask.id)
        db.add(progress)
    progress.done = done
    progress.done_at = now if done else None
    progress.done_by_person_id = ctx.person_id if done else None
    record_project_change(
        db,
        project_id=project.id,
        field_name=f"processo:{subtask.code}",
        old_value="feita" if was_done else "pendente",
        new_value="feita" if done else "pendente",
        source="ui",
        changed_by_person_id=ctx.person_id,
        note=subtask.title[:200],
    )
    db.commit()


def set_contact_done(db: Session, *, project: Project, stage_id: uuid.UUID, done: bool, ctx: AuthContext) -> None:
    if not can_update_process(ctx, project):
        raise PermissionDenied("workflow.update_progress")
    stage = db.get(WorkflowStage, stage_id)
    if stage is None:
        raise ProcessError("Etapa não encontrada.")
    if not stage.has_contact_checkpoint:
        raise ProcessError("Esta etapa não tem ponto de contacto.")
    progress = (
        db.query(ProjectStageProgress)
        .filter(ProjectStageProgress.project_id == project.id, ProjectStageProgress.stage_id == stage.id)
        .one_or_none()
    )
    was_done = bool(progress and progress.contact_done)
    if was_done == done:
        return
    if progress is None:
        progress = ProjectStageProgress(project_id=project.id, stage_id=stage.id)
        db.add(progress)
    progress.contact_done = done
    progress.contact_done_at = dt.datetime.now(dt.timezone.utc) if done else None
    progress.contact_done_by_person_id = ctx.person_id if done else None
    record_project_change(
        db,
        project_id=project.id,
        field_name=f"processo:{stage.code}:contacto",
        old_value="feito" if was_done else "pendente",
        new_value="feito" if done else "pendente",
        source="ui",
        changed_by_person_id=ctx.person_id,
        note=stage.title[:200],
    )
    db.commit()
