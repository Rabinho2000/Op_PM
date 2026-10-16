"""Read-only API for private material prices and cable-engine datasets."""
from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import app.prices_db as prices_db
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext
from app.services.material_prices import (
    MaterialPricesPermissionError,
    MaterialPricesStorageError,
    MaterialPricesValidationError,
    get_engine_data,
    list_material_prices,
)


class _SanitisedValidationRoute(APIRoute):
    """Never serialize untrusted query values in validation responses."""

    def get_route_handler(self):
        original_route_handler = super().get_route_handler()

        async def sanitised_handler(request):
            try:
                return await original_route_handler(request)
            except RequestValidationError:
                return JSONResponse(status_code=422, content={"detail": "Parâmetros inválidos."})

        return sanitised_handler


router = APIRouter(prefix="/api", tags=["material-prices"])
router.route_class = _SanitisedValidationRoute

_GENERIC_STORAGE_FAILURE = "A BD privada de preços está temporariamente indisponível."


def _require(ctx: AuthContext, permission: str, message: str) -> None:
    if not ctx.has_permission(permission):
        raise HTTPException(status_code=403, detail=message)


def _private_session(*, read_only: bool) -> Session:
    try:
        return prices_db.open_prices_session(read_only=read_only)
    except (OSError, RuntimeError, SQLAlchemyError) as exc:
        raise MaterialPricesStorageError(_GENERIC_STORAGE_FAILURE) from exc


def _etag(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f'"{hashlib.sha256(encoded).hexdigest()}"'


def _if_none_match_matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    return "*" in {part.strip() for part in header.split(",")} or etag in {
        part.strip() for part in header.split(",")
    }


@router.get("/cable-design/engine-data", response_model=None)
def cable_engine_data(
    request: Request,
    response: Response,
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, object] | Response:
    _require(ctx, "cable_design.edit", "Sem permissão para usar o motor de dimensionamento de cabos.")
    db: Session | None = None
    try:
        db = _private_session(read_only=True)
        payload = get_engine_data(db)
    except MaterialPricesStorageError as exc:
        raise HTTPException(status_code=503, detail=_GENERIC_STORAGE_FAILURE) from exc
    except (SQLAlchemyError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=_GENERIC_STORAGE_FAILURE) from exc
    finally:
        if db is not None:
            db.close()

    etag = _etag(payload)
    headers = {"ETag": etag, "Cache-Control": "private, no-store"}
    if _if_none_match_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return payload


@router.get("/material-prices")
def material_prices(
    response: Response,
    domain: str | None = Query(default=None, max_length=128),
    ref: str | None = Query(default=None, max_length=128),
    current: bool = Query(default=True),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[dict[str, object]]:
    _require(ctx, "price.view", "Sem permissão para consultar preços de materiais.")
    db: Session | None = None
    try:
        db = _private_session(read_only=True)
        result = list_material_prices(db, domain=domain, ref=ref, current=current)
    except MaterialPricesValidationError as exc:
        raise HTTPException(status_code=422, detail="Parâmetros inválidos.") from exc
    except MaterialPricesPermissionError as exc:
        raise HTTPException(status_code=403, detail="Sem permissão para consultar preços de materiais.") from exc
    except MaterialPricesStorageError as exc:
        raise HTTPException(status_code=503, detail=_GENERIC_STORAGE_FAILURE) from exc
    except (SQLAlchemyError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=_GENERIC_STORAGE_FAILURE) from exc
    finally:
        if db is not None:
            db.close()
    response.headers["Cache-Control"] = "private, no-store"
    return result
