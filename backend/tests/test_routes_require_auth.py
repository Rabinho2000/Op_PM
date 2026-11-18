"""Autenticação em todas as rotas (secção 4 de docs/ANALISE_OP_PM.md).

Hoje todas as rotas de dados exigem `get_current_user`, mas nada impedia uma
regressão: bastava um router novo sem a dependência para expor dados sem
login. Estes testes percorrem `app.routes` e falham se alguma rota (fora da
allowlist) não tiver `get_current_user` na árvore de dependências, e
confirmam em runtime que um GET sem credenciais devolve 401.
"""
from __future__ import annotations

import re

import pytest
from fastapi.routing import APIRoute

from app.config import Settings
from app.main import app
from app.security.current_user import get_current_user

# Rotas públicas de propósito: raiz e health (probe do Docker/nginx).
PUBLIC_PATHS = {"/", "/health"}
# Documentação interativa do FastAPI/Starlette — rotas que não são `APIRoute`
# e só existem com API_DOCS_ENABLED (ver `resolved_api_docs_enabled`).
DOCS_PATHS = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
ALLOWLIST = PUBLIC_PATHS | DOCS_PATHS

_PATH_PARAM = re.compile(r"{[^}]+}")


def _iter_routes(routes):
    """Todas as rotas, incluindo as de routers incluídos. Nesta versão do
    FastAPI um `include_router` pode aparecer como `_IncludedRouter` com o
    router original em `original_router` em vez de rotas já "achatadas"."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from _iter_routes(inner.routes)
        else:
            yield route


def _dependency_calls(dependant):
    for sub in dependant.dependencies:
        yield sub.call
        yield from _dependency_calls(sub)


def _all_routes() -> list:
    return list(_iter_routes(app.routes))


def _api_routes() -> list[APIRoute]:
    return [r for r in _all_routes() if isinstance(r, APIRoute)]


def test_route_discovery_finds_the_api():
    """Salvaguarda: se o percurso das rotas deixar de funcionar (mudança de
    versão do FastAPI), os testes abaixo passariam em vazio."""
    routes = _api_routes()
    assert len(routes) > 100, f"só {len(routes)} rotas encontradas — o percurso de app.routes está partido?"
    assert any(r.path == "/health" for r in routes)
    assert any(r.path.startswith("/api/projects") for r in routes)


def test_every_route_depends_on_get_current_user():
    unprotected = sorted(
        f"{','.join(sorted(r.methods or []))} {r.path}"
        for r in _api_routes()
        if r.path not in ALLOWLIST and get_current_user not in set(_dependency_calls(r.dependant))
    )
    assert not unprotected, (
        "Rotas sem `get_current_user` na árvore de dependências (e fora da allowlist "
        f"{sorted(ALLOWLIST)}):\n  " + "\n  ".join(unprotected)
    )


def test_non_api_routes_are_only_the_known_docs_routes():
    """Qualquer `Route`/`Mount` que não seja `APIRoute` (ficheiros estáticos,
    sub-aplicações, ...) escapa à verificação de dependências — por isso só
    se aceitam as rotas de documentação conhecidas."""
    extras = sorted(
        getattr(r, "path", repr(r)) for r in _all_routes() if not isinstance(r, APIRoute) and getattr(r, "path", None) not in ALLOWLIST
    )
    assert not extras, f"Rotas não-APIRoute inesperadas (sem verificação de autenticação): {extras}"


def test_public_allowlist_routes_really_exist():
    """A allowlist não pode ficar com entradas fantasma que mascarem uma
    rota nova com o mesmo caminho."""
    paths = {r.path for r in _api_routes()}
    assert PUBLIC_PATHS <= paths


def _get_routes_without_path_params() -> list[APIRoute]:
    return sorted(
        (
            r
            for r in _api_routes()
            if "GET" in (r.methods or set()) and r.path not in ALLOWLIST and not _PATH_PARAM.search(r.path)
        ),
        key=lambda r: r.path,
    )


def test_get_without_credentials_is_401_dev_mode(api_client):
    """AUTH_ENABLED=false (mecanismo de desenvolvimento): sem X-Dev-User-Email -> 401."""
    routes = _get_routes_without_path_params()
    assert len(routes) > 30
    wrong = {}
    for route in routes:
        resp = api_client.get(route.path)
        if resp.status_code != 401:
            wrong[route.path] = resp.status_code
    assert not wrong, f"GET sem cabeçalho que não devolveu 401: {wrong}"


def test_get_without_credentials_is_401_with_entra_auth(make_api_client):
    """AUTH_ENABLED=true: sem `Authorization: Bearer` -> 401, e com um Bearer
    que não é um JWT também."""
    client = make_api_client(Settings(app_env="test", auth_enabled=True, entra_validation_mode="mock"))
    wrong = {}
    for route in _get_routes_without_path_params():
        for headers in ({}, {"Authorization": "Bearer isto-nao-e-um-jwt"}):
            resp = client.get(route.path, headers=headers)
            if resp.status_code != 401:
                wrong[(route.path, bool(headers))] = resp.status_code
    assert not wrong, f"GET sem token válido que não devolveu 401: {wrong}"


def test_public_routes_stay_public(api_client):
    assert api_client.get("/health").status_code == 200
    assert api_client.get("/").status_code == 200
