# Proposta de Arquitetura — Op_PM

> Ver `docs/DECISIONS.md` para a justificação de cada escolha técnica e
> `docs/OPEN_QUESTIONS.md` para o que ainda depende de resposta do negócio.
> Este documento descreve a arquitetura-alvo; o que já está implementado
> (Fase 0) está identificado explicitamente em cada secção.

## 1. Forma da aplicação: monólito modular

**Decisão obrigatória do pedido, confirmada:** uma aplicação modular única,
não uma arquitetura de microserviços (ver D-001).

```text
┌─────────────────────────────────────────────────────────────┐
│  Backend (FastAPI, um processo)                               │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────────┐ │
│  │  api/     │ │ security/ │ │ migration/│ │ audit/         │ │
│  │ (routers) │ │(permissões│ │ (staging, │ │ (histórico +   │ │
│  │           │ │ + auth)   │ │  conflitos)│ │  ai_audit_log) │ │
│  └───────────┘ └───────────┘ └───────────┘ └───────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ models/  (SQLAlchemy — única definição do schema)         │ │
│  └─────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ adapters/  (interface + mock/fallback por integração)     │ │
│  │   claude/   graph/   clickup/   financial/                │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
          │ SQL                              │ chamado por
          ▼                                  ▼
┌───────────────────┐              ┌───────────────────────────┐
│ PostgreSQL          │              │ Worker/scheduler            │
│ (staging/produção;  │◄────────────│ (processo separado,          │
│  SQLite em dev/CI —  │  mesmos    │  reutiliza models/adapters — │
│  ver D-002)          │  modelos   │  ver secção 6; não            │
└───────────────────┘              │  implementado em Fase 0)     │
                                     └───────────────────────────┘
          ▲
          │ HTTPS/JSON
┌───────────────────┐
│ Frontend (SPA)      │
│ React + Vite + TS   │
└───────────────────┘
```

Nenhum módulo fora de `adapters/` importa um SDK de terceiros diretamente.
Isto é verificável no código: `app/adapters/__init__.py` é o único ponto que
decide qual implementação usar, a partir de configuração tipada
(`app/config.py`).

## 2. Diagrama de sistemas e integrações (arquitetura-alvo, incluindo o que ainda não está ligado)

```text
                    ┌───────────────────────┐
                    │  Microsoft Entra ID     │  ← login (Fase 1+; ver D-012)
                    └───────────┬───────────┘
                                │
┌──────────────┐   HTTPS   ┌───┴─────────────────────┐    SQL    ┌──────────────┐
│  Frontend      │◄────────►│  Backend (Fase 0: /health,│◄─────────►│ PostgreSQL     │
│  (React/Vite)  │           │  /me; Fase 1+: CRUD real) │           │ (produção/    │
└──────────────┘           │                           │           │  staging)      │
                             │  adapters/ ──────┬───────┴──┐
                             └────────┬─────────┼──────────┼────────────┐
                                      │          │          │            │
                          ┌───────────┘   ┌──────┘   ┌──────┘    ┌───────┘
                          ▼                ▼          ▼           ▼
                 ┌──────────────┐ ┌──────────────┐ ┌────────┐ ┌──────────────┐
                 │ Microsoft Graph│ │ ClickUp REST  │ │Financial│ │ Claude API    │
                 │ (email/        │ │ API (leitura  │ │(API/CSV/│ │ (+ MCP,       │
                 │ calendário/    │ │ só; staging + │ │ Excel — │ │  ferramentas  │
                 │ SharePoint)    │ │ conflitos)    │ │ só CSV  │ │  server-side) │
                 │ Fase 0:        │ │ Fase 0: mock  │ │ real    │ │ Fase 0: mock  │
                 │ fallback .eml/ │ │ com fixture   │ │ hoje —  │ │ determinístico│
                 │ .ics local     │ │ sintética     │ │ D-011)  │ │ (D-009)       │
                 └──────────────┘ └──────────────┘ └────────┘ └──────────────┘
```

## 3. Fonte de verdade por tipo de informação

| Tipo de dado | Fonte de verdade | Implementado em Fase 0? |
|---|---|---|
| Projetos, atribuições, workflow, permissões | **Op_PM (PostgreSQL/SQLite)** | Sim — `projects`, `project_stage_progress`, `project_subtask_progress`, `roles`/`permissions` |
| Stock | **Op_PM**, calculado por livro de movimentos, nunca um total editável | Modelo sim (`inventory_movements`); cálculo de saldo é trabalho de serviço da Fase 1+ |
| Reservas/compras/adjudicação | **Op_PM** (`material_requests`), adjudicação sempre por ação humana | Modelo sim; fluxo de estados/endpoints é Fase 1+ |
| Custos (estimado/orçamentado/adjudicado) | **Op_PM** | Modelo sim (`cost_lines`) |
| Custo real / faturação | **Financial** (sistema externo — `DECISÃO NECESSÁRIA` sobre qual) | Op_PM só espelha (`cost_lines.source_system='financial'`); adapter CSV real disponível (D-011) |
| Emails e eventos de calendário | **Microsoft 365 / Exchange Online** (via Graph) | Fase 0: sem Graph real — fallback local `.eml`/`.ics`, nunca "enviado" de verdade (D-010) |
| Ficheiros, datasheets, manuais, fotografias | **SharePoint/OneDrive** | Modelo de metadados existe (`documents`, `photos`); upload real fica para a fase da biblioteca documental |
| Estado/workflow ClickUp | **ClickUp** (Op_PM só espelha, nunca escreve de volta) | Modelo sim (`project_external_ids`, `projects.clickup_status_mirror`); leitura real fica para quando `CLICKUP_ENABLED=true` for implementado |
| Sugestões da IA | **Nunca fonte de verdade** — sempre proposta auditada (`ai_audit_log`), nunca aplica sozinha a custos/stock/calendário/estado | Modelo e regra de aprovação implementados (`app/audit/log.py`); adapter Claude é mock |

