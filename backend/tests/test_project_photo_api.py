from __future__ import annotations

import struct
import zlib

from app.config import get_settings
from app.models.project import Project


def _png_1x1() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\xff"))
        + chunk(b"IEND", b"")
    )


def test_project_manager_can_upload_and_view_primary_photo(db_session, api_client, monkeypatch, tmp_path):
    project = db_session.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()
    monkeypatch.setenv("PROJECT_PHOTO_DIR", str(tmp_path / "project_photos"))
    get_settings.cache_clear()
    try:
        headers = {"X-Dev-User-Email": "pm.um.sintetico@example.invalid"}
        upload = api_client.post(
            f"/api/projects/{project.id}/photo",
            files={"file": ("instalacao.png", _png_1x1(), "image/png")},
            headers=headers,
        )
        assert upload.status_code == 200, upload.text

        detail = api_client.get(f"/api/projects/{project.id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["has_project_photo"] is True
        assert detail.json()["can_edit_project_photo"] is True

        image = api_client.get(f"/api/projects/{project.id}/photo", headers=headers)
        assert image.status_code == 200
        assert image.content == _png_1x1()
        assert image.headers["content-type"] == "image/png"
        assert image.headers["x-content-type-options"] == "nosniff"
        assert image.headers["cache-control"] == "private"
    finally:
        get_settings.cache_clear()
