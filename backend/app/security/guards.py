"""Guardas de autorização para as rotas.

- `require_permission(Perm.X, ...)`: dependência FastAPI que devolve o
  `AuthContext` ou levanta `PermissionDenied` (substitui os `if not
  ctx.has_permission(...): raise HTTPException(403)` e os `_require_*` locais);
- `permission_denied_message("...")`: dependência que fixa o texto do 403 de
  uma rota cujo serviço levanta `PermissionDenied` (substitui os
  `try/except PermissionDenied → HTTPException(403)`);
- `permission_denied_handler`: o handler registado uma vez em `app.main`;
  devolve 403 com `{"detail": ...}` — o mesmo corpo que o frontend já mostra.

Ordem de precedência do texto: `exc.detail` (fixado por `require_permission`
ou por quem levanta) > mensagem da rota > `Permissão em falta: <código>`.
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from app.security.current_user import get_auth_context
from app.security.perm import Perm
from app.security.permissions import AuthContext, PermissionDenied

_STATE_KEY = "permission_denied_message"


def _compose(message: str, exc: PermissionDenied, with_reason: bool) -> str:
    return f"{message}: {exc}" if with_reason else message


def require_permission(
    *perms: Perm, detail: str | None = None, with_reason: bool = False
) -> Callable[..., AuthContext]:
    """Dependência: basta uma das permissões indicadas. Devolve o `AuthContext`,
    por isso usa-se no lugar de `Depends(get_auth_context)`::

        ctx: AuthContext = Depends(require_permission(Perm.MAP_VIEW, detail="Sem permissão para ver o mapa."))

    `detail` fixa o texto do 403; com `with_reason=True` acrescenta-lhe
    `: Permissão em falta: <código>` (formato antigo de algumas rotas).
    """
    if not perms:
        raise ValueError("require_permission precisa de pelo menos uma permissão.")
    code = str(perms[0]) if len(perms) == 1 else "|".join(str(p) for p in perms)

    def dependency(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if not any(ctx.has_permission(perm) for perm in perms):
            exc = PermissionDenied(code)
            if detail is not None:
                exc.detail = _compose(detail, exc, with_reason)
            raise exc
        return ctx

    return dependency


def permission_denied_message(message: str, *, with_reason: bool = False) -> Callable[..., None]:
    """Dependência que fixa o texto do 403 se o serviço chamado pela rota
    levantar `PermissionDenied` sem `detail`."""

    def dependency(request: Request) -> None:
        setattr(request.state, _STATE_KEY, (message, with_reason))

    return dependency


async def permission_denied_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, PermissionDenied)
    detail = exc.detail
    if detail is None:
        route_message: tuple[str, bool] | None = getattr(request.state, _STATE_KEY, None)
        if route_message is None:
            detail = str(exc)
        else:
            message, with_reason = route_message
            detail = _compose(message, exc, with_reason)
    return JSONResponse(status_code=403, content={"detail": detail})
