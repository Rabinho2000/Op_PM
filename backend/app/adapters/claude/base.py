"""Interface das ferramentas de IA expostas ao Claude (ver
docs/ARCHITECTURE_PROPOSAL.md, secção "Integração com Claude / MCP").

Regras que qualquer implementação (mock ou real) deve respeitar:
- Nenhum método aqui envia email, cria evento, altera stock/custo ou
  adjudica nada — todos devolvem uma proposta/rascunho em texto estruturado.
- O chamador (camada de serviço) é sempre responsável por registar a chamada
  em `ai_audit_log` (ver `app/audit/log.py`) antes/depois de invocar isto.
- Nenhuma implementação real pode receber a chave de API no frontend — só o
  backend a lê, a partir de `Settings.claude_api_key`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ToolResult:
    tool_name: str
    output_text: str
    structured: dict | None = None


class ClaudeAdapter(Protocol):
    def propose_visit_dates(self, *, project_context: dict, availability: dict) -> ToolResult: ...

    def check_availability(self, *, calendar_summary: dict) -> ToolResult: ...

    def analyze_travel(self, *, route_summary: dict) -> ToolResult: ...

    def draft_client_email(self, *, project_context: dict, purpose: str) -> ToolResult: ...

    def draft_material_request(self, *, project_context: dict, stock_summary: dict) -> ToolResult: ...

    def analyze_budget(self, *, cost_summary: dict) -> ToolResult: ...

    def draft_weekly_report(self, *, aggregated_data: dict) -> ToolResult: ...

    def search_documentation(self, *, query: str, index_summary: dict) -> ToolResult: ...

    def summarize_project(self, *, project_context: dict) -> ToolResult: ...
