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
| Migração em staging | `import_batches`, `staging_project_records` |
| Operação | `notifications`, `ai_audit_log` |

Princípios aplicados em todas as tabelas relevantes (ver D-003 a D-008, D-017 a D-020):

- Chave primária UUID gerada em Python, nunca autoincrement nem nome.
- `Person` ≠ `User` — histórico nunca depende de haver uma conta de login ativa.
- Workflow normalizado (fases → etapas → subtarefas), `code` estável por
  entidade, `id` nunca reindexado por posição.
- Stock como livro de movimentos, nunca um total editável diretamente.
- Valores monetários (`cost_lines.amount`, `material_request_items.unit_price`)
  em `Numeric(12, 2)`/`Decimal`, nunca `Float` — evita erro de arredondamento
  binário (D-018).
- Correspondência externa sempre por `(source_system, external_id)`, nunca
  por nome.
- Histórico (`project_history`) append-only; auditoria de IA
  (`ai_audit_log`) com estado `proposed → approved/rejected → executed`.
- Nenhuma migração escreve diretamente em `projects` — passa sempre por
  `import_batches`/`staging_project_records` e uma promoção explícita
  (D-017; ver secção 8).

## 5. Fonte de verdade por campo — detalhe (`Project`)

Complementa a secção 3 (fonte de verdade por tipo de informação) com o
detalhe campo a campo pedido: cada campo relevante do `Project`, de onde
vem, e quem tem autoridade para o alterar depois da importação inicial.

| Campo (`Project`) | Fonte de verdade | Notas |
|---|---|---|
| `name` | **Op_PM** | Editável na plataforma depois da importação; nunca é chave de correspondência (D-004). |
| `client_contact`, `client_email` | **Op_PM** | Importados do campo legado `contact`/`email`; editáveis na plataforma. |
| `lat`, `lon` | **Op_PM** | Importados de `coords`; sem geocoding automático nesta fase (ao contrário do `sync_locations.py` legado, que consultava Nominatim — não replicado aqui). |
| `power_kwp` | **Op_PM** (extração automática) | Extraído por regex de `power_raw` (ex. `"10,50 kWp"` → `10.5`); `None` se não for possível extrair — nunca inventado. |
| `power_raw` | **Op_PM** (cópia verbatim do legado) | Preserva sempre o texto original, mesmo quando `power_kwp` não conseguiu ser extraído. |
| `pm_person_id` | **Op_PM** | Resolvido por nome exato normalizado contra `people.display_name` no momento da promoção; fica `None` se ambíguo/inexistente — nunca adivinha (`_resolve_pm_person`). |
| `start_date` | **Op_PM** (extração automática) | Extraído de `startDate` (ISO-8601); `None` se o formato não for reconhecido — o texto original fica preservado em `StagingProjectRecord.raw_record_json`. |
| `clickup_status_mirror` | **ClickUp** | Op_PM só espelha o valor lido; nunca escreve de volta para o ClickUp. |
| `role`, `equipment_notes`, `injection_notes`, `om_notes`, `commercial_assumptions` | **Op_PM** (cópia verbatim do legado) | Campos `role`/`equip`/`injecao`/`om`/`assum` do IDF legado; texto livre, sem validação de formato nesta fase. |
| `upac_registration`, `m2m_card` | **Op_PM** (cópia verbatim do legado) | Campos `upacRegisto`/`m2mCard`; não confirmado se há um sistema externo de licenciamento que deva ser a fonte de verdade real — `DECISÃO NECESSÁRIA`, ver `OPEN_QUESTIONS.md`. |
| `upac_connection_date_raw`, `award_year_raw` | **Op_PM** (cópia verbatim do legado) | Guardados como texto (não `Date`/`Integer`) porque o formato real destes campos no export legado não foi confirmado nesta fase — ver docs/DECISIONS.md D-019. |
| `is_active` | **Op_PM** | `False` só por decisão humana (edição direta) ou por `rollback_promotion` a desfazer uma criação (D-017). |
| `cost_lines` (`cost_type='real'`) | **Financial** | Op_PM só espelha (`source_system='financial'`); nunca inventa um custo real. |
| `cost_lines` (`cost_type` estimado/orçamentado/adjudicado) | **Op_PM** | Calculado/editado na plataforma. |
| `calendar_events.graph_event_id`, `email_drafts` enviados | **Microsoft Graph / Exchange Online** | Só preenchido depois de uma publicação/envio real (Fase 3+); nesta fase, o fallback local nunca publica nada real (D-010). |
| `documents.sharepoint_item_id` | **SharePoint/OneDrive** | O ficheiro em si vive lá; Op_PM só guarda metadados. |

## 6. Permissões por perfil

Perfis (de `docs/PRODUCT_SCOPE.md`): Administrador, Chefe de Operações,
Project Manager, Comercial, Financeiro. Catálogo inicial de permissões em
`backend/app/security/catalog.py`, aplicado no seed de desenvolvimento e
testado em `backend/tests/test_permissions.py`.

| Perfil | Ver projetos | Editar projetos | Custos | Inventário | Pedidos de material | Documentos | Migração (ver/resolver) | Aprovar envio/evento/IA |
|---|---|---|---|---|---|---|---|---|
| **Administrador** | Todos | Todos | Ver+editar tudo | Ver+editar | Criar/aprovar/adjudicar | Ver+editar | Sim/Sim | Sim |
| **Chefe de Operações** | Todos | Todos | Ver+editar estimativa | Ver+editar | Criar/aprovar/adjudicar | Ver+editar | Sim/Sim | Sim |
| **Project Manager** | Só os seus | Só os seus (progresso) | Ver | Ver | Criar | Ver+editar | Não/Não | Sim (só os seus) |
| **Comercial** | Todos (leitura) | Não | Ver | Não | Não | Ver | Não/Não | Não |
| **Financeiro** | Todos (leitura) | Não | Ver+editar custo real | Não | Não | Ver | Não/Não | Não |

