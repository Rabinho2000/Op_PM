"""Tarefas operacionais por projeto — checklist geral (visita técnica,
preparação, instalação, comissionamento, fotos) mais qualquer tarefa
ad-hoc criada por um utilizador.

Distinto de propósito de `Phase`/`WorkflowStage`/`WorkflowSubtask` +
`ProjectStageProgress`/`ProjectSubtaskProgress` (ver app/models/workflow.py
e app/models/project.py): esse conjunto modela o *processo* fixo (uma
checklist booleana por etapa/subtarefa definida em catálogo) e já existia
antes deste MVP. O pedido deste MVP é uma entidade de tarefa genérica com
responsável, prioridade, prazo, notas e máquina de estados própria — não
cabe no modelo antigo sem o alargar significativamente. As duas
estruturas coexistem nesta fase; unificá-las fica como decisão em aberto
(ver docs/OPEN_QUESTIONS.md) — nenhum dado foi migrado de uma para a
outra.

`Task.task_type` guarda o código das 5 tarefas padrão criadas para cada
projeto (ver `app/services/tasks.py:ensure_default_tasks_for_project`) ou
"custom" para uma tarefa ad-hoc.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk
from app.utils.timezones import today_lisbon

# Tipos de tarefa padrão criados automaticamente para cada projeto — a
# ordem aqui é a ordem de execução esperada (ver seed/services/tasks.py).
TASK_TYPE_VISITA_TECNICA = "visita_tecnica"
TASK_TYPE_PREPARACAO_INSTALACAO = "preparacao_instalacao"
TASK_TYPE_INSTALACAO = "instalacao"
TASK_TYPE_COMISSIONAMENTO = "comissionamento"
TASK_TYPE_FOTOS_DRIVE = "fotos_drive"
TASK_TYPE_CUSTOM = "custom"

DEFAULT_TASK_TYPES: tuple[tuple[str, str], ...] = (
    (TASK_TYPE_VISITA_TECNICA, "Visita técnica"),
    (TASK_TYPE_PREPARACAO_INSTALACAO, "Preparação da instalação"),
    (TASK_TYPE_INSTALACAO, "Instalação"),
    (TASK_TYPE_COMISSIONAMENTO, "Comissionamento"),
    (TASK_TYPE_FOTOS_DRIVE, "Colocar fotos na Drive"),
)

# Tipos de tarefa cuja conclusão deve acionar o aviso persistente de fotos
# (ver app/services/projects.py:photos_pending_warning).
TASK_TYPES_REQUIRE_PHOTOS = frozenset({TASK_TYPE_VISITA_TECNICA, TASK_TYPE_COMISSIONAMENTO})

STATUS_TODO = "todo"
STATUS_IN_PROGRESS = "in_progress"
STATUS_BLOCKED = "blocked"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"

TASK_STATUSES: frozenset[str] = frozenset(
    {STATUS_TODO, STATUS_IN_PROGRESS, STATUS_BLOCKED, STATUS_DONE, STATUS_CANCELLED}
)

# Estados "abertos" — usados para contar tarefas atrasadas/pendentes no
# dashboard (nunca conta uma tarefa concluída ou cancelada como pendente).
OPEN_TASK_STATUSES: frozenset[str] = frozenset({STATUS_TODO, STATUS_IN_PROGRESS, STATUS_BLOCKED})

PRIORITY_LOW = "low"
PRIORITY_MEDIUM = "medium"
PRIORITY_HIGH = "high"
PRIORITY_URGENT = "urgent"

TASK_PRIORITIES: frozenset[str] = frozenset({PRIORITY_LOW, PRIORITY_MEDIUM, PRIORITY_HIGH, PRIORITY_URGENT})

# Categoria operacional da tarefa — vocabulário pequeno e controlado,
# distinto de `task_type` (tipo funcional específico). `category` separa
# workflow/documentação (não geram dívida operacional) de pendências reais
# de campo/material (ver OPERATIONAL_TASK_CATEGORIES, usado pelo mapa
# operacional — app/services/map.py — para calcular o estado `attention`).
TASK_CATEGORY_WORKFLOW = "workflow"
TASK_CATEGORY_FIELD = "field"
TASK_CATEGORY_MATERIAL = "material"
TASK_CATEGORY_DOCUMENTATION = "documentation"
TASK_CATEGORY_COMMERCIAL = "commercial"
TASK_CATEGORY_OTHER = "other"

TASK_CATEGORIES: frozenset[str] = frozenset(
    {
        TASK_CATEGORY_WORKFLOW,
        TASK_CATEGORY_FIELD,
        TASK_CATEGORY_MATERIAL,
        TASK_CATEGORY_DOCUMENTATION,
        TASK_CATEGORY_COMMERCIAL,
        TASK_CATEGORY_OTHER,
    }
)

# Categorias que contam como dívida operacional para o mapa (`attention`) —
# nunca hardcoded como string "field"/"material" fora deste módulo.
OPERATIONAL_TASK_CATEGORIES: frozenset[str] = frozenset({TASK_CATEGORY_FIELD, TASK_CATEGORY_MATERIAL})

# Categoria por omissão de cada tipo de tarefa padrão (ver DEFAULT_TASK_TYPES
# acima) — usada por ensure_default_tasks_for_project. `custom` (tarefas
# ad-hoc) recebe TASK_CATEGORY_OTHER por omissão.
DEFAULT_TASK_TYPE_CATEGORIES: dict[str, str] = {
    TASK_TYPE_VISITA_TECNICA: TASK_CATEGORY_WORKFLOW,
    TASK_TYPE_PREPARACAO_INSTALACAO: TASK_CATEGORY_WORKFLOW,
    TASK_TYPE_INSTALACAO: TASK_CATEGORY_WORKFLOW,
    TASK_TYPE_COMISSIONAMENTO: TASK_CATEGORY_WORKFLOW,
    TASK_TYPE_FOTOS_DRIVE: TASK_CATEGORY_DOCUMENTATION,
}


class Task(UUIDPk, TimestampMixin, Base):
    __tablename__ = "tasks"

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), default=TASK_TYPE_CUSTOM, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default=STATUS_TODO, nullable=False)
    priority: Mapped[str] = mapped_column(String(16), default=PRIORITY_MEDIUM, nullable=False)
    category: Mapped[str] = mapped_column(String(32), default=TASK_CATEGORY_OTHER, nullable=False)
    assigned_to_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    due_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )

    project: Mapped["Project"] = relationship()
    assigned_to: Mapped["Person | None"] = relationship(foreign_keys=[assigned_to_person_id])

    @property
    def is_overdue(self) -> bool:
        if self.due_date is None or self.status not in OPEN_TASK_STATUSES:
            return False
        return self.due_date < today_lisbon()


class TaskHistory(UUIDPk, Base):
    """Auditoria append-only das alterações a uma tarefa — mesmo padrão de
    `ProjectHistory` (ver app/models/project.py)."""

    __tablename__ = "task_history"

    task_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("tasks.id"), nullable=False)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # ui | system
    note: Mapped[str] = mapped_column(Text, default="")
    changed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
