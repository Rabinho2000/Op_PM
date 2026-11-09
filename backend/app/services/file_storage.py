"""Helpers partilhados para ficheiros privados carregados pela API."""
from __future__ import annotations

import re
from pathlib import Path


IMAGE_MIME_TYPES = {
    "jpeg": ("image/jpeg", ".jpg"),
    "png": ("image/png", ".png"),
    "webp": ("image/webp", ".webp"),
}
STORED_IMAGE_NAME = re.compile(r"^[0-9a-f]{32}\.(?:jpg|png|webp)$")


def detect_image_type(content: bytes) -> tuple[str, str] | None:
    """Detecta imagem pelo conteúdo, ignorando nome e MIME enviados pelo cliente."""
    if content.startswith(b"\xff\xd8\xff"):
        return IMAGE_MIME_TYPES["jpeg"]
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return IMAGE_MIME_TYPES["png"]
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return IMAGE_MIME_TYPES["webp"]
    return None


def safe_stored_file_path(directory: Path, storage_name: str | None, pattern: re.Pattern[str]) -> Path | None:
    """Resolve apenas nomes internos que correspondem ao formato permitido."""
    if storage_name is None or not pattern.fullmatch(storage_name):
        return None
    resolved_directory = directory.resolve()
    path = (resolved_directory / storage_name).resolve()
    if path.parent != resolved_directory:
        return None
    return path


def write_private_file(directory: Path, storage_name: str, content: bytes) -> Path:
    """Cria a pasta privada e escreve com criação exclusiva (sem sobrescrever)."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory.resolve() / storage_name
    with path.open("xb") as destination:
        destination.write(content)
    return path