A aplicação desta matriz é sempre no servidor
(`app/security/permissions.py`) — nunca um valor vindo do cliente. Um
utilizador sem papel associado não herda nenhuma permissão por omissão
(testado explicitamente). A coluna "Migração" (`migration.view`/
`migration.resolve`, D-026) cobre lotes de importação, registos de
staging, e a fila de reconciliação de PM — reservada a Administrador e
Chefe de Operações por omissão; ver `docs/OPEN_QUESTIONS.md` pergunta 17
para a confirmação de negócio pendente.

## 7. Worker/scheduler para tarefas demoradas

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
- `app/migration/staging.py` já está desenhado para ser chamado por este
  processo sem alteração — `ingest_export`/`resolve_conflict`/
  `promote_staging_record`/`rollback_promotion` recebem uma sessão de base
  de dados e dados simples; não sabem nada sobre HTTP nem sobre quem os
  invoca.

## 8. Contratos das integrações

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

## 9. Migração dos 295 projetos — estratégia (mecânica implementada, execução real pendente)

Ver `app/migration/staging.py` (implementado e testado com dados
sintéticos — `backend/tests/test_staging_persistence.py`) e `docs/PLAN.md`
para o plano de execução por fases. Desenho revisto na revisão de
hardening da Fase 0 (D-017): substitui o `dry_run`/`apply` de uma única
função por três etapas persistentes e distintas.

```text
1) ingest_export(payload)                2) resolve_conflict(...)         3) promote_staging_record(...)
   ─────────────────────────                ──────────────────────           ──────────────────────────
   Lê o export externo.                     Só para registos em              Só isto escreve em `projects`.
   Cria 1 ImportBatch +                     'conflict'. Decide              Cria/atualiza o Project,
   N StagingProjectRecord.                  create_new / link_existing /    ProjectExternalId, e gera
   NUNCA toca em `projects`.                skip. Nunca decide sozinho.     project_history por campo.
   Sempre persistente (sem "dry run" —
   nada aqui pode corromper dados
   canónicos).                                                              rollback_promotion(...)
                                                                             desfaz uma promoção — nunca
                                                                             apaga histórico, só acrescenta
                                                                             entradas que revertem os valores.
```

Garantias, todas testadas:

1. **Nunca escreve diretamente em `projects`.** Só `promote_staging_record`
   o faz, e só para um registo já em `status='ready_to_promote'` (nunca a
   partir de `conflict` ou `pending_review`).
2. **ID interno permanente por projeto**, gerado no momento da criação —
   nunca reaproveita nem depende do nome.
3. **Tabela de IDs externos** (`project_external_ids`) liga cada projeto ao
   seu identificador de origem, com unicidade por `(source_system, external_id)`.
4. **Deteção de duplicados/ambiguidade**: um nome repetido — já existente
   na base de dados, ou dentro do mesmo lote — nunca é ligado
   automaticamente; fica em `staging_project_records` com
   `status='conflict'`, para `resolve_conflict` explícito. **Âmbito
   conhecido:** não deteta duplicados entre lotes diferentes ainda não
   promovidos (só dentro do mesmo lote e contra `projects` já promovidos) —
   ver docs/DECISIONS.md D-017.
5. **Payload original preservado sempre**, em dois níveis: o export
   completo (`ImportBatch.raw_payload_json`) e cada registo individual
   (`StagingProjectRecord.raw_record_json`) — nunca editados depois da
   ingestão, mesmo que a normalização de campos tenha um erro.
6. **Mapeamento explícito de PM, email, contacto, coordenadas, data de
   início, estado ClickUp, e os restantes campos legados relevantes**
   (`role`, `equip`, `injecao`, `om`, `assum`, `upacRegisto`, `m2mCard`,
   `upacConnDate`, `anoAdjudicacao`) — ver a secção 5 para a fonte de
   verdade de cada um. `power` é tratado com cuidado especial: o legado
   guarda-o como texto livre (`"165,56 kWp"`), por isso há sempre extração
   numérica best-effort (`power_kwp`) e preservação do texto original
   (`power_raw`).
7. **Campos incompletos preservados tal como estão** — `None` fica `None`,
   nunca inventado nem motivo de exclusão.
8. **Checksum e contagens por lote**: `ImportBatch.checksum` (hash do
   payload de origem) e `records_seen`/`records_ready`/`records_conflicted`.
9. **Idempotência**: reingerir o mesmo payload não duplica um projeto já
   ligado por ID externo — o registo de staging nasce já `ready_to_promote`
   com `resolved_action='update_existing'`.
10. **Rollback com auditoria, não apagamento**: reverter uma promoção que
    criou um projeto inativa-o (`is_active=False`, nunca `DELETE`);
    reverter uma promoção que atualizou um projeto existente reaplica o
    valor anterior de cada campo alterado, com uma nova entrada de
    `project_history` por campo — nunca apaga as entradas anteriores.

**O que falta para migrar os 295 projetos reais** (fora do âmbito desta
fase — ver `docs/PLAN.md`): gerar o payload real a partir de
`files/atribuicoes.json` (repositório do código legado, não este),
`ingest_export` contra um ambiente de staging real, resolver manualmente a
fila de conflitos, e só depois `promote_staging_record` registo a registo —
nunca a partir deste repositório público, e nunca sem revisão humana da
fila de conflitos.