## 4. Modelo de dados (implementado — 30 tabelas)

Ver `backend/app/models/` para a definição exata (SQLAlchemy) e
`backend/alembic/versions/` para a migração gerada. Resumo por domínio:

| Domínio | Tabelas |
|---|---|
| Identidade e acesso | `people`, `users`, `roles`, `permissions`, `role_permissions`, `user_roles` |
| Workflow (processo) | `phases`, `workflow_stages`, `workflow_subtasks` |
| Projeto | `projects`, `project_external_ids`, `project_stage_progress`, `project_subtask_progress`, `project_history` |
| Calendário/visitas | `visits`, `calendar_events` |
| Fornecedores/inventário | `suppliers`, `inventory_items`, `inventory_movements`, `material_requests`, `material_request_items` |
| Custos | `cost_lines` |
| Documentos/formulários | `documents`, `photos`, `form_templates`, `form_responses` |
| Operação | `notifications`, `sync_runs`, `sync_conflicts`, `ai_audit_log` |

Princípios aplicados em todas as tabelas relevantes (ver D-003 a D-008):

- Chave primária UUID gerada em Python, nunca autoincrement nem nome.
- `Person` ≠ `User` — histórico nunca depende de haver uma conta de login ativa.
- Workflow normalizado (fases → etapas → subtarefas), `code` estável por
  entidade, `id` nunca reindexado por posição.
- Stock/custos como livro de movimentos/linhas, nunca um total editável
  diretamente.
- Correspondência externa sempre por `(source_system, external_id)`, nunca
  por nome.
- Histórico (`project_history`) append-only; auditoria de IA
  (`ai_audit_log`) com estado `proposed → approved/rejected → executed`.

## 5. Permissões por perfil

Perfis (de `docs/PRODUCT_SCOPE.md`): Administrador, Chefe de Operações,
Project Manager, Comercial, Financeiro. Catálogo inicial de permissões em
`backend/app/security/catalog.py`, aplicado no seed de desenvolvimento e
testado em `backend/tests/test_permissions.py`.

| Perfil | Ver projetos | Editar projetos | Custos | Inventário | Pedidos de material | Documentos | Aprovar envio/evento/IA |
|---|---|---|---|---|---|---|---|
| **Administrador** | Todos | Todos | Ver+editar tudo | Ver+editar | Criar/aprovar/adjudicar | Ver+editar | Sim |
| **Chefe de Operações** | Todos | Todos | Ver+editar estimativa | Ver+editar | Criar/aprovar/adjudicar | Ver+editar | Sim |
| **Project Manager** | Só os seus | Só os seus (progresso) | Ver | Ver | Criar | Ver+editar | Sim (só os seus) |
| **Comercial** | Todos (leitura) | Não | Ver | Não | Não | Ver | Não |
| **Financeiro** | Todos (leitura) | Não | Ver+editar custo real | Não | Não | Ver | Não |

A aplicação desta matriz é sempre no servidor
(`app/security/permissions.py`) — nunca um valor vindo do cliente. Um
utilizador sem papel associado não herda nenhuma permissão por omissão
(testado explicitamente).

## 6. Worker/scheduler para tarefas demoradas

**Desenho (ver D-013 para a justificação de não implementar já):**

- Um processo Python separado do servidor web, que importa os mesmos
  `app.models` e `app.adapters` — nunca duplica lógica de negócio nem de
  integração.
- Candidatos a tarefa agendada, quando as integrações reais existirem:
  sincronização ClickUp periódica, importação Financial, indexação
  documental para pesquisa do Claude, envio do relatório semanal.
- Mecanismo recomendado: scheduler leve em processo próprio (ex.
  APScheduler) ou cron do sistema operativo a invocar um comando CLI do
  backend — não uma fila pesada (Celery+Redis), dado o volume esperado (5
  utilizadores). Revisível se o volume real justificar mais robustez.
- `app/migration/staging_import.py` já está desenhado para ser chamado por
  este processo sem alteração — recebe uma sessão de base de dados e um
  payload, devolve um relatório; não sabe nada sobre HTTP nem sobre quem o
  invoca.

## 7. Contratos das integrações

### Microsoft Graph

