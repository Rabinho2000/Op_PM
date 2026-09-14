"""Listagem simples de pessoas — usada pelo frontend para o filtro de PM.
Leitura pura, sem escrita nenhuma; disponível a qualquer utilizador
autenticado (não expõe nada sensível além do nome/email já visível em
qualquer projeto atribuído a essa pessoa)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.people import Person
from app.schemas.people import PersonRead
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext

router = APIRouter(prefix="/api/people", tags=["people"])


@router.get("", response_model=list[PersonRead])
def list_people(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> list[PersonRead]:
    people = db.query(Person).order_by(Person.display_name.asc()).all()
    return [PersonRead.model_validate(p) for p in people]
