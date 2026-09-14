"""Fallback local, sem qualquer chamada de rede: grava rascunhos de email
como ficheiros `.eml` e eventos como ficheiros `.ics` em disco. Usado
sempre que `GRAPH_ENABLED=false` (o valor por omissão) — incluindo para
`send_mail`/`create_event`, que aqui **nunca enviam nem publicam nada
real**, apenas escrevem o ficheiro correspondente e devolvem o caminho.

Isto cumpre literalmente o pedido: "Preparar fallback para criar rascunho de
email, ficheiro .eml ou convite .ics quando Graph ainda não estiver
configurado" — e também a regra de segurança "não implementar envio real de
emails nem criação real de eventos nesta fase": mesmo o caminho "send"/
"create" deste adapter é, por construção, só uma escrita de ficheiro local.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from app.adapters.graph.base import DraftEmailResult, DraftEventResult


def _ics_datetime(iso: str) -> str:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class LocalFallbackGraphAdapter:
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_availability(self, *, person_emails: list[str], start: str, end: str) -> dict:
        # Sem ligação real ao calendário: devolve "sem informação" em vez de
        # inventar disponibilidade — nunca simular dados reais de calendário.
        return {email: "desconhecido_sem_graph" for email in person_emails}

    def _write_eml(self, *, to: str, subject: str, body: str, cc: str | None, folder: str) -> Path:
        msg = EmailMessage()
        msg["To"] = to
        if cc:
            msg["Cc"] = cc
        msg["Subject"] = subject
        msg["X-Op-PM-Fallback"] = "true — rascunho local, nao enviado"
        msg.set_content(body)

        target_dir = self.output_dir / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / f"{uuid.uuid4()}.eml"
        file_path.write_bytes(bytes(msg))
        return file_path

    def create_draft_email(self, *, to: str, subject: str, body: str, cc: str | None = None) -> DraftEmailResult:
        path = self._write_eml(to=to, subject=subject, body=body, cc=cc, folder="email_drafts")
        return DraftEmailResult(reference=str(path), was_sent=False)

    def send_mail(self, *, to: str, subject: str, body: str, approved_by: str) -> DraftEmailResult:
        if not approved_by:
            raise PermissionError("send_mail exige approved_by (aprovação humana registada).")
        # Mesmo aprovado, este adapter de fallback nunca entrega email real —
        # só grava o .eml numa pasta "approved" para indicar a intenção.
        path = self._write_eml(to=to, subject=subject, body=body, cc=None, folder="email_approved_not_sent")
        return DraftEmailResult(reference=str(path), was_sent=False)

    def create_event(
        self, *, title: str, starts_at: str, ends_at: str, attendees: list[str], approved_by: str
    ) -> DraftEventResult:
        if not approved_by:
            raise PermissionError("create_event exige approved_by (aprovação humana registada).")
        uid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Op_PM//fase0-fallback//PT",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now}",
            f"DTSTART:{_ics_datetime(starts_at)}",
            f"DTEND:{_ics_datetime(ends_at)}",
            f"SUMMARY:{title}",
        ]
        for attendee in attendees:
            lines.append(f"ATTENDEE:mailto:{attendee}")
        lines += ["END:VEVENT", "END:VCALENDAR"]

        target_dir = self.output_dir / "calendar_events_not_published"
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / f"{uid}.ics"
        file_path.write_text("\r\n".join(lines), encoding="utf-8")
        return DraftEventResult(reference=str(file_path), was_published=False)
