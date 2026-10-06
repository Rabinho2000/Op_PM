from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class PersonRead(BaseModel):
    """Usado por `GET /api/people`. Perfis globais recebem email; perfis
    limitados recebem `email=None` e apenas pessoas do seu âmbito efetivo.
    Deliberadamente sem `birth_date`: essa informação só é exposta através
    do dashboard (`BirthdayMini`, ver app/schemas/dashboard.py), que respeita
    `absence.view_all`/`absence.view_own`.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    email: str | None
    is_active: bool
