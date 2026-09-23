from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict


class MapProjectRead(BaseModel):
    id: uuid.UUID
    name: str
    client_name: str | None
    pm_display_name: str | None
    status: str
    lat: float | None
    lon: float | None
    power_kwp: float | None
    open_tasks_count: int
    issues_count: int


class MapSupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: str | None
    contact: str | None
    email: str | None
    address: str | None
    lat: float | None
    lon: float | None
    is_preferred: bool
    lead_time_days: int | None
    materials: str
    is_active: bool


class SupplierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    category: str | None = None
    contact: str | None = None
    email: str | None = None
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    is_preferred: bool = False
    lead_time_days: int | None = None
    materials: str = ""


class SupplierUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    category: str | None = None
    contact: str | None = None
    email: str | None = None
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    is_preferred: bool | None = None
    lead_time_days: int | None = None
    materials: str | None = None
    is_active: bool | None = None


class MapPickupPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    supplier_id: uuid.UUID | None
    address: str | None
    lat: float | None
    lon: float | None
    schedule: str | None
    contact: str | None
    materials: str
    notes: str
    is_active: bool


class PickupPointCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    supplier_id: uuid.UUID | None = None
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    schedule: str | None = None
    contact: str | None = None
    materials: str = ""
    notes: str = ""


class PickupPointUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    supplier_id: uuid.UUID | None = None
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    schedule: str | None = None
    contact: str | None = None
    materials: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class ProjectIssueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    description: str
    category: str
    priority: str
    status: str
    assigned_to_person_id: uuid.UUID | None
    due_date: dt.date | None
    lat: float | None
    lon: float | None
    related_task_id: uuid.UUID | None
    notes: str
    visible_on_map: bool
    created_by_person_id: uuid.UUID | None
    created_at: dt.datetime

    project_name: str | None = None


class ProjectIssueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    category: str = "outro"
    priority: str = "medium"
    assigned_to_person_id: uuid.UUID | None = None
    due_date: dt.date | None = None
    lat: float | None = None
    lon: float | None = None
    notes: str = ""
    visible_on_map: bool = True


class ProjectIssueUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    category: str | None = None
    priority: str | None = None
    status: str | None = None
    assigned_to_person_id: uuid.UUID | None = None
    due_date: dt.date | None = None
    lat: float | None = None
    lon: float | None = None
    notes: str | None = None
    visible_on_map: bool | None = None


class ConvertIssueToTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str


class MapConfig(BaseModel):
    provider_enabled: bool
    tile_url: str
    tile_attribution: str


class MapDataResponse(BaseModel):
    config: MapConfig
    projects: list[MapProjectRead]
    projects_without_coordinates: list[MapProjectRead]
    suppliers: list[MapSupplierRead]
    pickup_points: list[MapPickupPointRead]
    issues: list[ProjectIssueRead]
