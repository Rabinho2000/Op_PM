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
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.audit.log import record_project_change
from app.models.project import Project, ProjectStageProgress, ProjectSubtaskProgress
from app.models.workflow import WorkflowStage, WorkflowSubtask

DELIVERED = "entregue_cliente"
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

    projects = db.query(Project).filter(Project.is_active.is_(True), Project.lifecycle_status == DELIVERED).all()
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
        marked_subtasks = marked_contacts = 0
        for subtask in subtasks:
            row = existing_subtasks.get((project.id, subtask.id))
            if row is None:
                db.add(ProjectSubtaskProgress(project_id=project.id, subtask_id=subtask.id, done=True, source="inferred"))
                marked_subtasks += 1
            elif not row.done:
                summary["kept_unmarked_in_app"] += 1  # alguém a desmarcou: o Op_PM manda
        for stage in contact_stages:
            row = existing_contacts.get((project.id, stage.id))
            if row is None:
                db.add(ProjectStageProgress(project_id=project.id, stage_id=stage.id, contact_done=True, source="inferred"))
                marked_contacts += 1
            elif not row.contact_done:
                summary["kept_unmarked_in_app"] += 1
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
