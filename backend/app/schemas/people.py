from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class PersonRead(BaseModel):
    """Usado por `GET /api/people` — disponível a qualquer utilizador
    autenticado (ver app/api/routes_people.py). Deliberadamente sem
    `birth_date`: essa informação só é exposta através do dashboard
    (`BirthdayMini`, ver app/schemas/dashboard.py), que respeita
    `absence.view_all`/`absence.view_own` — este endpoint não deve
    vazá-la a qualquer utilizador só porque precisa de listar pessoas
    para um filtro."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    email: str | None
    is_active: bool
