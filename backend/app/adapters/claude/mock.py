"""Implementação mock — nunca faz nenhuma chamada de rede. Devolve texto
determinístico e claramente marcado como sintético, para que seja impossível
confundir com uma resposta real durante testes/demonstrações."""
from __future__ import annotations

from app.adapters.claude.base import ToolResult

_TAG = "[MOCK — sem chamada real ao Claude]"


class MockClaudeAdapter:
    def propose_visit_dates(self, *, project_context: dict, availability: dict) -> ToolResult:
        return ToolResult(
            "propose_visit_dates",
            f"{_TAG} Datas sugeridas (exemplo): próximas 2 terças-feiras úteis dentro da disponibilidade fornecida.",
            {"suggested_dates": []},
        )

    def check_availability(self, *, calendar_summary: dict) -> ToolResult:
        return ToolResult(f"{_TAG}", f"{_TAG} Disponibilidade agregada recebida com {len(calendar_summary)} entradas.")

    def analyze_travel(self, *, route_summary: dict) -> ToolResult:
        return ToolResult("analyze_travel", f"{_TAG} Explicação de deslocações com base num cálculo determinístico já feito pelo backend.")

    def draft_client_email(self, *, project_context: dict, purpose: str) -> ToolResult:
        subject = f"[RASCUNHO] {purpose} — {project_context.get('name', 'projeto')}"
        body = f"{_TAG}\n\nExmo(a) Cliente,\n\n(rascunho de exemplo para: {purpose})\n\nCumprimentos,\nEquipa Solcor"
        return ToolResult("draft_client_email", body, {"subject": subject})

    def draft_material_request(self, *, project_context: dict, stock_summary: dict) -> ToolResult:
        return ToolResult("draft_material_request", f"{_TAG} Rascunho de pedido de material gerado a partir do stock fornecido.")

    def analyze_budget(self, *, cost_summary: dict) -> ToolResult:
        return ToolResult("analyze_budget", f"{_TAG} Análise textual do orçamento — valores permanecem os calculados pelo backend.")

    def draft_weekly_report(self, *, aggregated_data: dict) -> ToolResult:
        return ToolResult("draft_weekly_report", f"{_TAG} Rascunho de relatório semanal com base nos dados agregados fornecidos.")

    def search_documentation(self, *, query: str, index_summary: dict) -> ToolResult:
        return ToolResult("search_documentation", f"{_TAG} Nenhum índice documental real disponível nesta fase (query: {query!r}).")

    def summarize_project(self, *, project_context: dict) -> ToolResult:
        return ToolResult("summarize_project", f"{_TAG} Resumo de exemplo do projeto {project_context.get('name', '(sem nome)')}.")
