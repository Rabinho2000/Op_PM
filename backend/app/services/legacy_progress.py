"""Importação do progresso do processo do legado (D-074).

O export do `solcor-gestao.html` guarda, por projeto, `done` (`{"<etapa>.<índice>":
true}`, com o índice **a partir de 0**) e `contactsDone` (`{"c<etapa>": true}`). Os códigos do
catálogo (`etapa-NN.i` e `etapa-NN`) foram escolhidos para corresponderem diretamente a
estas chaves — não há tabelas intermédias.

Regras (todas com testes):
- só se importa o que é **verdadeiro**; um `false` no legado é o mesmo que não estar feito;
- **nunca se sobrescreve** progresso que já exista no Op_PM (marcado aqui, ou já importado):
  o Op_PM manda. Uma corrida repetida não cria nada de novo (idempotente);
- o progresso importado fica com `source="legacy"`, **sem data nem autor** — o legado não os
  guarda, e a interface diz-o em vez de inventar;
- chaves que não correspondem a nada do catálogo carregado são **listadas, nunca escondidas**;
- projetos do export que não existem no Op_PM (por `ProjectExternalId`, nunca por nome) são
  contados e listados;
- um registo de histórico por projeto (`processo:importado`, `import_legacy`), não um por
  subtarefa;
- **não** se importam `commissionedAt` (a data de comissionamento não tem correspondente) nem
  `shift` (deslocamentos por etapa, só 2 dos 295 projetos): são contados no resumo.
"""
from __future__ import annotations

import re
import uuid

from sqlalchemy.orm import Session

from app.audit.log import record_project_change
from app.migration.staging import SOURCE_LEGACY_JSON
from app.models.project import ProjectExternalId, ProjectStageProgress, ProjectSubtaskProgress
from app.models.workflow import WorkflowStage, WorkflowSubtask

_SUBTASK_KEY = re.compile(r"^(\d+)\.(\d+)$")
_CONTACT_KEY = re.compile(r"^c(\d+)$")
MAX_LISTED = 25


def _stage_code(number: int) -> str:
    return f"etapa-{number:02d}"


def import_legacy_progress(db: Session, payload: dict, *, actor_person_id: uuid.UUID | None = None) -> dict:
    """Aplica o progresso do export. Não faz commit (permite `--dry-run`)."""
    projects = payload.get("projects") if isinstance(payload, dict) else None
    if not isinstance(projects, dict):
        raise ValueError("payload inválido: esperado um objeto com a chave 'projects'")

    subtask_ids = {code: sid for code, sid in db.query(WorkflowSubtask.code, WorkflowSubtask.id).all()}
    contact_stage_ids = {
        code: sid
        for code, sid in db.query(WorkflowStage.code, WorkflowStage.id).filter(WorkflowStage.has_contact_checkpoint.is_(True)).all()
    }
    project_by_external = {
        external_id: project_id
        for external_id, project_id in db.query(ProjectExternalId.external_id, ProjectExternalId.project_id).filter(
            ProjectExternalId.source_system == SOURCE_LEGACY_JSON
        )
    }
    existing_subtasks = {(p.project_id, p.subtask_id): p for p in db.query(ProjectSubtaskProgress).all()}
    existing_contacts = {(p.project_id, p.stage_id): p for p in db.query(ProjectStageProgress).all()}

    summary = {
        "projects_seen": len(projects),
        "projects_matched": 0,
        "projects_not_found": [],
        "projects_not_found_count": 0,
        "subtasks_created": 0,
        "subtasks_kept": 0,
        "contacts_created": 0,
        "contacts_kept": 0,
        "false_ignored": 0,
        "unmapped": [],
        "unmapped_count": 0,
        "commissioned_ignored": 0,
        "shift_ignored": 0,
    }

    def unmapped(external_id: str, key: str) -> None:
        summary["unmapped_count"] += 1
        if len(summary["unmapped"]) < MAX_LISTED:
            summary["unmapped"].append(f"{external_id}: {key}")

    for external_id, record in projects.items():
        if not isinstance(record, dict):
            continue
        if record.get("commissionedAt"):
            summary["commissioned_ignored"] += 1
        if record.get("shift"):
            summary["shift_ignored"] += 1
        project_id = project_by_external.get(external_id)
        if project_id is None:
            summary["projects_not_found_count"] += 1
            if len(summary["projects_not_found"]) < MAX_LISTED:
                summary["projects_not_found"].append(external_id)
            continue
        summary["projects_matched"] += 1

        created_subtasks = created_contacts = 0
        for key, value in (record.get("done") or {}).items():
            if not value:
                summary["false_ignored"] += 1
                continue
            match = _SUBTASK_KEY.match(str(key))
            subtask_id = subtask_ids.get(f"{_stage_code(int(match[1]))}.{int(match[2])}") if match else None
            if subtask_id is None:
                unmapped(external_id, str(key))
                continue
            if (project_id, subtask_id) in existing_subtasks:
                summary["subtasks_kept"] += 1
                continue
            row = ProjectSubtaskProgress(project_id=project_id, subtask_id=subtask_id, done=True, source="legacy")
            db.add(row)
            existing_subtasks[(project_id, subtask_id)] = row
            created_subtasks += 1

        for key, value in (record.get("contactsDone") or {}).items():
            if not value:
                summary["false_ignored"] += 1
                continue
            match = _CONTACT_KEY.match(str(key))
            stage_id = contact_stage_ids.get(_stage_code(int(match[1]))) if match else None
            if stage_id is None:
                unmapped(external_id, str(key))
                continue
            if (project_id, stage_id) in existing_contacts:
                summary["contacts_kept"] += 1
                continue
            row = ProjectStageProgress(project_id=project_id, stage_id=stage_id, contact_done=True, source="legacy")
            db.add(row)
            existing_contacts[(project_id, stage_id)] = row
            created_contacts += 1

        summary["subtasks_created"] += created_subtasks
        summary["contacts_created"] += created_contacts
        if created_subtasks or created_contacts:
            record_project_change(
                db,
                project_id=project_id,
                field_name="processo:importado",
                old_value=None,
                new_value=f"{created_subtasks} subtarefas, {created_contacts} contactos",
                source="import_legacy",
                changed_by_person_id=actor_person_id,
                note="Progresso do processo importado do legado (sem data nem autor).",
            )
    db.flush()
    return summary
