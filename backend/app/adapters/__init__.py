"""Fábrica de adapters de integração.

Cada integração externa (Claude, Microsoft Graph, ClickUp, Financial) é
acedida só através da interface definida em `<integração>/base.py`. O resto
da aplicação nunca importa um SDK de terceiros diretamente — só fala com a
interface, o que torna trivial trocar mock por implementação real mais
tarde, e torna impossível uma chamada real "escapar" por acidente enquanto
a flag correspondente estiver a `false`.

Nesta fase (Fase 0) não existe nenhuma implementação real — só mocks e o
fallback local .eml/.ics do Graph. Ativar uma integração real é trabalho de
uma fase futura, implementado atrás da mesma interface.
"""
from __future__ import annotations

from app.adapters.claude.base import ClaudeAdapter
from app.adapters.claude.mock import MockClaudeAdapter
from app.adapters.clickup.base import ClickUpAdapter
from app.adapters.clickup.mock import MockClickUpAdapter
from app.adapters.financial.base import FinancialAdapter
from app.adapters.financial.csv_adapter import CsvFinancialAdapter
from app.adapters.financial.mock import MockFinancialAdapter
from app.adapters.graph.base import GraphAdapter
from app.adapters.graph.local_fallback import LocalFallbackGraphAdapter
from app.config import Settings


def get_claude_adapter(settings: Settings) -> ClaudeAdapter:
    if settings.claude_enabled:
        raise NotImplementedError(
            "Integração real com a API do Claude ainda não está implementada "
            "(Fase 0 é só fundação). CLAUDE_ENABLED deve ficar 'false' até essa fase."
        )
    return MockClaudeAdapter()


def get_graph_adapter(settings: Settings) -> GraphAdapter:
    if settings.graph_enabled:
        raise NotImplementedError(
            "Integração real com o Microsoft Graph ainda não está implementada. "
            "GRAPH_ENABLED deve ficar 'false' até essa fase."
        )
    return LocalFallbackGraphAdapter(output_dir=settings.graph_fallback_dir)


def get_clickup_adapter(settings: Settings) -> ClickUpAdapter:
    if settings.clickup_enabled:
        raise NotImplementedError(
            "Sincronização real com o ClickUp ainda não está implementada. "
            "CLICKUP_ENABLED deve ficar 'false' até essa fase."
        )
    return MockClickUpAdapter()


def get_financial_adapter(settings: Settings) -> FinancialAdapter:
    if settings.financial_mode == "csv" and settings.financial_csv_path:
        return CsvFinancialAdapter(csv_path=settings.financial_csv_path)
    if settings.financial_mode in ("api", "excel"):
        raise NotImplementedError(
            f"Modo Financial '{settings.financial_mode}' ainda não está implementado nesta fase."
        )
    return MockFinancialAdapter()
