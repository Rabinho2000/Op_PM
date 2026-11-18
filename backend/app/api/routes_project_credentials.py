"""Credenciais de portais por projeto (DGEG/Login Geral, Mastervantagem, outro).

Regras de segurança (ver docs/PLANO_LICENCIAMENTO_SIM.md):

* A password é cifrada (Fernet) antes de tocar na BD; sem chave configurada a
  escrita/revelação falha fechado com 503 — nunca grava em claro.
* Nenhuma resposta de lista/detalhe/edição traz a password: só `has_password`.
* Só `POST .../reveal` devolve a password, com permissão própria, e regista no
  histórico quem revelou e quando (sem o valor).
* Erros de validação destas rotas respondem 422 `{"detail": "Corpo inválido."}`
  sem eco do corpo (`NoEchoRoute`), para que uma password mal formada nunca
  apareça numa mensagem de erro.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.no_echo_route import NoEchoRoute
from app.config import Settings, get_settings
from app.db import get_db
from app.models.project_data import ProjectPortalCredential
from app.schemas.project_data import (
    PortalCredentialCreate,
    PortalCredentialRead,
    PortalCredentialReveal,
    PortalCredentialUpdate,
)
from app.security.current_user import get_auth_context
from app.security.permissions import (
    AuthContext,
    can_edit_project_credentials,
    can_reveal_project_credential,
    can_view_project_credentials,
)
from app.security.secret_box import SecretBoxDecryptError, SecretBoxUnavailable, decrypt_secret, encrypt_secret
from app.services.project_data import (
    create_portal_credential,
    delete_portal_credential,
    get_portal_credential,
    list_portal_credentials,
    record_password_reveal,
    update_portal_credential,
)
from app.services.projects import get_visible_project


router = APIRouter(prefix="/api/projects", tags=["project-credentials"], route_class=NoEchoRoute)

_NOT_FOUND = "Projeto não encontrado ou sem permissão para o ver."


def _project_or_404(db: Session, project_id: uuid.UUID, ctx: AuthContext):
    project = get_visible_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return project


def _to_read(credential: ProjectPortalCredential) -> PortalCredentialRead:
    return PortalCredentialRead(
        id=credential.id,
        project_id=credential.project_id,
        portal=credential.portal,
        username=credential.username,
        email=credential.email,
        has_password=credential.password_encrypted is not None,
        updated_at=credential.updated_at,
    )


def _encrypt_or_503(settings: Settings, password: str) -> str:
    try:
        return encrypt_secret(settings, password)
    except SecretBoxUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _credential_or_404(db: Session, project_id: uuid.UUID, credential_id: uuid.UUID) -> ProjectPortalCredential:
    credential = get_portal_credential(db, project_id, credential_id)
    if credential is None:
        raise HTTPException(status_code=404, detail="Credencial não encontrada.")
    return credential


@router.get("/{project_id}/credentials", response_model=list[PortalCredentialRead])
def list_credentials_endpoint(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[PortalCredentialRead]:
    project = _project_or_404(db, project_id, ctx)
    if not can_view_project_credentials(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para ver credenciais de portais.")
    return [_to_read(c) for c in list_portal_credentials(db, project_id)]


@router.post("/{project_id}/credentials", response_model=PortalCredentialRead, status_code=201)
def create_credential_endpoint(
    project_id: uuid.UUID,
    body: PortalCredentialCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
) -> PortalCredentialRead:
    project = _project_or_404(db, project_id, ctx)
    if not can_edit_project_credentials(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para editar credenciais de portais.")
    encrypted = _encrypt_or_503(settings, body.password) if body.password else None
    credential = create_portal_credential(
        db,
        project_id=project_id,
        values={"portal": body.portal, "username": body.username, "email": body.email},
        encrypted_password=encrypted,
        changed_by_person_id=ctx.person_id,
    )
    return _to_read(credential)


@router.patch("/{project_id}/credentials/{credential_id}", response_model=PortalCredentialRead)
def update_credential_endpoint(
    project_id: uuid.UUID,
    credential_id: uuid.UUID,
    body: PortalCredentialUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
) -> PortalCredentialRead:
    project = _project_or_404(db, project_id, ctx)
    if not can_edit_project_credentials(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para editar credenciais de portais.")
    credential = _credential_or_404(db, project_id, credential_id)
    changes = body.model_dump(exclude_unset=True)
    password_given = "password" in changes
    raw_password = changes.pop("password", None)
    encrypted: str | None = None
    if password_given and raw_password:
        encrypted = _encrypt_or_503(settings, raw_password)
    if "portal" in changes and changes["portal"] is None:
        changes.pop("portal")
    if "username" in changes and changes["username"] is None:
        changes.pop("username")
    credential = update_portal_credential(
        db,
        credential=credential,
        changes=changes,
        password_given=password_given,
        encrypted_password=encrypted,
        changed_by_person_id=ctx.person_id,
    )
    return _to_read(credential)


@router.delete("/{project_id}/credentials/{credential_id}", status_code=204)
def delete_credential_endpoint(
    project_id: uuid.UUID,
    credential_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> None:
    project = _project_or_404(db, project_id, ctx)
    if not can_edit_project_credentials(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para editar credenciais de portais.")
    credential = _credential_or_404(db, project_id, credential_id)
    delete_portal_credential(db, credential=credential, deleted_by_person_id=ctx.person_id)


@router.post("/{project_id}/credentials/{credential_id}/reveal", response_model=PortalCredentialReveal)
def reveal_credential_endpoint(
    project_id: uuid.UUID,
    credential_id: uuid.UUID,
    response: Response,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
) -> PortalCredentialReveal:
    # A password revelada nunca deve ficar em caches intermédias nem do browser.
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    project = _project_or_404(db, project_id, ctx)
    if not can_reveal_project_credential(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para revelar credenciais de portais.")
    credential = _credential_or_404(db, project_id, credential_id)
    if credential.password_encrypted is None:
        raise HTTPException(status_code=409, detail="Esta credencial não tem password definida.")
    try:
        password = decrypt_secret(settings, credential.password_encrypted)
    except SecretBoxUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SecretBoxDecryptError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    # Regista antes de devolver: se o registo falhar, a password não sai.
    record_password_reveal(db, credential=credential, revealed_by_person_id=ctx.person_id)
    return PortalCredentialReveal(
        id=credential.id,
        portal=credential.portal,
        username=credential.username,
        password=password,
    )
