from __future__ import annotations

import datetime as dt
import struct
import zlib

import pytest

from app.config import get_settings
from app.models.identity import Role, User, UserRole
from app.models.installer_access import InstallerAccessMembership
from app.models.people import Person
from app.models.project import Project, ProjectHistory
from app.models.installer import Installer


def _png_1x1(seed: bytes = b"a") -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00" + seed[:1] * 4))
        + chunk(b"IEND", b"")
    )


@pytest.fixture

def project_photo_dir(monkeypatch, tmp_path):
    photo_dir = tmp_path / "project_photos"
    monkeypatch.setenv("PROJECT_PHOTO_DIR", str(photo_dir))
    get_settings.cache_clear()
    yield photo_dir
    get_settings.cache_clear()


def _headers(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _project(db_session) -> Project:
    return db_session.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


def test_upload_rejects_text_even_if_named_jpeg(db_session, api_client, project_photo_dir):
    project = _project(db_session)
    response = api_client.post(
        f"/api/projects/{project.id}/photo",
        files={"file": ("imagem.jpg", b"isto nao e uma imagem", "image/jpeg")},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert response.status_code == 400
    assert "JPEG, PNG ou WebP" in response.json()["detail"]
    assert list(project_photo_dir.glob("*")) == []


def test_upload_larger_than_10mb_returns_413(db_session, api_client, project_photo_dir):
    project = _project(db_session)
    content = b"\x89PNG\r\n\x1a\n" + b"x" * (10 * 1024 * 1024)
    response = api_client.post(
        f"/api/projects/{project.id}/photo",
        files={"file": ("grande.png", content, "image/png")},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert response.status_code == 413
    assert list(project_photo_dir.glob("*")) == []


def test_upload_is_denied_to_unrelated_pm_and_installer(db_session, api_client, project_photo_dir):
    project = _project(db_session)
    unrelated_pm = Person(display_name="PM foto alheio", email="pm.foto.alheio@example.invalid")
    db_session.add(unrelated_pm)
    db_session.flush()
    pm_user = User(person_id=unrelated_pm.id, email="pm.foto.alheio@example.invalid", is_active=True)
    db_session.add(pm_user)
    db_session.flush()
    pm_role = db_session.query(Role).filter(Role.code == "project_manager").one()
    db_session.add(UserRole(user_id=pm_user.id, role_id=pm_role.id))
    db_session.flush()

    payload = {"file": ("obra.png", _png_1x1(), "image/png")}
    unrelated = api_client.post(
        f"/api/projects/{project.id}/photo",
        files=payload,
        headers=_headers("pm.foto.alheio@example.invalid"),
    )
    assert unrelated.status_code == 403

    installer = db_session.query(Installer).first()
    assert installer is not None
    project.installer_id = installer.id
    collaborator = Person(display_name="Colaborador foto sintético", email="colaborador.foto@example.invalid")
    db_session.add(collaborator)
    db_session.flush()
    role = db_session.query(Role).filter(Role.code == "instalador_colaborador").one()
    user = User(person_id=collaborator.id, email=collaborator.email, is_active=True)
    db_session.add(user)
    db_session.flush()
    db_session.add_all(
        [
            UserRole(user_id=user.id, role_id=role.id),
            InstallerAccessMembership(person_id=collaborator.id, installer_id=installer.id, is_active=True),
        ]
    )
    db_session.flush()
    denied = api_client.post(
        f"/api/projects/{project.id}/photo",
        files=payload,
        headers=_headers("colaborador.foto@example.invalid"),
    )
    assert denied.status_code == 403
    assert list(project_photo_dir.glob("*")) == []


def test_photo_endpoints_require_a_session(db_session, api_client, project_photo_dir):
    project = _project(db_session)
    response = api_client.get(f"/api/projects/{project.id}/photo")
    assert response.status_code == 401


def test_deleted_project_photo_is_404(db_session, api_client, project_photo_dir):
    project = _project(db_session)
    project.deleted_at = dt.datetime.now(dt.timezone.utc)
    db_session.flush()
    response = api_client.get(
        f"/api/projects/{project.id}/photo",
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert response.status_code == 404


def test_replacement_deletes_old_file_and_traversal_filename_is_ignored(db_session, api_client, project_photo_dir):
    project = _project(db_session)
    headers = _headers("pm.um.sintetico@example.invalid")
    first = api_client.post(
        f"/api/projects/{project.id}/photo",
        files={"file": ("../../outside.jpg", _png_1x1(b"a"), "image/png")},
        headers=headers,
    )
    assert first.status_code == 200
    old_name = project.primary_photo_storage_name
    assert old_name is not None and "/" not in old_name and ".." not in old_name
    old_path = project_photo_dir / old_name
    assert old_path.is_file()

    second = api_client.post(
        f"/api/projects/{project.id}/photo",
        files={"file": ("segunda.png", _png_1x1(b"b"), "image/png")},
        headers=headers,
    )
    assert second.status_code == 200
    new_name = project.primary_photo_storage_name
    assert new_name is not None and new_name != old_name
    assert not old_path.exists()
    assert (project_photo_dir / new_name).is_file()

    history = (
        db_session.query(ProjectHistory)
        .filter(ProjectHistory.project_id == project.id, ProjectHistory.field_name == "photo_primary")
        .all()
    )
    assert len(history) == 2

    removed = api_client.delete(f"/api/projects/{project.id}/photo", headers=headers)
    assert removed.status_code == 204
    assert not (project_photo_dir / new_name).exists()
    assert project.primary_photo_storage_name is None
