"""Resolução do utilizador autenticado.

Dois caminhos, nunca simultâneos:

1. **`AUTH_ENABLED=true`** (Fase 1+): valida um token Bearer OIDC do
   Microsoft Entra ID (`Authorization: Bearer <token>`) via
   `app/security/entra_auth.py` — assinatura, issuer, audience, validade
   (`exp`/`iat`), e presença das claims obrigatórias. O `oid` (object ID)
   do token liga a um `User.entra_object_id`; se ainda não houver ligação,
   tenta uma ligação "just-in-time" por email (só para um `User` já
   existente, ativo, sem `entra_object_id` — nunca cria um `User` novo a
   partir do token). O cabeçalho `X-Dev-User-Email` nem é consultado neste
   caminho.
2. **`AUTH_ENABLED=false`** (mecanismo de desenvolvimento, Fase 0): usa o
   cabeçalho `X-Dev-User-Email`, que TEM de corresponder a um `User` já
   seedado — nunca cria um utilizador a partir do cabeçalho. Duas barreiras
   independentes impedem isto fora de desenvolvimento:
   - `Settings._enforce_hardening_in_non_local_envs` (app/config.py) já
     impede a aplicação de arrancar em 'staging'/'production' com
     `AUTH_ENABLED=false` — por isso, em condições normais, este caminho
     nunca é alcançável fora de 'local'/'test'.
   - Defesa em profundidade: esta função verifica também `settings.app_env`
     diretamente, a cada pedido — nunca confia só na validação de arranque.
"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models.identity import AuthAuditLog, User
from app.security.entra_auth import EntraClaims, TokenValidationError, get_token_validator
from app.security.permissions import AuthContext, load_auth_context

_DEV_HEADER_ALLOWED_ENVIRONMENTS = {"local", "test"}


def _resolve_user_from_entra_claims(db: Session, claims: EntraClaims, settings: Settings) -> User | None:
    """Liga o token validado a um `User` — nunca cria um `User` novo aqui
    (provisionamento é sempre um passo administrativo separado, fora deste
    caminho de autenticação)."""
    user = (
        db.query(User)
        .filter(User.entra_object_id == claims.object_id, User.is_active.is_(True))
        .one_or_none()
    )
    if user is not None:
        return user

    # Ligação "just-in-time" por email — configurável (D-029) e desligada
    # por omissão em staging/produção (`resolved_entra_jit_link_by_email`);
    # em local/test fica ligada por omissão para não exigir pré-preencher
    # entra_object_id manualmente em cada seed/teste.
    if not settings.resolved_entra_jit_link_by_email():
        return None
    if not claims.email:
        return None

    # Só para um User já existente, ativo, ainda sem entra_object_id, com
    # email exatamente correspondente (case insensitive). Ambíguo (mais do
    # que um) ou inexistente -> nunca adivinha, falha a autenticação.
    candidates = (
        db.query(User)
        .filter(
            User.entra_object_id.is_(None),
            User.is_active.is_(True),
            func.lower(User.email) == claims.email.strip().lower(),
        )
        .all()
    )
    if len(candidates) != 1:
        return None

    user = candidates[0]
    user.entra_object_id = claims.object_id
    db.add(
        AuthAuditLog(
            user_id=user.id,
            event="jit_link_by_email",
            detail=f"Ligação automática por email a partir do claim 'oid'={claims.object_id!r}.",
        )
    )
    db.commit()
    db.refresh(user)
    return user


def get_current_user(
    authorization: str | None = Header(default=None),
    x_dev_user_email: str | None = Header(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if settings.auth_enabled:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(
                status_code=401,
                detail="Cabeçalho 'Authorization: Bearer <token>' em falta.",
            )
        token = authorization.split(" ", 1)[1].strip()
        if not token:
            raise HTTPException(status_code=401, detail="Token vazio.")

        validator = get_token_validator(settings)
        try:
            claims = validator.validate(token)
        except TokenValidationError:
            # Nunca revelar o motivo exato (assinatura/issuer/audience/
            # validade) na resposta HTTP — só no log do servidor, se algum
            # dia for adicionado. Uma mensagem genérica evita ajudar quem
            # tenta "afinar" um token inválido por tentativa e erro.
            raise HTTPException(
                status_code=401,
                detail="Token inválido, expirado, ou não emitido para este tenant/aplicação.",
            )

        user = _resolve_user_from_entra_claims(db, claims, settings)
        if user is None:
            raise HTTPException(
                status_code=401,
                detail="Utilizador não provisionado nesta plataforma.",
            )
        return user

    # --- AUTH_ENABLED=false: mecanismo de desenvolvimento ---
    if settings.app_env not in _DEV_HEADER_ALLOWED_ENVIRONMENTS:
        # Defesa em profundidade — ver docstring do módulo. Nunca deve ser
        # alcançado em condições normais, porque Settings já bloqueia o
        # arranque nestas condições.
        raise HTTPException(
            status_code=403,
            detail="Mecanismo de utilizador de desenvolvimento (X-Dev-User-Email) "
            f"indisponível fora de 'local'/'test' (APP_ENV={settings.app_env!r}).",
        )
    if not x_dev_user_email:
        raise HTTPException(
            status_code=401,
            detail="Cabeçalho de desenvolvimento X-Dev-User-Email em falta "
            "(AUTH_ENABLED=false — sem Entra ID configurado).",
        )
    user = db.query(User).filter(User.email == x_dev_user_email, User.is_active.is_(True)).one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="Utilizador de desenvolvimento desconhecido ou inativo.")
    return user


def get_auth_context(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> AuthContext:
    return load_auth_context(db, user)
