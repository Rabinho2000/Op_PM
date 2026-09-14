"""Interface de calendário/email/documentos (destino real: Microsoft Graph).

Fonte de verdade: Outlook/Exchange Online e SharePoint/OneDrive — este
adapter nunca é ele próprio a fonte de verdade, só o canal de leitura e,
após aprovação humana, de escrita real. `send_mail`/`create_event` só devem
ser chamados depois de uma aprovação humana explícita registada fora deste
adapter (ver `app/audit/log.py`); nenhuma implementação deve pular esse
passo.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class DraftEmailResult:
    reference: str  # graph_message_id (real) ou caminho do ficheiro .eml (fallback)
    was_sent: bool


@dataclass
class DraftEventResult:
    reference: str  # graph_event_id (real) ou caminho do ficheiro .ics (fallback)
    was_published: bool


class GraphAdapter(Protocol):
    def get_availability(self, *, person_emails: list[str], start: str, end: str) -> dict: ...

    def create_draft_email(
        self, *, to: str, subject: str, body: str, cc: str | None = None
    ) -> DraftEmailResult:
        """Cria só o rascunho — nunca envia."""
        ...

    def send_mail(self, *, to: str, subject: str, body: str, approved_by: str) -> DraftEmailResult:
        """Só deve ser invocado depois de aprovação humana explícita."""
        ...

    def create_event(
        self, *, title: str, starts_at: str, ends_at: str, attendees: list[str], approved_by: str
    ) -> DraftEventResult:
        """Só deve ser invocado depois de aprovação humana explícita."""
        ...
