"""Dados satélite do projeto — um registo 1:1 por projeto em cada tabela,
separados de `Project` para não o transformar numa tabela com centenas de
campos opcionais (ver docs/PLAN_OPERATIONS_MVP.md secção 2.1).

`Project.client_name`/`client_contact`/`client_email` continuam a fonte de
verdade para identidade do cliente — `ProjectInstallationData` não duplica
esses três campos, só acrescenta o que falta.

`ProjectCommunicationData` não guarda PIN/PUK/password/token. O login
whereverSIM é um identificador de utilizador (texto), não um segredo. As
passwords de portais vivem em `ProjectPortalCredential`, com a password
cifrada (Fernet, chave em ficheiro — ver app/security/secret_box.py), nunca
em claro e nunca em respostas de lista/detalhe ou histórico.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk


def _history_now() -> dt.datetime:
    """Hora do evento escrita em Python (não `now()` do PostgreSQL, que é a
    hora de início da transação): a deteção de alterações posteriores no
    rollback de importações compara-a com marcas escritas em Python."""
    return dt.datetime.now(dt.timezone.utc)


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
    power_kwp: Mapped[float | None] = mapped_column(Float, nullable=True)
    panel_count: Mapped[int | None] = mapped_column(nullable=True)
    panel_power_wp: Mapped[float | None] = mapped_column(Float, nullable=True)
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
    upac_registration_date: Mapped[dt.date | None] = mapped_column(nullable=True)
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
    annual_production_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    provisional_certificate_date: Mapped[dt.date | None] = mapped_column(nullable=True)
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
    # Os campos de cartão SIM (operador, nº, ICCID, verificação, PIN/PUK) vivem em
    # `ProjectSimCard` (lista 0..n por projeto, migração c3e5a7b9d1f2).
    communication_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    whereversim_login: Mapped[str | None] = mapped_column(String(256), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class ProjectSimCard(UUIDPk, TimestampMixin, Base):
    """Cartão SIM de um projeto (0..n). PIN e PUK são tokens Fernet
    (`pin_encrypted`/`puk_encrypted`) — nunca em claro, nunca em respostas de
    leitura nem no histórico; só `POST .../reveal` os devolve, com permissão
    própria. Remoção lógica (`deleted_at`) apaga os segredos no mesmo passo."""

    __tablename__ = "project_sim_cards"

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=False, index=True)
    # comunicacoes | dados_moveis | outro
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    operator: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(64), nullable=True)  # nº telefone / M2M
    iccid: Mapped[str | None] = mapped_column(String(128), nullable=True)  # nº do cartão
    verified_on_portal: Mapped[bool | None] = mapped_column(nullable=True)
    verified_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    pin_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    puk_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )


class ProjectPortalCredential(UUIDPk, TimestampMixin, Base):
    """Credencial de portal de um projeto (0..n). `password_encrypted` é um
    token Fernet — nunca a password em claro. Remoção lógica (`deleted_at`)
    e a password é apagada nesse momento."""

    __tablename__ = "project_portal_credentials"

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=False, index=True)
    # dgeg_login_geral | mastervantagem | outro
    portal: Mapped[str] = mapped_column(String(32), nullable=False)
    username: Mapped[str] = mapped_column(String(256), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)  # email do portal (não é segredo)
    password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )


class ProjectSurplusContract(UUIDPk, TimestampMixin, Base):
    """Contrato de venda de excedente de um projeto (0..n). Remoção lógica."""

    __tablename__ = "project_surplus_contracts"

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=False, index=True)
    commercializer: Mapped[str | None] = mapped_column(String(256), nullable=True)
    contract_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contract_sent_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    signed_received_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    sent_to_commercializer_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    end_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by_person_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("people.id"), nullable=True
    )


class ProjectDataHistory(UUIDPk, Base):
    """Auditoria append-only para os três modelos acima — mesmo padrão de
    `ProjectHistory`/`TaskHistory`, mas com `entity_type` a distinguir qual
    das três tabelas foi alterada (evita três tabelas de histórico quase
    idênticas)."""

    __tablename__ = "project_data_history"

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=False)
    # installation | licensing | communication | credential | surplus
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Id do registo afetado quando a entidade tem várias linhas (credencial,
    # contrato de excedente). Nulo para os registos 1:1 do projeto.
    record_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
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
        DateTime(timezone=True), default=_history_now, server_default=func.now(), nullable=False
    )


__all__ = [
    "ProjectInstallationData",
    "ProjectLicensingData",
    "ProjectCommunicationData",
    "ProjectPortalCredential",
    "ProjectSurplusContract",
    "ProjectDataHistory",
]
