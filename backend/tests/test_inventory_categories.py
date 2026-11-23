from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.inventory import (
    INVENTORY_CATEGORY_KEY_MAX_LENGTH,
    InventoryCatalogHistory,
    InventoryCategory,
    InventoryItem,
    InventoryMovement,
)
from app.schemas.inventory_catalog import (
    inventory_category_key,
    inventory_category_key_for_read,
    inventory_category_slug,
    normalize_inventory_category_for_read,
)

CHEFE = {"X-Dev-User-Email": "chefe.sintetico@example.invalid"}
VIEWER = {"X-Dev-User-Email": "pm.um.sintetico@example.invalid"}


def test_manager_creates_category_without_item_or_stock(db_session, api_client):
    items_before = db_session.query(InventoryItem).count()
    movements_before = db_session.query(InventoryMovement).count()

    created = api_client.post(
        "/api/inventory/categories",
        json={"name": "  Ferramentas   especiais  "},
        headers=CHEFE,
    )

    assert created.status_code == 201, created.text
    assert created.json() == {
        "name": "Ferramentas especiais",
        "category_key": "ferramentasespeciais",
        "slug": "ferramentas-especiais",
        "has_custom_image": False,
        "image_version": None,
    }
    assert "id" not in created.json()
    assert db_session.query(InventoryCategory).filter_by(name="Ferramentas especiais").one()
    assert db_session.query(InventoryItem).count() == items_before
    assert db_session.query(InventoryMovement).count() == movements_before
    assert "Ferramentas especiais" in api_client.get("/api/inventory/categories", headers=VIEWER).json()
    details = api_client.get("/api/inventory/categories/details", headers=VIEWER)
    assert details.status_code == 200, details.text
    assert any(row["name"] == "Ferramentas especiais" for row in details.json())


def test_category_creation_requires_inventory_catalog_permission(db_session, api_client):
    denied = api_client.post(
        "/api/inventory/categories",
        json={"name": "Categoria só de gestor"},
        headers=VIEWER,
    )
    assert denied.status_code == 403, denied.text
    assert db_session.query(InventoryCategory).filter_by(name="Categoria só de gestor").one_or_none() is None


def test_category_names_are_validated_and_duplicates_are_rejected(api_client):
    assert api_client.post("/api/inventory/categories", json={"name": "   "}, headers=CHEFE).status_code == 422
    assert api_client.post("/api/inventory/categories", json={"name": "!!!"}, headers=CHEFE).status_code == 422

    created = api_client.post(
        "/api/inventory/categories",
        json={"name": "Ferramentas"},
        headers=CHEFE,
    )
    assert created.status_code == 201, created.text
    duplicate = api_client.post(
        "/api/inventory/categories",
        json={"name": "  ferramentás!!!  "},
        headers=CHEFE,
    )
    assert duplicate.status_code == 409, duplicate.text
    builtin = api_client.post(
        "/api/inventory/categories",
        json={"name": "Painel"},
        headers=CHEFE,
    )
    assert builtin.status_code == 409, builtin.text


def test_existing_custom_article_categories_stay_visible_and_prevent_duplicates(db_session, api_client):
    db_session.add(
        InventoryItem(sku="CUSTOM-CATEGORY-LEGACY", name="Artigo legado", unit="un", category="Módulos antigos")
    )
    db_session.flush()

    assert "Módulos antigos" in api_client.get("/api/inventory/categories", headers=VIEWER).json()
    assert any(
        row["name"] == "Módulos antigos"
        for row in api_client.get("/api/inventory/categories/details", headers=VIEWER).json()
    )
    duplicate = api_client.post(
        "/api/inventory/categories",
        json={"name": "Módulos antigos"},
        headers=CHEFE,
    )
    assert duplicate.status_code == 409, duplicate.text


