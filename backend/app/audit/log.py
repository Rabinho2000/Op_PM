"""Ponto único de escrita de auditoria. Qualquer serviço que altere um campo
de `Project` deve chamar `record_project_change` em vez de escrever
diretamente em `ProjectHistory` — mantém a regra "append-only" num só sítio.
"""
from __future__ import annotations

import datetime as dt
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.ai import AiAuditLog
from app.models.project import ProjectHistory


def record_project_change(
    db: Session,
    *,
    project_id: UUID,
    field_name: str,
    old_value: str | None,
    new_value: str | None,
    source: str,
    changed_by_person_id: UUID | None = None,
    note: str = "",
) -> ProjectHistory:
    if old_value == new_value:
        # Não gravar "alterações" que não mudam nada — corrige, por desenho,
        # o bug conhecido do script legado `clickup_sync.py` que marcava
        # campos como alterados mesmo sem diferença real (C-08 no repositório
        # legado).
        raise ValueError("old_value e new_value são iguais — nada a registar")
    entry = ProjectHistory(
        project_id=project_id,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        changed_by_person_id=changed_by_person_id,
        source=source,
        note=note,
        changed_at=dt.datetime.now(dt.timezone.utc),
    )
    db.add(entry)
    return entry


def record_ai_action(
    db: Session,
    *,
    tool_name: str,
    input_summary: str,
    output_summary: str,
    requested_by_person_id: UUID | None = None,
    related_entity_type: str | None = None,
    related_entity_id: UUID | None = None,
) -> AiAuditLog:
    """Toda a chamada a uma ferramenta de IA fica aqui, com `status='proposed'`
    por omissão. Nenhuma ferramenta pode chamar isto e já marcar `executed`
    para uma ação irreversível — isso exige uma chamada humana separada a
    `approve_ai_action`."""
    entry = AiAuditLog(
        tool_name=tool_name,
        input_summary=input_summary,
        output_summary=output_summary,
        requested_by_person_id=requested_by_person_id,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
        status="proposed",
    )
    db.add(entry)
    return entry


def approve_ai_action(db: Session, entry: AiAuditLog, *, approved_by_person_id: UUID) -> AiAuditLog:
    entry.status = "approved"
    entry.approved_by_person_id = approved_by_person_id
    entry.approved_at = dt.datetime.now(dt.timezone.utc)
    return entry
