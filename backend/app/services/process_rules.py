"""Regra de conclusão por estado do projeto (D-075).

Um projeto **entregue ao cliente** já passou por toda a obra: só lhe falta a inspeção
final e o certificado. Por isso, o que o processo ainda mostra por fazer nas outras
etapas é falta de registo (o legado nunca as marcou), não trabalho pendente. Esta regra
conclui essas etapas e deixa por fazer só a(s) etapa(s) excecionada(s) — por omissão a
`etapa-18` (inspeção e certificado).

Garantias (todas com testes):
- só projetos **ativos** em `entregue_cliente`; nunca outros estados;
- **nunca sobrescreve** progresso que já exista: uma subtarefa já feita (na aplicação ou
  importada) fica como está, e uma que alguém desmarcou na aplicação continua por fazer
  (o Op_PM manda);
- o que a regra conclui fica com `source="inferred"`, sem data nem autor, e a interface
  diz-o; um registo de histórico por projeto (`processo:concluído por regra`, `rule`);
- idempotente; a etapa excecionada nunca é tocada (nem o seu ponto de contacto).

Um projeto em **certificado final** já tem também a inspeção e o certificado: quando passa
para esse estado, `complete_certified_project` conclui **todas** as etapas, com as mesmas
garantias (chamado por `change_lifecycle_status` e pela criação de projetos).
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.audit.log import record_project_change
from app.models.project import Project, ProjectStageProgress, ProjectSubtaskProgress
from app.models.workflow import WorkflowStage, WorkflowSubtask

DELIVERED = "entregue_cliente"
CERTIFIED = "certificado_final"
DEFAULT_EXCEPT_STAGES = ("etapa-18",)


class RuleError(ValueError):
    """Erro de regra/entrada — mensagem segura para mostrar."""


def complete_delivered_projects(
    db: Session,
    *,
    except_stage_codes: tuple[str, ...] = DEFAULT_EXCEPT_STAGES,
    actor_person_id: uuid.UUID | None = None,
) -> dict:
    """Aplica a regra. Não faz commit (permite `--dry-run`)."""
    stages = db.query(WorkflowStage).all()
    if not stages:
        raise RuleError("o catálogo do processo não está carregado")
    known = {s.code for s in stages}
    unknown = sorted(set(except_stage_codes) - known)
    if unknown:
        raise RuleError(f"etapa(s) desconhecida(s): {', '.join(unknown)}")
    to_complete = [s for s in stages if s.code not in except_stage_codes]
    stage_by_id = {s.id: s for s in to_complete}
    subtasks = [t for t in db.query(WorkflowSubtask).all() if t.stage_id in stage_by_id]
    contact_stages = [s for s in to_complete if s.has_contact_checkpoint]

    projects = db.query(Project).filter(
        Project.is_active.is_(True), Project.deleted_at.is_(None), Project.lifecycle_status == DELIVERED
    ).all()
    project_ids = [p.id for p in projects]
    existing_subtasks = {
        (r.project_id, r.subtask_id): r
        for r in db.query(ProjectSubtaskProgress).filter(ProjectSubtaskProgress.project_id.in_(project_ids))
    } if project_ids else {}
    existing_contacts = {
        (r.project_id, r.stage_id): r
        for r in db.query(ProjectStageProgress).filter(ProjectStageProgress.project_id.in_(project_ids))
    } if project_ids else {}

    summary = {
        "projects": len(projects),
        "projects_changed": 0,
        "subtasks_marked": 0,
        "contacts_marked": 0,
        "kept_unmarked_in_app": 0,
        "excepted_stages": list(except_stage_codes),
    }
    for project in projects:
        marked_subtasks, marked_contacts, kept = _complete_project(
            db, project.id, subtasks, contact_stages, existing_subtasks, existing_contacts
        )
        summary["kept_unmarked_in_app"] += kept
        summary["subtasks_marked"] += marked_subtasks
        summary["contacts_marked"] += marked_contacts
        if marked_subtasks or marked_contacts:
            summary["projects_changed"] += 1
            record_project_change(
                db,
                project_id=project.id,
                field_name="processo:concluído por regra",
                old_value=None,
                new_value=f"{marked_subtasks} subtarefas, {marked_contacts} contactos",
                source="rule",
                changed_by_person_id=actor_person_id,
                note=(
                    "Projeto entregue ao cliente: etapas concluídas por regra; só falta "
                    + ", ".join(except_stage_codes)
                    + " (sem data nem autor)."
                ),
            )
    db.flush()
    return summary


def _complete_project(db, project_id, subtasks, contact_stages, existing_subtasks, existing_contacts) -> tuple[int, int, int]:
    """Marca como feito (`inferred`) o que não tem registo; nunca toca no que existe.
    Devolve (subtarefas marcadas, contactos marcados, itens desmarcados mantidos)."""
    marked_subtasks = marked_contacts = kept = 0
    for subtask in subtasks:
        row = existing_subtasks.get((project_id, subtask.id))
        if row is None:
            db.add(ProjectSubtaskProgress(project_id=project_id, subtask_id=subtask.id, done=True, source="inferred"))
            marked_subtasks += 1
        elif not row.done:
            kept += 1  # alguém a desmarcou: o Op_PM manda
    for stage in contact_stages:
        row = existing_contacts.get((project_id, stage.id))
        if row is None:
            db.add(ProjectStageProgress(project_id=project_id, stage_id=stage.id, contact_done=True, source="inferred"))
            marked_contacts += 1
        elif not row.contact_done:
            kept += 1
    return marked_subtasks, marked_contacts, kept


def complete_certified_project(
    db: Session, project: Project, *, actor_person_id: uuid.UUID | None = None
) -> tuple[int, int]:
    """Projeto que passou a certificado final: conclui todas as etapas do processo.
    Sem catálogo carregado não faz nada. Não faz commit. Devolve (subtarefas, contactos)."""
    if project.lifecycle_status != CERTIFIED or not project.is_active or project.deleted_at is not None:
        return 0, 0
    stages = db.query(WorkflowStage).all()
    if not stages:
        return 0, 0
    subtasks = db.query(WorkflowSubtask).all()
    contact_stages = [s for s in stages if s.has_contact_checkpoint]
    existing_subtasks = {
        (r.project_id, r.subtask_id): r
        for r in db.query(ProjectSubtaskProgress).filter(ProjectSubtaskProgress.project_id == project.id)
    }
    existing_contacts = {
        (r.project_id, r.stage_id): r
        for r in db.query(ProjectStageProgress).filter(ProjectStageProgress.project_id == project.id)
    }
    marked_subtasks, marked_contacts, _ = _complete_project(
        db, project.id, subtasks, contact_stages, existing_subtasks, existing_contacts
    )
    if marked_subtasks or marked_contacts:
        record_project_change(
            db,
            project_id=project.id,
            field_name="processo:concluído por regra",
            old_value=None,
            new_value=f"{marked_subtasks} subtarefas, {marked_contacts} contactos",
            source="rule",
            changed_by_person_id=actor_person_id,
            note="Projeto em certificado final: processo concluído por regra (sem data nem autor).",
        )
    db.flush()
    return marked_subtasks, marked_contacts
