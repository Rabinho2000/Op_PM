"""Adaptadores de integração.

- `graph_mail`: envio REAL do relatório semanal por Microsoft Graph, usado
  diretamente por `app.services.client_reports` quando `GRAPH_ENABLED=true`
  (sem a flag, o serviço grava um `.eml` na pasta `outbox`).
- `clickup`: interface (`ClickUpAdapter`) e mock de leitura com fixture
  sintética. Ponto de partida da integração ClickUp real, que está adiada
  (não cancelada): ainda não é chamado pela aplicação.
- `financial`: leitor de CSV exportado do Financial (`CsvFinancialAdapter`),
  ainda não ligado à aplicação.

Não há fábrica nem seleção por flag: `CLICKUP_ENABLED`, `FINANCIAL_ENABLED` e
`CLAUDE_ENABLED` são recusadas por `app.config.Settings` enquanto não existir
a implementação real correspondente.
"""
