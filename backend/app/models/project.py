"""Projeto e os seus registos satélite: identificadores externos estáveis,
progresso do workflow e histórico de alterações imutável.

Princípios (ver docs/ARCHITECTURE_PROPOSAL.md e docs/DECISIONS.md):
- `Project.id` é a única chave primária de negócio; nome nunca é chave.
- Correspondência com sistemas externos (ClickUp, Financial…) vive em
  `ProjectExternalId`, nunca inferida do nome em tempo de leitura.
- `ProjectHistory` é append-only: a camada de serviço nunca faz UPDATE/DELETE
  sobre esta tabela, só INSERT. (Fase 0: aplicado por convenção de código —
  ver docs/DECISIONS.md D-006 para o hardening a nível de base de dados.)
- Projetos incompletos (sem PM, sem email, sem coordenadas — 112/194/108 dos
  295 projetos legados, respetivamente) são preservados tal como estão; a
  incompletude se lê pelos campos a NULL, nunca é um motivo de exclusão.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk


class Project(UUIDPk, TimestampMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(512), nullable=False)
    client_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    client_contact: Mapped[str | None] = mapped_column(String(256), nullable=True)
    client_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_kwp: Mapped[float | None] = mapped_column(Float, nullable=True)

    pm_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    current_phase_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("phases.id"), nullable=True
    )

    start_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    # Espelho só-de-leitura do estado no ClickUp — nunca escrito de volta
    # para o ClickUp a partir daqui. Fonte de verdade: ClickUp.
    clickup_status_mirror: Mapped[str | None] = mapped_column(String(128), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="")

    pm: Mapped["Person | None"] = relationship(foreign_keys=[pm_person_id])
    external_ids: Mapped[list["ProjectExternalId"]] = relationship(back_populates="project")

    @property
    def has_pm(self) -> bool:
        return self.pm_person_id is not None

    @property
    def has_email(self) -> bool:
        return bool(self.client_email)

    @property
    def has_coordinates(self) -> bool:
        return self.lat is not None and self.lon is not None

    @property
    def has_contact(self) -> bool:
        return bool(self.client_contact)


class ProjectExternalId(UUIDPk, TimestampMixin, Base):
    """Mapeamento estável projeto ↔ sistema externo. Chave de correspondência
    real das integrações — nunca o nome do projeto (corrige o risco C-07 do
    repositório legado, onde `clickup_sync.py` fazia matching por nome)."""

    __tablename__ = "project_external_ids"
    __table_args__ = (
        UniqueConstraint("source_system", "external_id", name="uq_external_id_per_source"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=False)
    source_system: Mapped[str] = mapped_column(String(32), nullable=False)  # clickup | financial | legacy_json
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    external_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|ok|error
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="external_ids")


class ProjectStageProgress(UUIDPk, TimestampMixin, Base):
    """Conclusão do ponto de contacto de uma etapa para um projeto (ex.:
    "contacto com o cliente feito"). Um registo por (projeto, etapa)."""

    __tablename__ = "project_stage_progress"
    __table_args__ = (UniqueConstraint("project_id", "stage_id", name="uq_project_stage"),)

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=False)
    stage_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("workflow_stages.id"), nullable=False)
    contact_done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    contact_done_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    contact_done_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )


class ProjectSubtaskProgress(UUIDPk, TimestampMixin, Base):
    """Conclusão de uma subtarefa concreta para um projeto. Um registo por
    (projeto, subtarefa) — substitui as chaves posicionais `done['12.3']`
    do `solcor-gestao.html` legado por uma referência de chave estrangeira."""

    __tablename__ = "project_subtask_progress"
    __table_args__ = (UniqueConstraint("project_id", "subtask_id", name="uq_project_subtask"),)

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=False)
    subtask_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("workflow_subtasks.id"), nullable=False
    )
    done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    done_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )


class ProjectHistory(UUIDPk, Base):
    """Auditoria append-only. Sem `TimestampMixin.updated_at` de propósito —
    uma linha de histórico nunca é atualizada, só criada."""

    __tablename__ = "project_history"

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=False)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    # ui | import_legacy | clickup | financial | ai | system
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str] = mapped_column(Text, default="")
    changed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
