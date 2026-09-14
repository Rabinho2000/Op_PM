"""Resolução do utilizador autenticado.

Fase 0: `AUTH_ENABLED=false` por omissão — não há integração real com o
Microsoft Entra ID ainda. Para permitir testar o backend localmente sem essa
integração, o utilizador "atual" é resolvido a partir do cabeçalho de
desenvolvimento `X-Dev-User-Email`, que TEM de corresponder a um `User` já
seedado na base de dados — nunca cria um utilizador a partir do cabeçalho.

Isto é explicitamente um mecanismo de desenvolvimento, não autenticação:
- Só funciona com `AUTH_ENABLED=false`.
- Com `AUTH_ENABLED=true`, esta função levanta `NotImplementedError` — a
  integração real com Entra ID (validação de token OIDC) é trabalho de uma
  fase seguinte, não algo que se possa contornar silenciosamente.
"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models.identity import User
from app.security.permissions import AuthContext, load_auth_context


def get_current_user(
    x_dev_user_email: str | None = Header(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if settings.auth_enabled:
        raise NotImplementedError(
            "AUTH_ENABLED=true mas a validação real de token Entra ID ainda não "
            "está implementada nesta fase."
        )
    if not x_dev_user_email:
        raise HTTPException(
            status_code=401,
            detail="Cabeçalho de desenvolvimento X-Dev-User-Email em falta "
            "(AUTH_ENABLED=false — sem Entra ID configurado nesta fase).",
        )
    user = db.query(User).filter(User.email == x_dev_user_email, User.is_active.is_(True)).one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="Utilizador de desenvolvimento desconhecido ou inativo.")
    return user


def get_auth_context(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> AuthContext:
    return load_auth_context(db, user)
