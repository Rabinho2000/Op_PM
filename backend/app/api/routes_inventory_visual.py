from __future__ import annotations

import datetime as dt
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models.inventory import (
    INVENTORY_CATEGORIES,
    InventoryCategoryImage,
    InventoryItem,
    InventoryItemDocument,
)
from app.schemas.inventory import (
    InventoryCategoryImageRead,
    InventoryCategorySummaryRead,
    InventoryCategoryUnitStockRead,
    InventoryItemDocumentRead,
)
from app.schemas.inventory_catalog import normalize_inventory_category
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, PermissionDenied
from app.services.file_storage import detect_image_type, safe_stored_file_path, write_private_file
from app.services.inventory import item_balance

router = APIRouter(prefix="/api/inventory", tags=["inventory-visual"])
MAX_ITEM_PHOTO_BYTES = 10 * 1024 * 1024
MAX_ITEM_DOCUMENT_BYTES = 25 * 1024 * 1024
_STORED_MEDIA_NAME = re.compile(r"^[0-9a-f]{32}\.(?:jpg|png|webp|pdf)$")
_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_DOCUMENT_CONTENT_TYPES = _IMAGE_CONTENT_TYPES | {"application/pdf"}


@dataclass
class _InventoryCategoryTotals:
    item_count: int = 0
    stock_by_unit: dict[str, Decimal] = field(default_factory=dict)
    low_stock_count: int = 0


def _require(ctx: AuthContext, permission: str) -> None:
    try:
        ctx.require(permission)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=f"Sem permissão: {exc}") from exc


def _require_view(ctx: AuthContext) -> None:
    _require(ctx, "inventory.view")


def _require_catalog(ctx: AuthContext) -> None:
    _require(ctx, "inventory.manage_catalog")


def _get_item_or_404(db: Session, item_id: uuid.UUID) -> InventoryItem:
    item = db.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Artigo de inventário não encontrado.")
    return item


def _media_path(settings: Settings, folder: str, stored_name: str | None) -> Path | None:
    return safe_stored_file_path(settings.inventory_file_dir / folder, stored_name, _STORED_MEDIA_NAME)


def _read_media(path: Path | None, content_type: str | None, allowed: set[str], label: str) -> bytes:
    if path is None or content_type not in allowed or not path.is_file():
        raise HTTPException(status_code=404, detail=f"{label} não encontrado.")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=404, detail=f"{label} não encontrado.") from exc


def _upload_image(content: bytes, *, limit: int, label: str) -> tuple[str, str]:
    if len(content) > limit:
        raise HTTPException(status_code=413, detail=f"{label} excede o limite de {limit // (1024 * 1024)} MB.")
    detected = detect_image_type(content)
    if detected is None:
        raise HTTPException(status_code=400, detail="Formato inválido. Utilize JPEG, PNG ou WebP.")
    return detected


def _stored_name(extension: str) -> str:
    return f"{uuid.uuid4().hex}{extension}"


def _write_media(settings: Settings, folder: str, stored_name: str, content: bytes) -> Path:
    try:
        return write_private_file(settings.inventory_file_dir / folder, stored_name, content)
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Não foi possível guardar o ficheiro.") from exc