def test_article_category_must_exist_before_it_is_assigned(db_session, api_client):
    unknown = api_client.post(
        "/api/inventory/items",
        json={"sku": "CATEGORY-UNKNOWN", "name": "Artigo", "category": "Ainda não existe"},
        headers=CHEFE,
    )
    assert unknown.status_code == 422, unknown.text
    assert db_session.query(InventoryItem).filter_by(sku="CATEGORY-UNKNOWN").one_or_none() is None

    created = api_client.post("/api/inventory/categories", json={"name": "Ainda não existe"}, headers=CHEFE)
    assert created.status_code == 201, created.text
    # Equivalent spelling resolves to the canonical stored name.
    article = api_client.post(
        "/api/inventory/items",
        json={"sku": "CATEGORY-KNOWN", "name": "Artigo", "category": "  AINDA nao EXISTE "},
        headers=CHEFE,
    )
    assert article.status_code == 201, article.text
    assert article.json()["category"] == "Ainda não existe"
    assert article.json()["category_key"] == "aindanaoexiste"

    moved = api_client.patch(
        f"/api/inventory/items/{article.json()['id']}",
        json={"category": "Outra inexistente"},
        headers=CHEFE,
    )
    assert moved.status_code == 422, moved.text
    cleared = api_client.patch(
        f"/api/inventory/items/{article.json()['id']}", json={"category": None}, headers=CHEFE
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["category"] is None


def test_builtin_categories_come_first_and_keep_their_order(api_client):
    from app.models.inventory import INVENTORY_CATEGORIES

    created = api_client.post("/api/inventory/categories", json={"name": "Aaa primeira"}, headers=CHEFE)
    assert created.status_code == 201, created.text
    names = api_client.get("/api/inventory/categories", headers=VIEWER).json()
    assert names[: len(INVENTORY_CATEGORIES)] == list(INVENTORY_CATEGORIES)
    assert "Aaa primeira" in names[len(INVENTORY_CATEGORIES):]


def test_unicode_custom_category_is_kept_and_can_be_assigned_to_article(api_client):
    created = api_client.post(
        "/api/inventory/categories",
        json={"name": "工具"},
        headers=CHEFE,
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "工具"

    article = api_client.post(
        "/api/inventory/items",
        json={"sku": "UNICODE-CATEGORY", "name": "Alicate 工具", "category": "工具"},
        headers=CHEFE,
    )
    assert article.status_code == 201, article.text
    assert article.json()["category"] == "工具"
    assert any(
        row["name"] == "工具"
        for row in api_client.get("/api/inventory/categories/details", headers=VIEWER).json()
    )


@pytest.mark.parametrize(
    "reserved_label_variant",
    ["Outros/Sem categoria", "OUTROS / SEM CATEGORIA", "Outros - sem categoria"],
)
def test_reserved_unassigned_label_is_rejected_for_new_and_changed_articles(
    db_session, api_client, reserved_label_variant
):
    created = api_client.post(
        "/api/inventory/items",
        json={"sku": f"OTHER-RESERVED-{uuid4().hex[:8]}", "name": "Artigo Outros", "category": "Outros"},
        headers=CHEFE,
    )
    assert created.status_code == 201, created.text
    assert created.json()["category"] == "Outros"
    assert created.json()["category_key"] == "outros"

    reserved_sku = f"RESERVED-{uuid4().hex[:8]}"
    rejected_create = api_client.post(
        "/api/inventory/items",
        json={
            "sku": reserved_sku,
            "name": "Categoria reservada",
            "category": reserved_label_variant,
        },
        headers=CHEFE,
    )
    assert rejected_create.status_code == 422, rejected_create.text
    assert "reservada" in rejected_create.json()["detail"]
    assert db_session.query(InventoryItem).filter_by(sku=reserved_sku).one_or_none() is None

    rejected_update = api_client.patch(
        f"/api/inventory/items/{created.json()['id']}",
        json={"category": reserved_label_variant},
        headers=CHEFE,
    )
    assert rejected_update.status_code == 422, rejected_update.text
    db_session.expire_all()
    assert db_session.get(InventoryItem, created.json()["id"]).category == "Outros"

    denied_sku = f"RESERVED-DENIED-{uuid4().hex[:8]}"
    denied = api_client.post(
        "/api/inventory/items",
        json={
            "sku": denied_sku,
            "name": "Tentativa sem permissão",
            "category": reserved_label_variant,
        },
        headers=VIEWER,
    )
    assert denied.status_code == 403, denied.text
    assert db_session.query(InventoryItem).filter_by(sku=denied_sku).one_or_none() is None


def test_legacy_reserved_category_remains_readable_and_same_value_can_be_resubmitted(db_session, api_client):
    legacy = InventoryItem(
        sku="LEGACY-RESERVED-CATEGORY",
        name="Artigo literal legado",
        unit="un",
        category="Outros/Sem categoria",
    )
    db_session.add(legacy)
    db_session.flush()

    read = api_client.get("/api/inventory/items", headers=VIEWER)
    assert read.status_code == 200, read.text
    row = next(item for item in read.json() if item["sku"] == legacy.sku)
    assert row["category"] == "Outros/Sem categoria"
    assert row["category_key"] == "outrossemcategoria"
    catalog_names = api_client.get("/api/inventory/categories", headers=VIEWER)
    assert catalog_names.status_code == 200, catalog_names.text
    assert "Outros" in catalog_names.json()
    assert "Outros/Sem categoria" in catalog_names.json()

    details = api_client.get("/api/inventory/categories/details", headers=VIEWER)
    by_name = {category["name"]: category for category in details.json()}
    assert by_name["Outros"]["slug"] == "outros-sem-categoria"
    assert by_name["Outros/Sem categoria"]["category_key"] == "outrossemcategoria"
    assert by_name["Outros/Sem categoria"]["slug"] == "outros-sem-categoria--legado"

    unchanged = api_client.patch(
        f"/api/inventory/items/{legacy.id}",
        json={"name": "Artigo legado editado", "category": "Outros/Sem categoria"},
        headers=CHEFE,
    )
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["category"] == "Outros/Sem categoria"


def test_category_key_expansion_is_rejected_as_business_error_before_persistence(db_session, api_client):
    # U+FDFA expands to 15 alphanumeric characters under the accepted NFKD +
    # casefold contract; 64 source characters therefore produce a 960-char key.
    name = "\ufdfa" * 64
    assert len(inventory_category_key(name)) == 960
    before = db_session.query(InventoryCategory).count()

    rejected = api_client.post("/api/inventory/categories", json={"name": name}, headers=CHEFE)
    assert rejected.status_code == 422, rejected.text
    assert "normalização Unicode" in rejected.json()["detail"]
    db_session.expire_all()
    assert db_session.query(InventoryCategory).count() == before
    assert db_session.query(InventoryCategory).filter_by(name=name).one_or_none() is None

    items_before = db_session.query(InventoryItem).count()
    history_before = db_session.query(InventoryCatalogHistory).count()
    rejected_article = api_client.post(
        "/api/inventory/items",
        json={"sku": "OVERLONG-CATEGORY", "name": "Artigo de teste", "category": name},
        headers=CHEFE,
    )
    assert rejected_article.status_code == 422, rejected_article.text
    assert rejected_article.json()["detail"] == "A categoria excede o limite após normalização Unicode."
    assert "input" not in rejected_article.text
    db_session.expire_all()
    assert db_session.query(InventoryItem).count() == items_before
    assert db_session.query(InventoryCatalogHistory).count() == history_before
    assert db_session.query(InventoryItem).filter_by(sku="OVERLONG-CATEGORY").one_or_none() is None

    denied = api_client.post("/api/inventory/categories", json={"name": name}, headers=VIEWER)
    assert denied.status_code == 403, denied.text
    assert INVENTORY_CATEGORY_KEY_MAX_LENGTH == 256
    assert db_session.query(InventoryCategory).filter_by(name=name).one_or_none() is None


def test_inventory_category_key_and_slug_follow_unicode_casefold_contract():
    assert inventory_category_key("Straße") == inventory_category_key("STRASSE") == "strasse"
    assert inventory_category_key("工具") == "工具"
    assert inventory_category_key("材料") == "材料"
    assert inventory_category_slug("Straße") == inventory_category_slug("STRASSE") == "strasse"
    assert inventory_category_slug("工具") == "工具"
    assert inventory_category_slug("Outros") == "outros-sem-categoria"
    assert inventory_category_slug("Outros/Sem categoria") == "outros-sem-categoria--legado"
    assert inventory_category_slug("OUTROS / SEM CATEGORIA") == "outros-sem-categoria--legado"

    assert normalize_inventory_category_for_read("!!!") == "!!!"
    exclamation_key = inventory_category_key_for_read("!!!")
    question_key = inventory_category_key_for_read("???")
    assert exclamation_key.startswith("!legacy:")
    assert exclamation_key == inventory_category_key_for_read("!!!")
    assert exclamation_key != question_key
    assert len(exclamation_key) <= INVENTORY_CATEGORY_KEY_MAX_LENGTH


def test_oversized_legacy_category_is_read_safely_and_patch_only_rejects_changes(db_session, api_client):
    legacy_name = "\ufdfa" * 64
    changed_oversized_name = "\ufdfa" * 63 + "A"
    legacy = InventoryItem(
        sku="LEGACY-OVERSIZED-CATEGORY",
        name="Artigo legado longo",
        unit="un",
        category=legacy_name,
    )
    db_session.add(legacy)
    db_session.flush()

    items = api_client.get("/api/inventory/items", headers=VIEWER)
    assert items.status_code == 200, items.text
    read_item = next(row for row in items.json() if row["sku"] == legacy.sku)
    assert read_item["category"] == legacy_name
    assert read_item["category_key"] == inventory_category_key_for_read(legacy_name)
    assert len(read_item["category_key"]) <= INVENTORY_CATEGORY_KEY_MAX_LENGTH
    assert read_item["category_key"].startswith("!legacy:")

    names = api_client.get("/api/inventory/categories", headers=VIEWER)
    assert names.status_code == 200, names.text
    assert legacy_name in names.json()
    details = api_client.get("/api/inventory/categories/details", headers=VIEWER)
    assert details.status_code == 200, details.text
    legacy_detail = next(row for row in details.json() if row["name"] == legacy_name)
    assert legacy_detail["category_key"] == read_item["category_key"]
    assert len(legacy_detail["slug"]) <= INVENTORY_CATEGORY_KEY_MAX_LENGTH

    unchanged = api_client.patch(
        f"/api/inventory/items/{legacy.id}",
        json={"category": legacy_name},
        headers=CHEFE,
    )
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["category"] == legacy_name
    rejected_change = api_client.patch(
        f"/api/inventory/items/{legacy.id}",
        json={"category": changed_oversized_name},
        headers=CHEFE,
    )
    assert rejected_change.status_code == 422, rejected_change.text
    assert "input" not in rejected_change.text
    db_session.expire_all()
    assert db_session.get(InventoryItem, legacy.id).category == legacy_name

    assert api_client.post(
        "/api/inventory/categories", json={"name": "Ferramentas térmicas"}, headers=CHEFE
    ).status_code == 201
    valid_change = api_client.patch(
        f"/api/inventory/items/{legacy.id}",
        json={"category": "Ferramentas térmicas"},
        headers=CHEFE,
    )
    assert valid_change.status_code == 200, valid_change.text
    assert valid_change.json()["category"] == "Ferramentas térmicas"


def test_legacy_article_categories_publish_one_unicode_key_and_slug(db_session, api_client):
    for sku, category in (
        ("LEGACY-STRASSE-1", "Straße"),
        ("LEGACY-STRASSE-2", "STRASSE"),
        ("LEGACY-TOOLS", "工具"),
        ("LEGACY-MATERIALS", "材料"),
    ):
        db_session.add(InventoryItem(sku=sku, name=sku, unit="un", category=category))
    db_session.flush()

    items = {row["sku"]: row for row in api_client.get("/api/inventory/items", headers=VIEWER).json()}
    for sku, category in (("LEGACY-STRASSE-1", "Straße"), ("LEGACY-STRASSE-2", "STRASSE"), ("LEGACY-TOOLS", "工具")):
        assert items[sku]["category_key"] == inventory_category_key(category)

    details_response = api_client.get("/api/inventory/categories/details", headers=VIEWER)
    assert details_response.status_code == 200, details_response.text
    details = details_response.json()
    by_key = {row["category_key"]: row for row in details}
    assert sum(row["category_key"] == "strasse" for row in details) == 1
    assert by_key["strasse"]["slug"] == "strasse"
    assert by_key["工具"]["slug"] == "工具"
    assert by_key["材料"]["slug"] == "材料"
    assert by_key["工具"]["category_key"] != by_key["材料"]["category_key"]

    duplicate = api_client.post(
        "/api/inventory/categories",
        json={"name": "strasse"},
        headers=CHEFE,
    )
    assert duplicate.status_code == 409, duplicate.text


def test_custom_category_summary_keeps_company_stock_isolated(api_client):
    category = api_client.post(
        "/api/inventory/categories",
        json={"name": "Ferramentas de medição"},
        headers=CHEFE,
    )
    assert category.status_code == 201, category.text
    article = api_client.post(
        "/api/inventory/items",
        json={"sku": "CUSTOM-CATEGORY-STOCK", "name": "Multímetro", "unit": "un", "category": category.json()["name"]},
        headers=CHEFE,
    )
    assert article.status_code == 201, article.text

    central = next(
        (
            location for location in api_client.get("/api/inventory/locations?owner=solcor", headers=CHEFE).json()
            if location["owner"] == "solcor" and location["location_type"] == "central" and location["is_active"]
        ),
        None,
    )
    if central is None:
        created_central = api_client.post(
            "/api/inventory/locations",
            json={"code": f"CAT-SOL-{uuid4().hex[:8]}", "name": "Central de teste Solcor", "location_type": "central"},
            headers=CHEFE,
        )
        assert created_central.status_code == 201, created_central.text
        central = created_central.json()

    movement = api_client.post(
        "/api/inventory/opening-stock?owner=solcor",
        json={
            "item_id": article.json()["id"],
            "quantity": "7",
            "reference": "Teste de isolamento de stock",
            "idempotency_key": f"category-isolation-{uuid4()}",
            "location_id": central["id"],
        },
        headers=CHEFE,
    )
    assert movement.status_code == 201, movement.text

    solcor = api_client.get("/api/inventory/categories/summary?owner=solcor", headers=VIEWER)
    verde = api_client.get("/api/inventory/categories/summary?owner=verde_milenar", headers=VIEWER)
    assert solcor.status_code == verde.status_code == 200
    solcor_category = next(row for row in solcor.json() if row["category"] == category.json()["name"])
    verde_category = next(row for row in verde.json() if row["category"] == category.json()["name"])
    assert solcor_category["stock_by_unit"] == [{"unit": "un", "total_stock": "7.000"}]
    assert verde_category["stock_by_unit"] == [{"unit": "un", "total_stock": "0.000"}]
