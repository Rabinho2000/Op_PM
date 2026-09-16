from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict


class AbsenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    person_id: uuid.UUID
    start_date: dt.date
    end_date: dt.date
    type: str
    note: str
    status: str
    created_by_person_id: uuid.UUID | None
    created_at: dt.datetime
    updated_at: dt.datetime

    person_display_name: str | None = None
    # Permissão efetiva do utilizador atual (D-051) — só para a UI.
    can_cancel: bool = False


class AbsenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: uuid.UUID
    start_date: dt.date
    end_date: dt.date
    type: str = "ferias"
    note: str = ""


class AbsenceUpdate(BaseModel):
    """Só `status` (ex. cancelar) e `note` são editáveis depois de criada —
    alterar datas/pessoa/tipo de uma ausência já registada exige cancelar e
    criar de novo, para manter o registo simples e sem ambiguidade sobre
    "o que mudou realmente"."""

    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    note: str | None = None
