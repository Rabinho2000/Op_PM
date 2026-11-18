"""Serve the private cable-dimensioning engine script."""
from __future__ import annotations

import hashlib
import json
import logging
import stat as stat_module
import threading
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings, get_settings
from app.schemas.cable_tool import CableToolRead
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["cable-tool"])

_MAX_TOOL_BYTES = 8 * 1024 * 1024
_UNAVAILABLE_DETAIL = "Ferramenta de dimensionamento indisponível."
_FORBIDDEN_DETAIL = "Sem permissão para abrir a ferramenta de dimensionamento."


class _CableToolUnavailable(Exception):
    """Known private-script loading failure with no path in its message."""


@dataclass(frozen=True)
class _CachedCableTool:
    path: Path
    mtime_ns: int
    size: int
    sha256: str
    script: str


_cache_lock = threading.Lock()
_cache: _CachedCableTool | None = None


def _file_signature(path: Path) -> tuple[int, int]:
    try:
        file_stat = path.stat()
    except (OSError, ValueError) as exc:
        raise _CableToolUnavailable from exc
    if not stat_module.S_ISREG(file_stat.st_mode):
        raise _CableToolUnavailable
    if file_stat.st_size > _MAX_TOOL_BYTES:
        raise _CableToolUnavailable
    return file_stat.st_mtime_ns, file_stat.st_size


def _load_tool(path: Path) -> _CachedCableTool:
    global _cache

    mtime_ns, size = _file_signature(path)
    with _cache_lock:
        cached = _cache
        if (
            cached is not None
            and cached.path == path
            and cached.mtime_ns == mtime_ns
            and cached.size == size
        ):
            return cached

        try:
            with path.open("rb") as handle:
                content = handle.read(_MAX_TOOL_BYTES + 1)
        except (OSError, ValueError) as exc:
            raise _CableToolUnavailable from exc
        if len(content) > _MAX_TOOL_BYTES:
            raise _CableToolUnavailable
        try:
            script = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _CableToolUnavailable from exc

        cached = _CachedCableTool(
            path=path,
            mtime_ns=mtime_ns,
            size=size,
            sha256=hashlib.sha256(content).hexdigest(),
            script=script,
        )
        _cache = cached
        return cached


def _manifest_engine_version(path: Path, digest: str) -> str:
    fallback = f"cabos-engine@{digest[:12]}"
    manifest_path = path.with_name(f"{path.stem}.manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return fallback
    if not isinstance(manifest, dict):
        return fallback
    version = manifest.get("engine_version")
    if not isinstance(version, str) or not (1 <= len(version) <= 64):
        return fallback
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in version):
        return fallback
    return version


@router.get("/cable-tool", response_model=CableToolRead)
def get_cable_tool(
    response: Response,
    ctx: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
) -> CableToolRead:
    """Return the UTF-8 engine script with its manifest version and digest."""
    if not ctx.has_permission("cable_design.view_costs"):
        raise HTTPException(status_code=403, detail=_FORBIDDEN_DETAIL)

    path = settings.cable_tool_file
    if path is None:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL)

    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    try:
        cached = _load_tool(path)
        engine_version = _manifest_engine_version(path, cached.sha256)
    except _CableToolUnavailable as exc:
        logger.warning("Motor de cabos indisponível: %s", exc)
        raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL) from None
    except (OSError, SQLAlchemyError):
        # Keep filesystem/database implementation details out of the API (only in the log).
        logger.exception("Erro ao carregar o motor de cabos")
        raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL) from None

    return CableToolRead(
        engine_version=engine_version,
        sha256=cached.sha256,
        script=cached.script,
    )
