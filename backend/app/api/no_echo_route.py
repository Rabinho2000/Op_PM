"""Rota FastAPI que não ecoa o corpo num 422.

O 422 por defeito do FastAPI devolve `input` com o valor recebido — numa rota
com passwords (credenciais) ou dados sensíveis isso põe o segredo numa
mensagem de erro. Aqui o 422 responde sempre `{"detail": "Corpo inválido."}`.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute


class NoEchoRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except RequestValidationError:
                return JSONResponse(status_code=422, content={"detail": "Corpo inválido."})

        return handler
