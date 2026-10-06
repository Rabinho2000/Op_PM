"""Adaptador Microsoft Graph para envio de relatórios.

As credenciais são sempre lidas de ficheiros locais configurados por *_FILE;
este módulo nunca faz fallback para valores de ambiente nem envia em testes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib import request

from app.config import Settings
from app.services.client_reports import GraphSenderUnavailable, ReportSender


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
        return Path(path).read_text(encoding="utf-8").strip()

    def _token(self) -> str:
        payload = json.dumps({
            "client_id": self.settings.graph_client_id,
            "client_secret": self._secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }).encode()
        req = request.Request(
            f"https://login.microsoftonline.com/{self.settings.graph_tenant_id}/oauth2/v2.0/token",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self._transport(req, timeout=20) as response:
            data = json.loads(response.read())
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
            f"https://graph.microsoft.com/v1.0/users/{from_email}/sendMail",
            data=payload,
            headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"},
            method="POST",
        )
        with self._transport(req, timeout=20) as response:
            response.read()
        return f"graph:{from_email}"


def graph_sender(settings: Settings) -> ReportSender:
    return GraphMailSender(settings)
