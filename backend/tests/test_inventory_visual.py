from __future__ import annotations

import pytest

from app.models.inventory import InventoryItemDocument

CHEFE = {"X-Dev-User-Email": "chefe.sintetico@example.invalid"}
VIEWER = {"X-Dev-User-Email": "pm.um.sintetico@example.invalid"}
PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-png"


def _create_item(api_client, *, sku="VIS-001", **extra):
    payload = {"sku": sku, "name": sku, "unit": "un", **extra}
    response = api_client.post("/api/inventory/items", json=payload, headers=CHEFE)
    assert response.status_code == 201, response.text
    return response.json()


def test_item_visual_fields_and_section_label_rules(api_client):
    cases = [
        ({"category": "Cabos DC", "cross_section_mm2": "6"}, "6 mm²"),
        ({"category": "Cabos AC", "subcategory": "Armado"}, "Armado"),
        ({"category": "Inversores", "manufacturer": "Marca X", "power_w": "5000"}, "Marca X"),
        ({"category": "Baterias", "subcategory": "Lítio"}, "Lítio"),
        ({"category": "Painéis", "manufacturer": "Marca Y", "model": "M-450"}, "Marca Y M-450"),
        ({"category": "Estruturas", "subcategory": "Telhado"}, "Telhado"),
        ({"category": "Conectores"}, "Geral"),
    ]
    for index, (fields, expected) in enumerate(cases):
        item = _create_item(api_client, sku=f"VIS-{index:03}", **fields)
        assert item["section_label"] == expected
        assert item["has_photo"] is False
    items = api_client.get("/api/inventory/items", headers=CHEFE).json()
    inverter = next(item for item in items if item["sku"] == "VIS-002")
    assert inverter["manufacturer"] == "Marca X"
    assert inverter["power_w"] == "5000.000"
    panel_item = next(item for item in items if item["sku"] == "VIS-004")
    assert panel_item["manufacturer"] == "Marca Y"
    assert panel_item["model"] == "M-450"


def test_visual_numeric_fields_reject_negative_values(api_client):
    for field in ("power_w", "cross_section_mm2"):
        response = api_client.post(
            "/api/inventory/items",
            json={"sku": f"NEG-{field}", "name": "Negativo", field: "-0.1"},
            headers=CHEFE,
        )
        assert response.status_code == 422, response.text