def _unlink_media(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        # Storage cleanup is best-effort; it must not undo a durable DB commit
        # or hide the original failure that caused a new upload to be discarded.
        pass


def _remove_media(settings: Settings, folder: str, stored_name: str | None) -> None:
    _unlink_media(_media_path(settings, folder, stored_name))


def _canonical_category(value: str) -> str:
    try:
        category = normalize_inventory_category(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if category is None:
        raise HTTPException(status_code=422, detail="Categoria inválida.")
    return category


def _category_details(db: Session) -> list[InventoryCategoryImageRead]:
    rows = {
        image.category: image
        for image in db.query(InventoryCategoryImage).filter(
            InventoryCategoryImage.category.in_(INVENTORY_CATEGORIES)
        ).all()
    }
    return [
        InventoryCategoryImageRead(
            name=category,
            has_custom_image=category in rows,
            image_version=rows[category].updated_at.isoformat() if category in rows else None,
        )
        for category in INVENTORY_CATEGORIES
    ]


@router.get("/categories/details", response_model=list[InventoryCategoryImageRead])
def inventory_category_details(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> list[InventoryCategoryImageRead]:
    _require_view(ctx)
    return _category_details(db)


@router.post("/categories/{category:path}/image")
async def upload_inventory_category_image(
    category: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
) -> dict[str, str | bool]:
    _require_catalog(ctx)
    canonical = _canonical_category(category)
    content = await file.read(MAX_ITEM_PHOTO_BYTES + 1)
    content_type, extension = _upload_image(content, limit=MAX_ITEM_PHOTO_BYTES, label="A imagem")
    new_name = _stored_name(extension)
    new_path = _write_media(settings, "category_images", new_name, content)
    old_name: str | None = None
    updated_at = dt.datetime.now(dt.timezone.utc)
    try:
        image = db.get(InventoryCategoryImage, canonical)
        old_name = image.stored_name if image is not None else None
        if image is None:
            image = InventoryCategoryImage(
                category=canonical,
                stored_name=new_name,
                content_type=content_type,
                updated_by_person_id=ctx.person_id,
                updated_at=updated_at,
            )
            db.add(image)
        else:
            image.stored_name = new_name
            image.content_type = content_type
            image.updated_by_person_id = ctx.person_id
            image.updated_at = updated_at
        db.flush()
        result = {
            "name": canonical,
            "has_custom_image": True,
            "image_version": updated_at.isoformat(),
            "content_type": content_type,
        }
        db.commit()
    except Exception:
        db.rollback()
        _unlink_media(new_path)
        raise
    _remove_media(settings, "category_images", old_name)
    return result


@router.get("/categories/{category:path}/image")
def get_inventory_category_image(
    category: str,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
) -> Response:
    _require_view(ctx)
    canonical = _canonical_category(category)
    image = db.get(InventoryCategoryImage, canonical)
    if image is None:
        raise HTTPException(status_code=404, detail="Imagem personalizada da categoria não encontrada.")
    content = _read_media(
        _media_path(settings, "category_images", image.stored_name), image.content_type,
        _IMAGE_CONTENT_TYPES, "Imagem da categoria",
    )
    return Response(
        content=content,
        media_type=image.content_type,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private"},
    )


@router.delete("/categories/{category:path}/image", status_code=204)
def delete_inventory_category_image(
    category: str,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
) -> Response:
    _require_catalog(ctx)
    canonical = _canonical_category(category)
    image = db.get(InventoryCategoryImage, canonical)
    if image is None:
        raise HTTPException(status_code=404, detail="Imagem personalizada da categoria não encontrada.")
    old_name = image.stored_name
    db.delete(image)
    db.commit()
    _remove_media(settings, "category_images", old_name)
    return Response(status_code=204)


@router.get("/categories/summary", response_model=list[InventoryCategorySummaryRead])
def inventory_category_summary(
    owner: Literal["solcor", "verde_milenar"] = Query(default="solcor"),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[InventoryCategorySummaryRead]:
    _require_view(ctx)
    totals = {category: _InventoryCategoryTotals() for category in INVENTORY_CATEGORIES}
    items = db.query(InventoryItem).filter(InventoryItem.is_active.is_(True)).all()
    for item in items:
        try:
            category = normalize_inventory_category(item.category)
        except ValueError:
            continue
        if category is None:
            continue
        balance = item_balance(db, item, owner)
        aggregate = totals[category]
        aggregate.item_count += 1
        aggregate.stock_by_unit[item.unit] = (
            aggregate.stock_by_unit.get(item.unit, Decimal("0.000")) + balance.physical_stock
        )
        if balance.physical_stock < item.min_stock:
            aggregate.low_stock_count += 1
    return [
        InventoryCategorySummaryRead(
            category=category,
            owner=owner,
            item_count=totals[category].item_count,
            stock_by_unit=[
                InventoryCategoryUnitStockRead(unit=unit, total_stock=total)
                for unit, total in sorted(totals[category].stock_by_unit.items())
            ],
            low_stock_count=totals[category].low_stock_count,
        )
        for category in INVENTORY_CATEGORIES
    ]


@router.post("/items/{item_id}/photo")
async def upload_inventory_item_photo(
    item_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
) -> dict[str, str | bool]:
    _require_catalog(ctx)
    item = _get_item_or_404(db, item_id)
    content = await file.read(MAX_ITEM_PHOTO_BYTES + 1)
    content_type, extension = _upload_image(content, limit=MAX_ITEM_PHOTO_BYTES, label="A fotografia")
    new_name = _stored_name(extension)
    new_path = _write_media(settings, "item_photos", new_name, content)
    old_name: str | None = None
    try:
        old_name = item.photo_storage_name
        item.photo_storage_name = new_name
        item.photo_content_type = content_type
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        _unlink_media(new_path)
        raise
    _remove_media(settings, "item_photos", old_name)
    return {"has_photo": True, "content_type": content_type}


@router.get("/items/{item_id}/photo")
def get_inventory_item_photo(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
) -> Response:
    _require_view(ctx)
    item = _get_item_or_404(db, item_id)
    content = _read_media(
        _media_path(settings, "item_photos", item.photo_storage_name), item.photo_content_type,
        _IMAGE_CONTENT_TYPES, "Fotografia do artigo",
    )
    return Response(
        content=content,
        media_type=item.photo_content_type,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private"},
    )


@router.delete("/items/{item_id}/photo", status_code=204)
def delete_inventory_item_photo(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
) -> Response:
    _require_catalog(ctx)
    item = _get_item_or_404(db, item_id)
    old_name = item.photo_storage_name
    if old_name is None:
        raise HTTPException(status_code=404, detail="Fotografia do artigo não encontrada.")
    item.photo_storage_name = None
    item.photo_content_type = None
    db.commit()
    _remove_media(settings, "item_photos", old_name)
    return Response(status_code=204)


def _detect_document_type(content: bytes) -> tuple[str, str] | None:
    if content.startswith(b"%PDF"):
        return "application/pdf", ".pdf"
    return detect_image_type(content)


def _safe_download_filename(filename: str) -> str:
    # Ignore literal or percent-encoded line breaks, then remove directory components.
    first_line = re.split(r"(?i)%0d|%0a|\r|\n", filename, maxsplit=1)[0]
    name = first_line.replace("\\", "/").split("/")[-1]
    name = "".join(char for char in name if ord(char) >= 32 and ord(char) != 127)
    name = name.strip().strip(".")
    return name or "documento"


def _content_disposition(filename: str, inline: bool) -> str:
    cleaned = _safe_download_filename(filename)
    fallback = cleaned.encode("ascii", "replace").decode("ascii")
    fallback = fallback.replace("?", "_").replace('"', "_").replace("\\", "_")
    if not fallback:
        fallback = "documento"
    encoded = quote(cleaned, safe="!#$&+-.^_`|~")
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


@router.post(
    "/items/{item_id}/documents",
    response_model=InventoryItemDocumentRead,
    status_code=201,
)
async def upload_inventory_item_document(
    item_id: uuid.UUID,
    kind: Literal["datasheet", "manual", "guia", "outro"] = Form(...),
    title: str = Form(..., min_length=1, max_length=256),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
) -> InventoryItemDocumentRead:
    _require_catalog(ctx)
    _get_item_or_404(db, item_id)
    title = " ".join(title.split())
    if not title:
        raise HTTPException(status_code=422, detail="O título do documento é obrigatório.")
    content = await file.read(MAX_ITEM_DOCUMENT_BYTES + 1)
    if len(content) > MAX_ITEM_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="O documento excede o limite de 25 MB.")
    detected = _detect_document_type(content)
    if detected is None:
        raise HTTPException(status_code=400, detail="Formato inválido. Utilize PDF, JPEG, PNG ou WebP.")
    content_type, extension = detected
    filename = file.filename or "documento"
    if len(filename) > 512:
        raise HTTPException(status_code=422, detail="O nome do ficheiro excede o limite de 512 caracteres.")
    stored_name = _stored_name(extension)
    new_path = _write_media(settings, "item_documents", stored_name, content)
    try:
        document = InventoryItemDocument(
            item_id=item_id,
            kind=kind,
            title=title,
            filename=filename,
            stored_name=stored_name,
            content_type=content_type,
            size=len(content),
            created_by_person_id=ctx.person_id,
            created_at=dt.datetime.now(dt.timezone.utc),
        )
        db.add(document)
        db.flush()
        db.refresh(document)
        result = InventoryItemDocumentRead.model_validate(document)
        db.commit()
    except Exception:
        db.rollback()
        _unlink_media(new_path)
        raise
    return result


@router.get("/items/{item_id}/documents", response_model=list[InventoryItemDocumentRead])
def list_inventory_item_documents(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[InventoryItemDocument]:
    _require_view(ctx)
    _get_item_or_404(db, item_id)
    return (
        db.query(InventoryItemDocument)
        .filter(
            InventoryItemDocument.item_id == item_id,
            InventoryItemDocument.deleted_at.is_(None),
        )
        .order_by(InventoryItemDocument.created_at.desc(), InventoryItemDocument.id)
        .all()
    )


@router.get("/items/{item_id}/documents/{document_id}/download")
def download_inventory_item_document(
    item_id: uuid.UUID,
    document_id: uuid.UUID,
    inline: bool = Query(default=False),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
) -> Response:
    _require_view(ctx)
    _get_item_or_404(db, item_id)
    document = db.query(InventoryItemDocument).filter(
        InventoryItemDocument.id == document_id,
        InventoryItemDocument.item_id == item_id,
        InventoryItemDocument.deleted_at.is_(None),
    ).one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Documento do artigo não encontrado.")
    content = _read_media(
        _media_path(settings, "item_documents", document.stored_name),
        document.content_type,
        _DOCUMENT_CONTENT_TYPES,
        "Documento do artigo",
    )
    return Response(
        content=content,
        media_type=document.content_type,
        headers={
            "Content-Disposition": _content_disposition(document.filename, inline),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private",
        },
    )


@router.delete("/items/{item_id}/documents/{document_id}", status_code=204)
def delete_inventory_item_document(
    item_id: uuid.UUID,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> Response:
    _require_catalog(ctx)
    _get_item_or_404(db, item_id)
    document = db.query(InventoryItemDocument).filter(
        InventoryItemDocument.id == document_id,
        InventoryItemDocument.item_id == item_id,
        InventoryItemDocument.deleted_at.is_(None),
    ).one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Documento do artigo não encontrado.")
    document.deleted_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    return Response(status_code=204)
