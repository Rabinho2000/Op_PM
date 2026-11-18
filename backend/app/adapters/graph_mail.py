"""Adaptador Microsoft Graph para envio de relatórios.

As credenciais são sempre lidas de ficheiros locais configurados por *_FILE;
este módulo nunca faz fallback para valores de ambiente. Só envia com
`GRAPH_ENABLED=true`; os testes injetam `transport` e nunca tocam na rede.

Fluxo client-credentials: POST form-urlencoded ao endpoint de tokens do Entra
(o endpoint rejeita JSON) e depois POST JSON a /users/{from}/sendMail.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from app.config import Settings
from app.services.client_reports import GraphSenderUnavailable, ReportSender

_TIMEOUT_SECONDS = 20
_MAX_ERROR_DETAIL = 300


class GraphDeliveryError(RuntimeError):
    """O Entra ou o Graph recusaram o pedido; a mensagem traz o código devolvido."""


def _error_detail(exc: error.HTTPError) -> str:
    """Código/descrição do erro devolvido pelo Entra/Graph — nunca o pedido."""
    try:
        body = json.loads(exc.read() or b"{}")
    except (ValueError, OSError):
        return exc.reason if isinstance(exc.reason, str) else ""
    graph_error = body.get("error")
    if isinstance(graph_error, dict):  # Graph: {"error": {"code", "message"}}
        detail = f"{graph_error.get('code', '')}: {graph_error.get('message', '')}"
    else:  # Entra: {"error", "error_description"}
        detail = f"{graph_error or ''}: {body.get('error_description', '')}"
    return detail.strip(": ")[:_MAX_ERROR_DETAIL]


class GraphMailSender:
    """Sender Graph client-credentials, com transporte injetável para testes."""

    def __init__(self, settings: Settings, *, transport: Any | None = None):
        if not settings.graph_enabled:
            raise GraphSenderUnavailable("Microsoft Graph está desativado.")
        self.settings = settings
        self._transport = transport or request.urlopen
        self._secret = self._read_secret(settings.graph_client_secret_file)
        if not settings.graph_tenant_id or not settings.graph_client_id or not self._secret:
            raise GraphSenderUnavailable("Graph requer tenant, client ID e segredo por ficheiro.")

    @staticmethod
    def _read_secret(path: str) -> str:
        if not path:
            return ""
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise GraphSenderUnavailable("Não foi possível ler GRAPH_CLIENT_SECRET_FILE.") from exc

    def _post(self, req: request.Request, what: str) -> bytes:
        try:
            with self._transport(req, timeout=_TIMEOUT_SECONDS) as response:
                return response.read()
        except error.HTTPError as exc:
            raise GraphDeliveryError(f"{what}: HTTP {exc.code} {_error_detail(exc)}".strip()) from exc
        except error.URLError as exc:
            raise GraphDeliveryError(f"{what}: falha de rede ({exc.reason})") from exc

    def _token(self) -> str:
        payload = parse.urlencode({
            "client_id": self.settings.graph_client_id,
            "client_secret": self._secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }).encode()
        tenant = parse.quote(self.settings.graph_tenant_id, safe="")
        req = request.Request(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        data = json.loads(self._post(req, "Token Entra recusado") or b"{}")
        token = data.get("access_token")
        if not token:
            raise GraphSenderUnavailable("Microsoft Graph não devolveu access_token.")
        return token

    def __call__(self, *, from_email: str, to_emails: list[str], cc_emails: list[str], subject: str, body_html: str) -> str:
        recipients = [{"emailAddress": {"address": address}} for address in to_emails]
        recipients_cc = [{"emailAddress": {"address": address}} for address in cc_emails]
        payload = json.dumps({
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": body_html},
                "toRecipients": recipients,
                "ccRecipients": recipients_cc,
            },
            "saveToSentItems": True,
        }).encode()
        req = request.Request(
            f"https://graph.microsoft.com/v1.0/users/{parse.quote(from_email, safe='@')}/sendMail",
            data=payload,
            headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"},
            method="POST",
        )
        self._post(req, "sendMail recusado")
        return f"graph:{from_email}"


def graph_sender(settings: Settings) -> ReportSender:
    return GraphMailSender(settings)
