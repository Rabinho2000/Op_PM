from __future__ import annotations

import datetime as dt
import uuid

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectInstallationDataRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: uuid.UUID
    client_nif: str | None = None
    contact_person_name: str | None = None
    contact_person_role: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    address: str | None = None
    district: str | None = None
    municipality: str | None = None
    power_kwp: float | None = None
    panel_count: int | None = None
    panel_power_wp: float | None = None
    inverters: str | None = None
    batteries: str | None = None
    has_backup: bool | None = None
    ev_chargers: str | None = None
    installation_type: str | None = None
    injection_type: str | None = None
    om_notes: str | None = None
    notes: str = ""
    updated_at: dt.datetime | None = None


class ProjectInstallationDataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_nif: str | None = None
    contact_person_name: str | None = None
    contact_person_role: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    address: str | None = None
    district: str | None = None
    municipality: str | None = None
    power_kwp: float | None = None
    panel_count: int | None = None
    panel_power_wp: float | None = None
    inverters: str | None = None
    batteries: str | None = None
    has_backup: bool | None = None
    ev_chargers: str | None = None
    installation_type: str | None = None
    injection_type: str | None = None
    om_notes: str | None = None
    notes: str | None = None


class ProjectLicensingDataRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: uuid.UUID
    upac_number: str | None = None
    upac_registration_date: dt.date | None = None
    dgeg_number: str | None = None
    cadastro_number: str | None = None
    licensing_status: str | None = None
    registration_date: dt.date | None = None
    certification_request_date: dt.date | None = None
    inspecting_entity: str | None = None
    inspection_date: dt.date | None = None
    provisional_certificate_date: dt.date | None = None
    certificate_date: dt.date | None = None
    installer: str | None = None
    commercializer: str | None = None
    annual_production_kwh: float | None = None
    comments: str = ""
    # Derivado (não guardado): maior etapa com data preenchida.
    licensing_state: str = "sem_registo"
    updated_at: dt.datetime | None = None


class ProjectLicensingDataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upac_number: str | None = None
    upac_registration_date: dt.date | None = None
    dgeg_number: str | None = None
    cadastro_number: str | None = None
    licensing_status: str | None = None
    registration_date: dt.date | None = None
    certification_request_date: dt.date | None = None
    inspecting_entity: str | None = None
    inspection_date: dt.date | None = None
    provisional_certificate_date: dt.date | None = None
    certificate_date: dt.date | None = None
    installer: str | None = None
    commercializer: str | None = None
    annual_production_kwh: float | None = None
    comments: str | None = None


class ProjectCommunicationDataRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: uuid.UUID
    communication_status: str | None = None
    whereversim_login: str | None = None
    notes: str = ""
    updated_at: dt.datetime | None = None


class ProjectCommunicationDataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    communication_status: str | None = None
    whereversim_login: str | None = None
    notes: str | None = None


# --- Cartões SIM (0..n por projeto) -----------------------------------------
# A leitura NUNCA traz PIN/PUK: só `has_pin`/`has_puk`. Ver docs/PLANO_LICENCIAMENTO_SIM.md.

SimPurpose = Literal["comunicacoes", "dados_moveis", "outro"]


class SimCardRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    purpose: str
    operator: str | None = None
    phone_number: str | None = None
    iccid: str | None = None
    verified_on_portal: bool | None = None
    verified_date: dt.date | None = None
    notes: str = ""
    has_pin: bool = False
    has_puk: bool = False
    updated_at: dt.datetime | None = None


class SimCardCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: SimPurpose
    operator: str | None = Field(default=None, max_length=128)
    phone_number: str | None = Field(default=None, max_length=64)
    iccid: str | None = Field(default=None, max_length=128)
    verified_on_portal: bool | None = None
    verified_date: dt.date | None = None
    notes: str | None = None
    # Ausente = sem PIN/PUK. String vazia ou null = sem valor (com o campo explícito, remove).
    pin: str | None = Field(default=None, max_length=32)
    puk: str | None = Field(default=None, max_length=32)


class SimCardUpdate(SimCardCreate):
    """PATCH: campos omitidos mantêm-se. `pin`/`puk` omitidos = mantêm; `null`/`""` = removem."""

    purpose: SimPurpose | None = None  # type: ignore[assignment]


class SimCardReveal(BaseModel):
    id: uuid.UUID
    pin: str | None = None
    puk: str | None = None


# --- Credenciais de portais --------------------------------------------------
# A leitura NUNCA tem campo de password: só `has_password`. Ver docs/PLANO_LICENCIAMENTO_SIM.md.

PortalCode = Literal["dgeg_login_geral", "mastervantagem", "outro"]


class PortalCredentialRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    portal: str
    username: str
    email: str | None = None
    has_password: bool
    updated_at: dt.datetime | None = None


class PortalCredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portal: PortalCode
    username: str = Field(min_length=1, max_length=256)
    email: str | None = Field(default=None, max_length=320)
    password: str | None = Field(default=None, max_length=512)


class PortalCredentialUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portal: PortalCode | None = None
    username: str | None = Field(default=None, min_length=1, max_length=256)
    email: str | None = Field(default=None, max_length=320)
    # Ausente = manter. String vazia ou null = remover a password (com `password` explícito).
    password: str | None = Field(default=None, max_length=512)


class PortalCredentialReveal(BaseModel):
    id: uuid.UUID
    portal: str
    username: str
    password: str


# --- Contratos de venda de excedente ----------------------------------------


class SurplusContractRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    commercializer: str | None = None
    contract_type: str | None = None
    contract_sent_date: dt.date | None = None
    signed_received_date: dt.date | None = None
    sent_to_commercializer_date: dt.date | None = None
    status: str | None = None
    duration_months: int | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    notes: str = ""
    updated_at: dt.datetime | None = None


class SurplusContractCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commercializer: str | None = Field(default=None, max_length=256)
    contract_type: str | None = Field(default=None, max_length=128)
    contract_sent_date: dt.date | None = None
    signed_received_date: dt.date | None = None
    sent_to_commercializer_date: dt.date | None = None
    status: str | None = Field(default=None, max_length=64)
    duration_months: int | None = Field(default=None, ge=0, le=600)
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    notes: str | None = None


class SurplusContractUpdate(SurplusContractCreate):
    pass




class ProjectDataHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    entity_type: str
    record_id: uuid.UUID | None = None
    field_name: str
    old_value: str | None
    new_value: str | None
    changed_by_person_id: uuid.UUID | None
    changed_by_person_name: str | None = None
    source: str
    note: str
    changed_at: dt.datetime
