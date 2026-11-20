from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models.project import Project, ProjectHistory
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, can_edit_project
from app.services.file_storage import detect_image_type, safe_stored_file_path, write_private_file
from app.api.deps import get_visible_project_or_404

router = APIRouter(prefix="/api/projects", tags=["project-photos"])
MAX_PROJECT_PHOTO_BYTES = 10 * 1024 * 1024
_ALLOWED_MIME_TYPES = {
    "jpeg": ("image/jpeg", ".jpg"),
    "png": ("image/png", ".png"),
    "webp": ("image/webp", ".webp"),
}
_STORED_NAME = re.compile(r"^[0-9a-f]{32}\.(?:jpg|png|webp)$")


def _detect_image_type(content: bytes) -> tuple[str, str] | None:
    return detect_image_type(content)


def _get_project_for_edit_or_404(db: Session, project_id: uuid.UUID) -> Project:
    # Só para escrever (POST/DELETE): 404 "simples" para um projeto inexistente ou
    # apagado e 403 (em `_require_photo_edit`) a quem não o pode editar — regra
    # diferente da do resto da API (`get_visible_project_or_404`: 404 sempre que o
    # projeto não é visível). Ver docs/ANALISE_OP_PM.md, secção 5, item 1.
    project = db.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    return project


def _require_photo_edit(ctx: AuthContext, project: Project) -> None:
    if not can_edit_project(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para alterar a fotografia deste projeto.")


def _stored_photo_path(settings: Settings, storage_name: str | None) -> Path | None:
    return safe_stored_file_path(settings.project_photo_dir, storage_name, _STORED_NAME)


def _write_history(
    db: Session,
    *,
    project: Project,
    ctx: AuthContext,
    old_value: str | None,
    new_value: str | None,
    note: str,
) -> None:
    db.add(
        ProjectHistory(
            project_id=project.id,
            field_name="photo_primary",
            old_value=old_value,
            new_value=new_value,
            changed_by_person_id=ctx.person_id,
            source="ui",
            note=note,
        )
    )


@router.post("/{project_id}/photo")
async def upload_project_photo(
    project_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
) -> dict[str, str | bool]:
    project = _get_project_for_edit_or_404(db, project_id)
    _require_photo_edit(ctx, project)

    content = await file.read(MAX_PROJECT_PHOTO_BYTES + 1)
    if len(content) > MAX_PROJECT_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="A fotografia excede o limite de 10 MB.")
    detected = _detect_image_type(content)
    if detected is None:
        raise HTTPException(status_code=400, detail="Formato inválido. Utilize JPEG, PNG ou WebP.")
    content_type, extension = detected

    settings.project_photo_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    new_name = f"{uuid.uuid4().hex}{extension}"
    try:
        new_path = write_private_file(settings.project_photo_dir, new_name, content)
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Não foi possível guardar a fotografia.") from exc

    old_name = project.primary_photo_storage_name
    project.primary_photo_storage_name = new_name
    project.primary_photo_content_type = content_type
    _write_history(
        db,
        project=project,
        ctx=ctx,
        old_value="fotografia principal existente" if old_name else None,
        new_value="fotografia principal atualizada",
        note="Fotografia principal carregada/substituída.",
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        new_path.unlink(missing_ok=True)
        raise

    old_path = _stored_photo_path(settings, old_name)
    if old_path is not None:
        old_path.unlink(missing_ok=True)
    return {"has_project_photo": True, "content_type": content_type}


@router.get("/{project_id}/photo")
def get_project_photo(
    project: Project = Depends(get_visible_project_or_404),
    settings: Settings = Depends(get_settings),
) -> Response:
    path = _stored_photo_path(settings, project.primary_photo_storage_name)
    content_type = project.primary_photo_content_type
    if path is None or content_type not in {value[0] for value in _ALLOWED_MIME_TYPES.values()} or not path.is_file():
        raise HTTPException(status_code=404, detail="Fotografia do projeto não encontrada.")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=404, detail="Fotografia do projeto não encontrada.") from exc
    return Response(
        content=content,
        media_type=content_type,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private"},
    )


@router.delete("/{project_id}/photo", status_code=204)
def delete_project_photo(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
) -> Response:
    project = _get_project_for_edit_or_404(db, project_id)
    _require_photo_edit(ctx, project)
    old_name = project.primary_photo_storage_name
    if old_name is None:
        raise HTTPException(status_code=404, detail="Fotografia do projeto não encontrada.")
    project.primary_photo_storage_name = None
    project.primary_photo_content_type = None
    _write_history(
        db,
        project=project,
        ctx=ctx,
        old_value="fotografia principal existente",
        new_value=None,
        note="Fotografia principal removida.",
    )
    db.commit()
    old_path = _stored_photo_path(settings, old_name)
    if old_path is not None:
        old_path.unlink(missing_ok=True)
    return Response(status_code=204)