def test_inventory_item_photo_upload_read_delete_and_headers(tmp_path, make_api_client):
    from app.config import Settings

    settings = Settings(inventory_file_dir=tmp_path)
    client = make_api_client(settings)
    item = _create_item(client, sku="PHOTO-ITEM")
    uploaded = client.post(
        f"/api/inventory/items/{item['id']}/photo",
        files={"file": ("photo.png", PNG, "image/png")},
        headers=CHEFE,
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json() == {"has_photo": True, "content_type": "image/png"}
    read = client.get(f"/api/inventory/items/{item['id']}/photo", headers=VIEWER)
    assert read.status_code == 200
    assert read.content == PNG
    assert read.headers["x-content-type-options"] == "nosniff"
    assert read.headers["cache-control"] == "private"
    listed = client.get("/api/inventory/items", headers=CHEFE).json()
    assert next(row for row in listed if row["id"] == item["id"])["has_photo"] is True
    deleted = client.delete(f"/api/inventory/items/{item['id']}/photo", headers=CHEFE)
    assert deleted.status_code == 204
    assert client.get(f"/api/inventory/items/{item['id']}/photo", headers=VIEWER).status_code == 404


def test_item_photo_rejects_false_magic_and_oversize(tmp_path, make_api_client):
    from app.config import Settings

    client = make_api_client(Settings(inventory_file_dir=tmp_path))
    item = _create_item(client, sku="PHOTO-BAD")
    false_type = client.post(
        f"/api/inventory/items/{item['id']}/photo",
        files={"file": ("fake.png", b"MZ" + b"x" * 20, "image/png")},
        headers=CHEFE,
    )
    assert false_type.status_code == 400
    oversized = client.post(
        f"/api/inventory/items/{item['id']}/photo",
        files={"file": ("large.png", PNG + b"x" * (10 * 1024 * 1024 + 1), "image/png")},
        headers=CHEFE,
    )
    assert oversized.status_code == 413


def test_item_photo_permissions_require_session_and_catalog_management(api_client):
    item = _create_item(api_client, sku="PHOTO-PERM")
    path = f"/api/inventory/items/{item['id']}/photo"
    assert api_client.post(path, files={"file": ("p.png", PNG, "image/png")}).status_code == 401
    assert api_client.post(path, files={"file": ("p.png", PNG, "image/png")}, headers=VIEWER).status_code == 403
    assert api_client.get(path, headers=VIEWER).status_code == 404


def test_item_documents_pdf_upload_list_download_sanitization_and_logical_delete(tmp_path, make_api_client, db_session):
    from app.config import Settings

    client = make_api_client(Settings(inventory_file_dir=tmp_path))
    item = _create_item(client, sku="DOC-ITEM")
    payload = b"%PDF-1.7\nsynthetic document\n%%EOF"
    uploaded = client.post(
        f"/api/inventory/items/{item['id']}/documents",
        data={"kind": "datasheet", "title": "Ficha técnica"},
        files={"file": ("../../evil\r\nX-Evil: yes.pdf", payload, "application/pdf")},
        headers=CHEFE,
    )
    assert uploaded.status_code == 201, uploaded.text
    doc = uploaded.json()
    assert doc["kind"] == "datasheet"
    assert doc["filename"] == "../../evil%0D%0AX-Evil: yes.pdf"
    assert client.get(f"/api/inventory/items/{item['id']}/documents", headers=VIEWER).json() == [doc]
    download_url = f"/api/inventory/items/{item['id']}/documents/{doc['id']}/download"
    download = client.get(download_url, headers=VIEWER)
    assert download.status_code == 200
    assert download.content == payload
    assert download.headers["content-type"].startswith("application/pdf")
    assert download.headers["x-content-type-options"] == "nosniff"
    assert download.headers["cache-control"] == "private"
    disposition = download.headers["content-disposition"]
    assert "attachment" in disposition
    assert "X-Evil" not in disposition and "\r" not in disposition and "\n" not in disposition
    inline = client.get(download_url + "?inline=true", headers=VIEWER)
    assert inline.headers["content-disposition"].startswith("inline;")
    deleted = client.delete(
        f"/api/inventory/items/{item['id']}/documents/{doc['id']}", headers=CHEFE
    )
    assert deleted.status_code == 204
    assert client.get(download_url, headers=VIEWER).status_code == 404
    assert client.get(f"/api/inventory/items/{item['id']}/documents", headers=VIEWER).json() == []
    row = db_session.get(InventoryItemDocument, doc["id"])
    assert row is not None and row.deleted_at is not None


def test_item_documents_accept_images_but_reject_disguised_exe_and_oversize(tmp_path, make_api_client):
    from app.config import Settings

    client = make_api_client(Settings(inventory_file_dir=tmp_path))
    item = _create_item(client, sku="DOC-IMAGE")
    image = client.post(
        f"/api/inventory/items/{item['id']}/documents",
        data={"kind": "manual", "title": "Imagem"},
        files={"file": ("manual.png", PNG, "application/pdf")},
        headers=CHEFE,
    )
    assert image.status_code == 201, image.text
    disguised = client.post(
        f"/api/inventory/items/{item['id']}/documents",
        data={"kind": "guia", "title": "Executável"},
        files={"file": ("manual.pdf", b"MZ" + b"x" * 20, "application/pdf")},
        headers=CHEFE,
    )
    assert disguised.status_code == 400
    oversized = client.post(
        f"/api/inventory/items/{item['id']}/documents",
        data={"kind": "outro", "title": "Grande"},
        files={"file": ("large.pdf", b"%PDF-1.4" + b"x" * (25 * 1024 * 1024 + 1), "application/pdf")},
        headers=CHEFE,
    )
    assert oversized.status_code == 413


def test_document_write_permissions(api_client):
    item = _create_item(api_client, sku="DOC-PERM")
    path = f"/api/inventory/items/{item['id']}/documents"
    assert api_client.post(path, data={"kind": "manual", "title": "x"}, files={"file": ("x.pdf", b"%PDF-x", "application/pdf")}, headers=VIEWER).status_code == 403
    assert api_client.get(path).status_code == 401


def test_category_images_details_replace_remove_and_validate(tmp_path, make_api_client):
    from app.config import Settings

    client = make_api_client(Settings(inventory_file_dir=tmp_path))
    details = client.get("/api/inventory/categories/details", headers=VIEWER)
    assert details.status_code == 200
    panels = next(row for row in details.json() if row["name"] == "Painéis")
    assert panels == {"name": "Painéis", "has_custom_image": False, "image_version": None}
    bad = client.post(
        "/api/inventory/categories/nao-existe/image",
        files={"file": ("x.png", PNG, "image/png")},
        headers=CHEFE,
    )
    assert bad.status_code == 422
    first = client.post(
        "/api/inventory/categories/Painéis/image",
        files={"file": ("one.png", PNG, "image/png")},
        headers=CHEFE,
    )
    assert first.status_code == 200, first.text
    assert first.json()["has_custom_image"] is True
    read = client.get("/api/inventory/categories/Painéis/image", headers=VIEWER)
    assert read.content == PNG
    replacement = PNG + b"replacement"
    replaced = client.post(
        "/api/inventory/categories/Painéis/image",
        files={"file": ("two.png", replacement, "image/png")},
        headers=CHEFE,
    )
    assert replaced.status_code == 200
    assert client.get("/api/inventory/categories/Painéis/image", headers=VIEWER).content == replacement
    removed = client.delete("/api/inventory/categories/Painéis/image", headers=CHEFE)
    assert removed.status_code == 204
    final = next(row for row in client.get("/api/inventory/categories/details", headers=VIEWER).json() if row["name"] == "Painéis")
    assert final["has_custom_image"] is False and final["image_version"] is None
    assert client.get("/api/inventory/categories/Painéis/image", headers=VIEWER).status_code == 404
    # The legacy endpoint keeps the list[str] contract.
    assert client.get("/api/inventory/categories", headers=VIEWER).json()[0] == "Painéis"


def test_category_image_permissions(api_client):
    path = "/api/inventory/categories/Painéis/image"
    assert api_client.post(path, files={"file": ("x.png", PNG, "image/png")}, headers=VIEWER).status_code == 403
    assert api_client.get(path).status_code == 401


def test_category_summary_is_owner_scoped(api_client):
    item = _create_item(api_client, sku="SUMMARY-OWNER", category="Cabos DC", min_stock="7", name="Cabo owner")
    verde_location = api_client.post(
        "/api/inventory/locations",
        json={"code": "VERDE-CENTRAL", "name": "Central Verde", "location_type": "central", "owner": "verde_milenar"},
        headers=CHEFE,
    )
    assert verde_location.status_code == 201, verde_location.text
    for owner, quantity in (("solcor", "5"), ("verde_milenar", "11")):
        stock = api_client.post(
            f"/api/inventory/opening-stock?owner={owner}",
            json={"item_id": item["id"], "quantity": quantity, "reference": f"Inicial {owner}", "idempotency_key": f"summary-{owner}"},
            headers=CHEFE,
        )
        assert stock.status_code == 201, stock.text
    solcor = api_client.get("/api/inventory/categories/summary?owner=solcor", headers=VIEWER)
    verde = api_client.get("/api/inventory/categories/summary?owner=verde_milenar", headers=VIEWER)
    assert solcor.status_code == verde.status_code == 200
    cabos_solcor = next(row for row in solcor.json() if row["category"] == "Cabos DC")
    cabos_verde = next(row for row in verde.json() if row["category"] == "Cabos DC")
    assert cabos_solcor["item_count"] == cabos_verde["item_count"] == 1
    assert cabos_solcor["stock_by_unit"] == [{"unit": "un", "total_stock": "5.000"}]
    assert cabos_verde["stock_by_unit"] == [{"unit": "un", "total_stock": "11.000"}]
    assert "total_stock" not in cabos_solcor
    assert cabos_solcor["low_stock_count"] == 1
    assert cabos_verde["low_stock_count"] == 0


def test_category_summary_keeps_mixed_units_separate_and_owner_scoped(api_client):
    items = []
    for sku, unit in (("SUMMARY-M", "m"), ("SUMMARY-UN", "un")):
        items.append(_create_item(
            api_client,
            sku=sku,
            category="Cabos DC",
            unit=unit,
            min_stock="5",
        ))
    verde_location = api_client.post(
        "/api/inventory/locations",
        json={"code": "SUMMARY-VERDE", "name": "Central Verde resumo", "location_type": "central", "owner": "verde_milenar"},
        headers=CHEFE,
    )
    assert verde_location.status_code == 201, verde_location.text

    for owner, item, quantity in (
        ("solcor", items[0], "2"),
        ("solcor", items[1], "3"),
        ("verde_milenar", items[0], "7"),
    ):
        response = api_client.post(
            f"/api/inventory/opening-stock?owner={owner}",
            json={
                "item_id": item["id"],
                "quantity": quantity,
                "reference": f"Inicial {owner}",
                "idempotency_key": f"summary-mixed-{owner}-{item['sku']}",
            },
            headers=CHEFE,
        )
        assert response.status_code == 201, response.text

    solcor_rows = api_client.get(
        "/api/inventory/categories/summary?owner=solcor", headers=VIEWER
    ).json()
    verde_rows = api_client.get(
        "/api/inventory/categories/summary?owner=verde_milenar", headers=VIEWER
    ).json()
    solcor = next(row for row in solcor_rows if row["category"] == "Cabos DC")
    verde = next(row for row in verde_rows if row["category"] == "Cabos DC")

    assert solcor["item_count"] == verde["item_count"] == 2
    assert solcor["stock_by_unit"] == [
        {"unit": "m", "total_stock": "2.000"},
        {"unit": "un", "total_stock": "3.000"},
    ]
    assert verde["stock_by_unit"] == [
        {"unit": "m", "total_stock": "7.000"},
        {"unit": "un", "total_stock": "0.000"},
    ]
    assert solcor["low_stock_count"] == 2
    assert verde["low_stock_count"] == 1
    empty = next(row for row in solcor_rows if row["category"] == "Painéis")
    assert empty["stock_by_unit"] == []


def test_category_summary_requires_inventory_read_permission(api_client):
    assert api_client.get("/api/inventory/categories/summary").status_code == 401
    assert api_client.get("/api/inventory/categories/summary", headers=VIEWER).status_code == 200


def test_existing_project_photo_helpers_remain_usable():
    from app.api.routes_project_photos import _detect_image_type

    assert _detect_image_type(PNG) == ("image/png", ".png")
    assert _detect_image_type(b"MZ") is None


@pytest.mark.parametrize("category", ["Proteções/Quadros", "Monitorização/Comunicação"])
def test_category_images_with_encoded_slash_upload_read_delete_and_permissions(
    tmp_path, make_api_client, category
):
    from urllib.parse import quote

    from app.config import Settings

    client = make_api_client(Settings(inventory_file_dir=tmp_path))
    encoded_category = quote(category, safe="")
    path = f"/api/inventory/categories/{encoded_category}/image"

    details = client.get("/api/inventory/categories/details", headers=VIEWER)
    summary = client.get("/api/inventory/categories/summary", headers=VIEWER)
    assert details.status_code == 200, details.text
    assert summary.status_code == 200, summary.text
    details_by_name = {row["name"]: row for row in details.json()}
    assert details_by_name[category]["has_custom_image"] is False
    assert any(row["category"] == category for row in summary.json())

    uploaded = client.post(
        path,
        files={"file": ("category.png", PNG, "image/png")},
        headers=CHEFE,
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["name"] == category
    current = client.get("/api/inventory/categories/details", headers=VIEWER)
    assert next(row for row in current.json() if row["name"] == category)["has_custom_image"] is True

    read = client.get(path, headers=VIEWER)
    assert read.status_code == 200, read.text
    assert read.content == PNG
    assert client.post(
        path,
        files={"file": ("category.png", PNG, "image/png")},
        headers=VIEWER,
    ).status_code == 403
    assert client.get(path).status_code == 401
    assert client.delete(path, headers=VIEWER).status_code == 403

    deleted = client.delete(path, headers=CHEFE)
    assert deleted.status_code == 204, deleted.text
    assert client.get(path, headers=VIEWER).status_code == 404
    final_details = client.get("/api/inventory/categories/details", headers=VIEWER)
    assert final_details.status_code == 200, final_details.text
    assert next(row for row in final_details.json() if row["name"] == category)["has_custom_image"] is False
    assert client.get("/api/inventory/categories/summary", headers=VIEWER).status_code == 200

    invalid = client.get(
        f"/api/inventory/categories/{quote('Categoria/ inválida', safe='')}/image",
        headers=VIEWER,
    )
    assert invalid.status_code == 422, invalid.text


@pytest.mark.parametrize("resource", ["category", "document"])
def test_upload_response_does_not_refresh_expired_orm_after_commit(
    tmp_path, make_api_client, db_session, monkeypatch, resource
):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import app

    client = make_api_client(Settings(inventory_file_dir=tmp_path))
    item = _create_item(client, sku=f"NO-REFRESH-{resource}") if resource == "document" else None
    if resource == "document":
        assert item is not None
    client = TestClient(app, raise_server_exceptions=False)

    refresh_state = {"committed": False}
    original_commit = db_session.commit
    original_refresh = db_session.refresh

    def tracked_commit(*args, **kwargs):
        result = original_commit(*args, **kwargs)
        refresh_state["committed"] = True
        return result

    def reject_post_commit_refresh(*args, **kwargs):
        if refresh_state["committed"]:
            raise AssertionError("post-commit ORM refresh must not be needed")
        return original_refresh(*args, **kwargs)

    monkeypatch.setattr(db_session, "commit", tracked_commit)
    monkeypatch.setattr(db_session, "refresh", reject_post_commit_refresh)
    if resource == "category":
        response = client.post(
            "/api/inventory/categories/Painéis/image",
            files={"file": ("category.png", PNG, "image/png")},
            headers=CHEFE,
        )
        assert response.status_code == 200, response.text
        read = client.get("/api/inventory/categories/Painéis/image", headers=VIEWER)
        assert read.status_code == 200
        assert read.content == PNG
    else:
        assert item is not None
        payload = b"%PDF-1.7\ncommitted document\n%%EOF"
        response = client.post(
            f"/api/inventory/items/{item['id']}/documents",
            data={"kind": "manual", "title": "Manual"},
            files={"file": ("manual.pdf", payload, "application/pdf")},
            headers=CHEFE,
        )
        assert response.status_code == 201, response.text
        document = response.json()
        download = client.get(
            f"/api/inventory/items/{item['id']}/documents/{document['id']}/download",
            headers=VIEWER,
        )
        assert download.status_code == 200
        assert download.content == payload


def test_document_commit_failure_removes_new_file_and_database_row(
    tmp_path, make_api_client, db_session, monkeypatch
):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import app
    from app.models.inventory import InventoryItemDocument

    client = make_api_client(Settings(inventory_file_dir=tmp_path))
    item = _create_item(client, sku="DOC-COMMIT-FAIL")
    client = TestClient(app, raise_server_exceptions=False)

    def fail_commit():
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    response = client.post(
        f"/api/inventory/items/{item['id']}/documents",
        data={"kind": "datasheet", "title": "Ficha"},
        files={"file": ("ficha.pdf", b"%PDF-1.7\ncontent\n%%EOF", "application/pdf")},
        headers=CHEFE,
    )

    assert response.status_code == 500
    assert client.get(f"/api/inventory/items/{item['id']}/documents", headers=VIEWER).json() == []
    assert db_session.query(InventoryItemDocument).filter_by(item_id=item["id"]).count() == 0
    assert list((tmp_path / "item_documents").glob("*")) == []


@pytest.mark.parametrize("resource", ["category", "photo"])
def test_failed_replacement_preserves_old_file_and_database_reference(
    tmp_path, make_api_client, db_session, monkeypatch, resource
):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import app

    client = make_api_client(Settings(inventory_file_dir=tmp_path))
    item = _create_item(client, sku=f"REPLACE-FAIL-{resource}") if resource == "photo" else None
    if resource == "category":
        path = "/api/inventory/categories/Painéis/image"
        file_folder = tmp_path / "category_images"
    else:
        assert item is not None
        path = f"/api/inventory/items/{item['id']}/photo"
        file_folder = tmp_path / "item_photos"
    initial = client.post(path, files={"file": ("old.png", PNG, "image/png")}, headers=CHEFE)
    assert initial.status_code == 200, initial.text
    old_paths = list(file_folder.glob("*"))
    assert len(old_paths) == 1
    client = TestClient(app, raise_server_exceptions=False)

    def fail_commit():
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    replacement = client.post(
        path,
        files={"file": ("new.png", PNG + b"replacement", "image/png")},
        headers=CHEFE,
    )

    assert replacement.status_code == 500
    read = client.get(path, headers=VIEWER)
    assert read.status_code == 200
    assert read.content == PNG
    assert list(file_folder.glob("*")) == old_paths
    assert old_paths[0].read_bytes() == PNG


def test_old_file_cleanup_failure_does_not_turn_committed_replacement_into_error(
    tmp_path, make_api_client, monkeypatch
):
    from pathlib import Path

    from app.config import Settings

    client = make_api_client(Settings(inventory_file_dir=tmp_path))
    path = "/api/inventory/categories/Painéis/image"
    initial = client.post(path, files={"file": ("old.png", PNG, "image/png")}, headers=CHEFE)
    assert initial.status_code == 200, initial.text
    folder = tmp_path / "category_images"
    old_path = next(folder.glob("*"))
    original_unlink = Path.unlink

    def fail_old_file_unlink(candidate, *args, **kwargs):
        if candidate == old_path:
            raise OSError("simulated cleanup failure")
        return original_unlink(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_old_file_unlink)
    new_content = PNG + b"replacement"
    response = client.post(
        path,
        files={"file": ("new.png", new_content, "image/png")},
        headers=CHEFE,
    )

    assert response.status_code == 200, response.text
    read = client.get(path, headers=VIEWER)
    assert read.status_code == 200
    assert read.content == new_content
    assert old_path.exists()