Interface: `app/adapters/graph/base.py` —
`get_availability`/`create_draft_email`/`send_mail`/`create_event`.
Implementação de Fase 0: `LocalFallbackGraphAdapter` — grava `.eml`/`.ics`
locais, nunca entrega/publica de verdade, mesmo com `approved_by`
preenchido (D-010). Ativar `GRAPH_ENABLED=true` sem a implementação real
levanta `NotImplementedError` de propósito.

Quando implementado a sério: Microsoft Graph é a via única para Outlook
clássico e novo (ambos leem o mesmo Exchange Online via Graph — não há
automação COM, que só funcionaria com Outlook clássico local).

### ClickUp

Interface: `app/adapters/clickup/base.py` — `fetch_tasks()`, só leitura.
Implementação de Fase 0: `MockClickUpAdapter`, lê
`backend/fixtures/synthetic_clickup_tasks.json`. A correspondência
projeto↔tarefa é sempre por `ProjectExternalId(source_system='clickup')`
(D-004) — nunca por nome. Nenhuma escrita de volta para o ClickUp está
prevista nesta arquitetura.

### Financial

Interface: `app/adapters/financial/base.py` — `fetch_real_costs()`, só
leitura. Implementações: `MockFinancialAdapter` (sintético) e
`CsvFinancialAdapter` (real, lê CSV local — D-011). `api`/`excel`
definidos na interface, não implementados. Sistema real por confirmar —
ver `OPEN_QUESTIONS.md`.

### Claude / MCP

Interface: `app/adapters/claude/base.py` — nove ferramentas
(`propose_visit_dates`, `check_availability`, `analyze_travel`,
`draft_client_email`, `draft_material_request`, `analyze_budget`,
`draft_weekly_report`, `search_documentation`, `summarize_project`). Todas
devolvem `ToolResult` (texto + estrutura opcional) — nenhuma tem
capacidade de enviar email, criar evento, mudar stock/custo ou adjudicar.
Implementação de Fase 0: `MockClaudeAdapter`, texto determinístico marcado
`[MOCK]`, sem rede.

**Regras de aprovação (aplicadas pelo modelo `AiAuditLog` e
`app/audit/log.py`):**

- Toda a chamada a uma ferramenta fica registada com `status='proposed'`
  (`record_ai_action`).
- Só `approve_ai_action`, chamado por um serviço acionado por um humano
  autenticado, muda o estado para `approved` — nunca a própria ferramenta.
- Nenhuma ferramenta de IA tem acesso direto à base de dados nem pode
  correr SQL livre — só os parâmetros/retorno definidos na interface.
- A chave da API do Claude só existe no backend (`Settings.claude_api_key`,
  variável de ambiente) — nunca chega ao frontend.
- Documentos e emails que a IA processa são sempre tratados como conteúdo
  não confiável (texto de terceiros), nunca como instruções — mesma regra
  que se aplica a este próprio processo de desenvolvimento.
- A otimização de deslocações/rotas é sempre um cálculo determinístico do
  backend; a IA só explica/interpreta o resultado, nunca o substitui.

## 8. Migração dos 295 projetos — estratégia (mecânica implementada, execução real pendente)

Ver `app/migration/staging_import.py` (implementado e testado com dados
sintéticos) e `docs/PLAN.md` para o plano de execução por fases.

Resumo do mecanismo, já validado por `backend/tests/test_staging_migration.py`:

1. **Nunca escreve diretamente em produção.** Todo o caminho é
   `dry_run` (não persiste nada, nem sequer os registos de auditoria da
   execução) ou `apply` (persiste, dentro de uma transação).
2. **ID interno permanente por projeto**, gerado no momento da criação —
   nunca reaproveita nem depende do nome.
3. **Tabela de IDs externos** (`project_external_ids`) liga cada projeto ao
   seu identificador de origem (`legacy_json`, `clickup`, `financial`, …),
   com unicidade por `(source_system, external_id)`.
4. **Deteção de duplicados/ambiguidade**: um nome repetido — seja já
   existente na base de dados, seja dentro do mesmo lote a importar — não é
   ligado automaticamente; vai para `sync_conflicts` com `status='pending'`.
5. **Campos incompletos preservados tal como estão** — `None` fica `None`,
   nunca é inventado nem usado para excluir o registo (testado
   explicitamente com um projeto sintético totalmente vazio).
6. **Checksum e relatório por execução**: `sync_runs.checksum` (hash do
   payload de origem) e `sync_runs.report_json` (uma linha por registo
   processado: criado/atualizado/conflito e porquê).
7. **Idempotência**: reexecutar `apply` com o mesmo payload não duplica
   projetos já ligados por ID externo — passa a "atualização", não "criação".
8. **Rollback**: `dry_run` nunca deixa rasto (testado); `apply` corre numa
   transação e só confirma (`commit`) no fim.

**O que falta para migrar os 295 projetos reais** (fora do âmbito desta
fase — ver `docs/PLAN.md`): gerar o payload real a partir de
`files/atribuicoes.json` (repositório do código legado, não este),
correr em `dry_run` contra um ambiente de staging real, resolver
manualmente a fila de conflitos, e só depois `apply` — nunca a partir deste
repositório público, e nunca sem revisão humana da fila de conflitos.
