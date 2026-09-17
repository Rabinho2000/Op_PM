"""Dados satélite do projeto — um registo 1:1 por projeto em cada tabela,
separados de `Project` para não o transformar numa tabela com centenas de
campos opcionais (ver docs/PLAN_OPERATIONS_MVP.md secção 2.1).

`Project.client_name`/`client_contact`/`client_email` continuam a fonte de
verdade para identidade do cliente — `ProjectInstallationData` não duplica
esses três campos, só acrescenta o que falta.

`ProjectCommunicationData` nunca guarda PIN/PUK/password/login/token — não
há campos para isso no modelo, por desenho (ver pedido explícito do MVP de
Operações). Se um dia for necessário guardar credenciais de portal, isso
exige um sistema de secrets/vault separado, nunca esta tabela.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk


class ProjectInstallationData(UUIDPk, TimestampMixin, Base):
    __tablename__ = "project_installation_data"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("projects.id"), unique=True, nullable=False
    )
    client_nif: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contact_person_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    contact_person_role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    district: Mapped[str | None] = mapped_column(String(128), nullable=True)
    municipality: Mapped[str | None] = mapped_column(String(128), nullable=True)
    power_kwp: Mapped[float | None] = mapped_column(nullable=True)
    panel_count: Mapped[int | None] = mapped_column(nullable=True)
    panel_power_wp: Mapped[float | None] = mapped_column(nullable=True)
    inverters: Mapped[str | None] = mapped_column(Text, nullable=True)
    batteries: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_backup: Mapped[bool | None] = mapped_column(nullable=True)
    ev_chargers: Mapped[str | None] = mapped_column(Text, nullable=True)
    installation_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    injection_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    om_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class ProjectLicensingData(UUIDPk, TimestampMixin, Base):
    __tablename__ = "project_licensing_data"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("projects.id"), unique=True, nullable=False
    )
    upac_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dgeg_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cadastro_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    licensing_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    registration_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    certification_request_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    inspecting_entity: Mapped[str | None] = mapped_column(String(256), nullable=True)
    inspection_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    certificate_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    installer: Mapped[str | None] = mapped_column(String(256), nullable=True)
    commercializer: Mapped[str | None] = mapped_column(String(256), nullable=True)
    annual_production_kwh: Mapped[float | None] = mapped_column(nullable=True)
    comments: Mapped[str] = mapped_column(Text, default="")


class ProjectCommunicationData(UUIDPk, TimestampMixin, Base):
    """Dados de comunicação/M2M — acesso restrito por
    `project.view_communication_data`/`edit_communication_data` (ver
    app/security/permissions.py). Nunca guarda credenciais — ver docstring
    do módulo."""

    __tablename__ = "project_communication_data"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("projects.id"), unique=True, nullable=False
    )
    operator: Mapped[str | None] = mapped_column(String(128), nullable=True)
    gsm_m2m_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    card_identifier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    communication_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class ProjectDataHistory(UUIDPk, Base):
    """Auditoria append-only para os três modelos acima — mesmo padrão de
    `ProjectHistory`/`TaskHistory`, mas com `entity_type` a distinguir qual
    das três tabelas foi alterada (evita três tabelas de histórico quase
    idênticas)."""

    __tablename__ = "project_data_history"

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=False)
    # installation | licensing | communication
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )
    # ui | import_notes | import_licensing
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str] = mapped_column(Text, default="")
    changed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = [
    "ProjectInstallationData",
    "ProjectLicensingData",
    "ProjectCommunicationData",
    "ProjectDataHistory",
]
