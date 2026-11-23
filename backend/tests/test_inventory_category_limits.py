from __future__ import annotations

import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import event

from app.api.routes_inventory import (
    create_inventory_category_endpoint,
    create_item_endpoint,
    update_item_endpoint,
)
from app.api.routes_inventory_visual import (
    _category_details,
    delete_inventory_category_image,
    get_inventory_category_image,
    upload_inventory_category_image,
)
from app.config import Settings
from app.models.inventory import (
    InventoryCatalogHistory,
    InventoryCategory,
    InventoryCategoryImage,
    InventoryItem,
)
from app.schemas.inventory_catalog import (
    InventoryCategoryCreate,
    InventoryItemCreate,
    InventoryItemUpdate,
    inventory_category_key_for_read,
)
from app.security.permissions import AuthContext
from app.services.inventory_categories import list_inventory_category_names

CHEFE = AuthContext(
    user=None,
    person_id=None,
    role_codes=frozenset(),
    permission_codes=frozenset({"inventory.manage_catalog", "inventory.view"}),
)


def test_overexpanded_input_handlers_return_422_before_sql_or_file_effects(db_session, tmp_path):
    category = "\ufdfa" * 64
    before = {
        "categories": db_session.query(InventoryCategory).count(),
        "items": db_session.query(InventoryItem).count(),
        "history": db_session.query(InventoryCatalogHistory).count(),
        "images": db_session.query(InventoryCategoryImage).count(),
    }
    statements: list[str] = []
    connection = db_session.connection()

    def record_statement(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(connection, "before_cursor_execute", record_statement)
    try:
        with pytest.raises(HTTPException) as rejected_category:
            create_inventory_category_endpoint(
                InventoryCategoryCreate(name=category), db_session, CHEFE
            )
        assert rejected_category.value.status_code == 422
        assert rejected_category.value.detail == "A categoria excede o limite após normalização Unicode."

        with pytest.raises(HTTPException) as rejected_article:
            create_item_endpoint(
                InventoryItemCreate(
                    sku="OVEREXPANDED-CATEGORY",
                    name="Artigo de teste",
                    category=category,
                ),
                db_session,
                CHEFE,
            )
        assert rejected_article.value.status_code == 422
        assert rejected_article.value.detail == "A categoria excede o limite após normalização Unicode."

        path_category = category
        upload = UploadFile(filename="test.png", file=BytesIO(b"not-read"))
        settings = Settings(inventory_file_dir=tmp_path)
        with pytest.raises(HTTPException) as rejected_upload:
            asyncio.run(
                upload_inventory_category_image(
                    path_category, upload, db_session, CHEFE, settings
                )
            )
        assert rejected_upload.value.status_code == 422
        assert rejected_upload.value.detail == "A categoria excede o limite após normalização Unicode."

        with pytest.raises(HTTPException) as rejected_read:
            get_inventory_category_image(path_category, db_session, CHEFE, settings)
        assert rejected_read.value.status_code == 422
        with pytest.raises(HTTPException) as rejected_delete:
            delete_inventory_category_image(path_category, db_session, CHEFE, settings)
        assert rejected_delete.value.status_code == 422
    finally:
        event.remove(connection, "before_cursor_execute", record_statement)

    assert statements == []
    assert not list(tmp_path.rglob("*"))
    assert db_session.query(InventoryCategory).count() == before["categories"]
    assert db_session.query(InventoryItem).count() == before["items"]
    assert db_session.query(InventoryCatalogHistory).count() == before["history"]
    assert db_session.query(InventoryCategoryImage).count() == before["images"]


def test_legacy_same_value_patch_is_allowed_but_changed_overexpanded_value_is_rejected(
    db_session,
):
    created_category = create_inventory_category_endpoint(
        InventoryCategoryCreate(name="Ferramentas térmicas"), db_session, CHEFE
    )
    assert created_category.name == "Ferramentas térmicas"
    assert created_category.category_key == "ferramentastermicas"

    legacy_category = "\ufdfa" * 64
    modified_category = "\ufdfa" * 63 + "A"
    legacy = InventoryItem(
        sku="LEGACY-OVEREXPANDED-CATEGORY",
        name="Artigo legado",
        unit="un",
        category=legacy_category,
    )
    db_session.add(legacy)
    db_session.flush()
    assert legacy_category in list_inventory_category_names(db_session)
    details = _category_details(db_session)
    legacy_detail = next(row for row in details if row.name == legacy_category)
    assert legacy_detail.category_key == inventory_category_key_for_read(legacy_category)
    assert len(legacy_detail.slug) <= 256

    history_before_same_patch = db_session.query(InventoryCatalogHistory).count()
    same_value = update_item_endpoint(
        legacy.id,
        InventoryItemUpdate(category=legacy_category),
        db_session,
        CHEFE,
    )
    assert same_value.category == legacy_category
    assert same_value.category_key == inventory_category_key_for_read(legacy_category)
    assert db_session.query(InventoryCatalogHistory).count() == history_before_same_patch
    history_before = db_session.query(InventoryCatalogHistory).count()

    with pytest.raises(HTTPException) as rejected_change:
        update_item_endpoint(
            legacy.id,
            InventoryItemUpdate(category=modified_category),
            db_session,
            CHEFE,
        )
    assert rejected_change.value.status_code == 422
    assert rejected_change.value.detail == "A categoria excede o limite após normalização Unicode."
    db_session.expire_all()
    assert db_session.get(InventoryItem, legacy.id).category == legacy_category
    assert db_session.query(InventoryCatalogHistory).count() == history_before

    valid_change = update_item_endpoint(
        legacy.id,
        InventoryItemUpdate(category="Ferramentas térmicas"),
        db_session,
        CHEFE,
    )
    assert valid_change.category == "Ferramentas térmicas"

    alias = create_item_endpoint(
        InventoryItemCreate(
            sku="CATEGORY-ALIAS-COMPAT",
            name="Artigo com alias",
            category="Cabo DC",
        ),
        db_session,
        CHEFE,
    )
    assert alias.category == "Cabos DC"

    legacy_alias = InventoryItem(
        sku="CATEGORY-ALIAS-PATCH",
        name="Artigo com alias legado",
        unit="un",
        category="Cabo DC",
    )
    db_session.add(legacy_alias)
    db_session.flush()
    patched_alias = update_item_endpoint(
        legacy_alias.id,
        InventoryItemUpdate(category="Cabo DC"),
        db_session,
        CHEFE,
    )
    assert patched_alias.category == "Cabos DC"

    other = create_item_endpoint(
        InventoryItemCreate(
            sku="CATEGORY-OTHER-COMPAT",
            name="Artigo Outros",
            category="Outros",
        ),
        db_session,
        CHEFE,
    )
    assert other.category == "Outros"
    assert other.category_key == "outros"
