"""Cartões SIM por projeto (0..n): CRUD, PIN/PUK cifrados e reveal próprio.

Regras (ver docs/PLANO_LICENCIAMENTO_SIM.md):

* Leitura/lista/histórico: nunca PIN/PUK — só `has_pin`/`has_puk`.
* Escrita de SIM (campos não secretos): `project.edit_communication_data` + `can_edit_project`.
* Escrita de PIN/PUK: mesma permissão das passwords de portais
  (`project.credentials.edit` + `can_edit_project`). Sem ela → 403, nada gravado.
* Reveal: `POST .../sim-cards/{id}/reveal` com `project.credentials.reveal`;
  regista primeiro no histórico, `Cache-Control: no-store`.
* Sem chave de cifra e com PIN/PUK no corpo → 503, nada gravado.
* 422 sem eco do corpo (`NoEchoRoute`).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.no_echo_route import NoEchoRoute
from app.config import Settings, get_settings
from app.db import get_db
from app.models.project_data import ProjectSimCard
from app.schemas.project_data import SimCardCreate, SimCardRead, SimCardReveal, SimCardUpdate
from app.security.current_user import get_auth_context
from app.security.permissions import (
    AuthContext,
    can_edit_project_sim_cards,
    can_reveal_project_sim_secrets,
    can_view_project_sim_cards,
    can_write_project_sim_secrets,
)
from app.security.secret_box import SecretBoxDecryptError, SecretBoxUnavailable, decrypt_secret, encrypt_secret
from app.services.project_data import (
    create_sim_card,
    delete_sim_card,
    get_sim_card,
    list_sim_cards,
    record_sim_secrets_reveal,
    update_sim_card,
)
from app.services.projects import get_visible_project

router = APIRouter(prefix="/api/projects", tags=["project-sim-cards"], route_class=NoEchoRoute)

_NOT_FOUND = "Projeto não encontrado ou sem permissão para o ver."


def _project_or_404(db: Session, project_id: uuid.UUID, ctx: AuthContext):
    project = get_visible_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return project


def _to_read(sim: ProjectSimCard) -> SimCardRead:
    return SimCardRead(
        id=sim.id,
        project_id=sim.project_id,
        purpose=sim.purpose,
        operator=sim.operator,
        phone_number=sim.phone_number,
        iccid=sim.iccid,
        verified_on_portal=sim.verified_on_portal,
        verified_date=sim.verified_date,
        notes=sim.notes or "",
        has_pin=sim.pin_encrypted is not None,
        has_puk=sim.puk_encrypted is not None,
        updated_at=sim.updated_at,
    )


def _encrypt_or_503(settings: Settings, value: str) -> str:
    try:
        return encrypt_secret(settings, value)
    except SecretBoxUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _secret_token(settings: Settings, value: str | None) -> str | None:
    """`None`/`""` → sem valor (None); texto → token Fernet."""
    if value is None or value == "":
        return None
    return _encrypt_or_503(settings, value)


def _sim_or_404(db: Session, project_id: uuid.UUID, sim_id: uuid.UUID) -> ProjectSimCard:
    sim = get_sim_card(db, project_id, sim_id)
    if sim is None:
        raise HTTPException(status_code=404, detail="Cartão SIM não encontrado.")
    return sim


def _require_secret_write(ctx: AuthContext, project, body_fields: set[str]) -> None:
    if body_fields & {"pin", "puk"} and not can_write_project_sim_secrets(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para definir PIN/PUK.")


@router.get("/{project_id}/sim-cards", response_model=list[SimCardRead])
def list_sim_cards_endpoint(
    project_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> list[SimCardRead]:
    project = _project_or_404(db, project_id, ctx)
    if not can_view_project_sim_cards(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para ver cartões SIM.")
    return [_to_read(s) for s in list_sim_cards(db, project_id)]


@router.post("/{project_id}/sim-cards", response_model=SimCardRead, status_code=201)
def create_sim_card_endpoint(
    project_id: uuid.UUID,
    body: SimCardCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
) -> SimCardRead:
    project = _project_or_404(db, project_id, ctx)
    if not can_edit_project_sim_cards(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para editar cartões SIM.")
    sent = body.model_dump(exclude_unset=True)
    _require_secret_write(ctx, project, set(sent))
    encrypted_pin = _secret_token(settings, body.pin)
    encrypted_puk = _secret_token(settings, body.puk)
    values = {k: v for k, v in sent.items() if k not in ("pin", "puk")}
    sim = create_sim_card(
        db,
        project_id=project_id,
        values=values,
        encrypted_pin=encrypted_pin,
        encrypted_puk=encrypted_puk,
        changed_by_person_id=ctx.person_id,
    )
    return _to_read(sim)


@router.patch("/{project_id}/sim-cards/{sim_id}", response_model=SimCardRead)
def update_sim_card_endpoint(
    project_id: uuid.UUID,
    sim_id: uuid.UUID,
    body: SimCardUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
) -> SimCardRead:
    project = _project_or_404(db, project_id, ctx)
    if not can_edit_project_sim_cards(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para editar cartões SIM.")
    sim = _sim_or_404(db, project_id, sim_id)
    sent = body.model_dump(exclude_unset=True)
    _require_secret_write(ctx, project, set(sent))
    secret_changes: dict[str, str | None] = {}
    for kind in ("pin", "puk"):
        if kind in sent:
            secret_changes[kind] = _secret_token(settings, sent.pop(kind))
    sim = update_sim_card(
        db,
        sim=sim,
        changes=sent,
        secret_changes=secret_changes,
        changed_by_person_id=ctx.person_id,
    )
    return _to_read(sim)


@router.delete("/{project_id}/sim-cards/{sim_id}", status_code=204)
def delete_sim_card_endpoint(
    project_id: uuid.UUID,
    sim_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> None:
    project = _project_or_404(db, project_id, ctx)
    if not can_edit_project_sim_cards(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para editar cartões SIM.")
    sim = _sim_or_404(db, project_id, sim_id)
    delete_sim_card(db, sim=sim, deleted_by_person_id=ctx.person_id)


@router.post("/{project_id}/sim-cards/{sim_id}/reveal", response_model=SimCardReveal)
def reveal_sim_secrets_endpoint(
    project_id: uuid.UUID,
    sim_id: uuid.UUID,
    response: Response,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
) -> SimCardReveal:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    project = _project_or_404(db, project_id, ctx)
    if not can_reveal_project_sim_secrets(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para revelar PIN/PUK.")
    sim = _sim_or_404(db, project_id, sim_id)
    if sim.pin_encrypted is None and sim.puk_encrypted is None:
        raise HTTPException(status_code=409, detail="Este cartão SIM não tem PIN/PUK definidos.")
    try:
        pin = decrypt_secret(settings, sim.pin_encrypted) if sim.pin_encrypted is not None else None
        puk = decrypt_secret(settings, sim.puk_encrypted) if sim.puk_encrypted is not None else None
    except SecretBoxUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SecretBoxDecryptError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    # Regista antes de devolver: se o registo falhar, o PIN/PUK não sai.
    record_sim_secrets_reveal(db, sim=sim, revealed_by_person_id=ctx.person_id)
    return SimCardReveal(id=sim.id, pin=pin, puk=puk)
