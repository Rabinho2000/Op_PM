from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict


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
    dgeg_number: str | None = None
    cadastro_number: str | None = None
    licensing_status: str | None = None
    registration_date: dt.date | None = None
    certification_request_date: dt.date | None = None
    inspecting_entity: str | None = None
    inspection_date: dt.date | None = None
    certificate_date: dt.date | None = None
    installer: str | None = None
    commercializer: str | None = None
    annual_production_kwh: float | None = None
    comments: str = ""
    updated_at: dt.datetime | None = None


class ProjectLicensingDataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upac_number: str | None = None
    dgeg_number: str | None = None
    cadastro_number: str | None = None
    licensing_status: str | None = None
    registration_date: dt.date | None = None
    certification_request_date: dt.date | None = None
    inspecting_entity: str | None = None
    inspection_date: dt.date | None = None
    certificate_date: dt.date | None = None
    installer: str | None = None
    commercializer: str | None = None
    annual_production_kwh: float | None = None
    comments: str | None = None


class ProjectCommunicationDataRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: uuid.UUID
    operator: str | None = None
    gsm_m2m_number: str | None = None
    card_identifier: str | None = None
    communication_status: str | None = None
    notes: str = ""
    updated_at: dt.datetime | None = None


class ProjectCommunicationDataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator: str | None = None
    gsm_m2m_number: str | None = None
    card_identifier: str | None = None
    communication_status: str | None = None
    notes: str | None = None


class ProjectDataHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    entity_type: str
    field_name: str
    old_value: str | None
    new_value: str | None
    changed_by_person_id: uuid.UUID | None
    changed_by_person_name: str | None = None
    source: str
    note: str
    changed_at: dt.datetime
