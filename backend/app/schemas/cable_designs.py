"""Strict DTOs for the cable-dimensioning backend contract."""
from __future__ import annotations

import datetime as dt
import json
import math
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

CABLE_JSON_MAX_BYTES = 2 * 1024 * 1024


def _walk_json(value: object, *, path: str) -> None:
    """Reject values that cannot be represented safely as JSON content."""
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contém um número inválido.")
        return
    if isinstance(value, str):
        if any(ord(char) < 0x20 for char in value):
            raise ValueError(f"{path} contém caracteres de controlo.")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _walk_json(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contém uma chave inválida.")
            if any(ord(char) < 0x20 for char in key):
                raise ValueError(f"{path} contém uma chave com caracteres de controlo.")
            _walk_json(item, path=f"{path}.{key}")
        return
    raise ValueError(f"{path} contém um tipo JSON inválido.")


def _json_object(value: object, *, field_name: str, require_format: bool = False) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError(f"{field_name} tem de ser um objeto JSON.")
    _walk_json(value, path=field_name)
    if require_format and (type(value.get("format")) is not int or value.get("format") != 1):
        raise ValueError(f"{field_name} tem de conter {{\"format\": 1}}.")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} não é JSON válido.") from exc
    if len(encoded) > CABLE_JSON_MAX_BYTES:
        raise ValueError(f"{field_name} excede o limite de 2 MiB.")
    return value


def _strict_text(value: object, *, field_name: str, max_length: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} tem de ser texto.")
    if any(ord(char) < 0x20 for char in value):
        raise ValueError(f"{field_name} contém caracteres de controlo.")
    normalised = value.strip()
    if required and not normalised:
        raise ValueError(f"{field_name} não pode ficar vazio.")
    if len(normalised) > max_length:
        raise ValueError(f"{field_name} excede o limite de {max_length} caracteres.")
    return normalised


class CableDesignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: StrictStr
    input_json: dict[str, Any] | None = None
    engine_version: StrictStr

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, value: object) -> str:
        return _strict_text(value, field_name="title", max_length=256)

    @field_validator("engine_version", mode="before")
    @classmethod
    def validate_engine_version(cls, value: object) -> str:
        return _strict_text(value, field_name="engine_version", max_length=64)

    @field_validator("input_json", mode="before")
    @classmethod
    def validate_input_json(cls, value: object) -> dict[str, Any] | None:
        if value is None:
            raise ValueError("input_json não pode ser null.")
        return _json_object(value, field_name="input_json", require_format=True)


class CableDesignRevisionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: StrictInt
    title: StrictStr | None = None
    input: dict[str, Any]
    result: dict[str, Any]
    engine_version: StrictStr

    @field_validator("expected_version")
    @classmethod
    def validate_expected_version(cls, value: int) -> int:
        if value < 1:
            raise ValueError("expected_version tem de ser positivo.")
        return value

    @field_validator("title", mode="before")
    @classmethod
    def validate_optional_title(cls, value: object) -> object:
        if value is None:
            raise ValueError("title não pode ser null.")
        return _strict_text(value, field_name="title", max_length=256)

    @field_validator("engine_version", mode="before")
    @classmethod
    def validate_engine_version(cls, value: object) -> str:
        return _strict_text(value, field_name="engine_version", max_length=64)

    @field_validator("input", mode="before")
    @classmethod
    def validate_input(cls, value: object) -> dict[str, Any]:
        return _json_object(value, field_name="input", require_format=True)

    @field_validator("result", mode="before")
    @classmethod
    def validate_result(cls, value: object) -> dict[str, Any]:
        return _json_object(value, field_name="result")


class CableDesignExpectedVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: StrictInt

    @field_validator("expected_version")
    @classmethod
    def validate_expected_version(cls, value: int) -> int:
        if value < 1:
            raise ValueError("expected_version tem de ser positivo.")
        return value


class CableDesignRevisionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    design_id: UUID
    rev: str
    input_json: dict[str, Any]
    result_json: dict[str, Any]
    engine_version: str
    content_sha256: str
    unresolved_circuits: int
    status: str
    approved_by_person_id: UUID | None
    approved_at: dt.datetime | None
    created_by_person_id: UUID
    created_at: dt.datetime
    updated_at: dt.datetime


class CableDesignListRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    project_id: UUID
    title: str
    status: str
    current_revision: str
    version: int
    updated_at: dt.datetime
    unresolved_circuits: int


class CableDesignRead(CableDesignListRead):
    is_active: bool
    created_by_person_id: UUID
    created_at: dt.datetime
    revision: CableDesignRevisionRead


class CableDesignHistoryRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    design_id: UUID
    action: str
    actor_person_id: UUID
    rev: str
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None
    created_at: dt.datetime


class CableDesignRevisionListRead(CableDesignRevisionRead):
    pass
