"""Definição do processo operacional (fases → etapas → subtarefas) como
dados normalizados em base de dados, não como um array hardcoded no
frontend. Isto substitui o padrão do `solcor-gestao.html` legado, onde
`STAGES`/`STAGE_BY_ID` eram uma constante JavaScript e a app de emails e o
script `mark_certified_done.py` duplicavam a mesma estrutura por regex —
ver `.planning/codebase/CONCERNS.md` (C-18) no repositório legado.

O `code` de cada etapa/subtarefa é a chave estável usada por qualquer
integração externa; o `id` (UUID) nunca é reindexado por posição.
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk


class Phase(UUIDPk, TimestampMixin, Base):
    __tablename__ = "phases"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    color_hex: Mapped[str] = mapped_column(String(16), default="#888888")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    stages: Mapped[list["WorkflowStage"]] = relationship(back_populates="phase")


class WorkflowStage(UUIDPk, TimestampMixin, Base):
    __tablename__ = "workflow_stages"

    phase_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("phases.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    # Papel responsável, referenciado por código (ver roles.code) — nunca o
    # nome de uma pessoa concreta hardcoded na definição do processo.
    responsible_role_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    depends_on_stage_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("workflow_stages.id"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_start_offset_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    planned_end_offset_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_contact_checkpoint: Mapped[bool] = mapped_column(default=False, nullable=False)
    contact_note: Mapped[str] = mapped_column(Text, default="")
    # Dia útil (desde o arranque do projeto) do ponto de contacto e o seu tipo
    # ("contacto" com o cliente ou "update" interno). D-073.
    contact_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contact_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Quem é o responsável, resolvido **por projeto** (ver app/services/process.py):
    # `role` (um papel), `pm`, `support_delegate` (o PM, ou a pessoa de suporte
    # delegada), `installer` (o subempreiteiro da obra) ou `team_leader` (o chefe
    # da equipa atribuída). `responsible_label` é o texto a mostrar. D-073.
    responsible_rule: Mapped[str | None] = mapped_column(String(32), nullable=True)
    responsible_label: Mapped[str | None] = mapped_column(String(128), nullable=True)

    phase: Mapped["Phase"] = relationship(back_populates="stages")
    subtasks: Mapped[list["WorkflowSubtask"]] = relationship(back_populates="stage")


class WorkflowSubtask(UUIDPk, TimestampMixin, Base):
    __tablename__ = "workflow_subtasks"

    stage_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("workflow_stages.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    stage: Mapped["WorkflowStage"] = relationship(back_populates="subtasks")


class SupportDelegation(UUIDPk, TimestampMixin, Base):
    """Quem faz as etapas de suporte (licenciamento, projeto eletrotécnico…) nos
    projetos de um PM. Sem linha para um PM, essas etapas são do próprio PM
    (D-073). É dado, não código: mudar a regra é mudar linhas."""

    __tablename__ = "support_delegations"

    pm_person_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("people.id"), unique=True, nullable=False)
    support_person_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("people.id"), nullable=False)
