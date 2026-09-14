# Plano — Op_PM

> Ver `docs/ARCHITECTURE_PROPOSAL.md` (arquitetura, modelo de dados,
> integrações) e `docs/DECISIONS.md` (justificação de cada escolha técnica).
> Este documento cobre o roadmap por fases, a estratégia de migração, testes,
> segurança, deployment, estratégia GitHub, riscos e o MVP recomendado.

## Resumo executivo

**Fase 0 está implementada e testada** (ver "Fase 0" abaixo): fundação de
backend (FastAPI + SQLAlchemy + Alembic, 30 tabelas), frontend mínimo
(React + Vite), quatro integrações a funcionar em modo mock/fallback local
(nunca uma chamada real), mecanismo de migração em staging com fila de
conflitos (testado com dados sintéticos, nunca com os 295 projetos reais),
permissões aplicadas no servidor, e histórico/auditoria com as regras
corretas de aprovação de IA. 27 testes automatizados, todos a passar.

Nenhum dado real, segredo, ou integração real entrou neste repositório —
ver `docs/DECISIONS.md` D-015 e o `.gitignore`.

## Fase 0 — Fundação técnica (IMPLEMENTADA)

- **Objetivo:** estrutura base do backend/frontend, modelo de dados
  completo, adapters de todas as integrações em modo seguro, mecanismo de
  migração em staging, testes cobrindo as regras mais críticas.
- **Funcionalidades:** `/health`, `/me` (com utilizador de desenvolvimento —
  ver D-012), seed sintético de desenvolvimento.
- **Entidades:** as 30 tabelas listadas em `docs/ARCHITECTURE_PROPOSAL.md`
  secção 4.
- **Integrações:** Claude, Graph, ClickUp, Financial — todas mock/fallback
  local, nenhuma chamada real (ver D-009 a D-011).
- **Testes:** 27 testes (`backend/tests/`) — saúde da API, permissões,
  unicidade de IDs externos, migração em staging (dry-run, criação,
  ambiguidade, idempotência), histórico/auditoria, adapters.
- **Riscos considerados:** nenhum dado real nem segredo commitado (mitigado
  por `.gitignore` + revisão manual); SQLite em vez de PostgreSQL em
  dev/teste é uma simplificação documentada (D-002), não uma mudança de
  arquitetura-alvo.
- **Rollback:** esta fase não toca em nenhum sistema de produção — não há
  rollback a fazer, só não avançar para a Fase 1 enquanto o essencial não
  estiver revisto.
- **Critérios de conclusão (cumpridos):** `alembic upgrade head` cria o
  schema completo em SQLite limpo; `python -m app.migration.seed_dev` corre
  sem erros; `pytest -q` — 27/27 testes passam; `npm run build` do frontend
  conclui sem erros; nenhuma flag de integração real ativa por omissão.

## Fase 0 — Revisão de hardening (IMPLEMENTADA, antes da Fase 1)

Pedida explicitamente antes de iniciar a Fase 1 — nenhum item liga
integrações reais (Entra ID, Graph, ClickUp, Financial, Claude continuam
mock/fallback). Ver `docs/DECISIONS.md` D-017 a D-021 para o detalhe.

- **Objetivo:** fechar os riscos identificados na fundação da Fase 0 antes
  de expor a aplicação a autenticação real ou dados reais.
- **Funcionalidades/correções:**
  1. Bloqueio de arranque em `staging`/`production` com `AUTH_ENABLED=false`,
     `SECRET_KEY` de desenvolvimento, ou `DATABASE_URL` SQLite — mais uma
     segunda verificação independente no mecanismo de utilizador de
     desenvolvimento (D-020).
  2. Migração redesenhada: `SyncRun`/`SyncConflict` (decidiam tudo numa
     função `dry_run`/`apply`) substituídos por `ImportBatch`/
     `StagingProjectRecord`, persistentes, com `ingest_export` →
     `resolve_conflict` → `promote_staging_record` como três etapas
     distintas, e `rollback_promotion` com auditoria completa (D-017).
  3. Mapeamento expandido: PM, email, contacto, coordenadas, data de
     início, estado ClickUp, e os restantes campos legados relevantes
     (`role`, `equip`, `injecao`, `om`, `assum`, `upacRegisto`, `m2mCard`,
     `upacConnDate`, `anoAdjudicacao`, `power` com extração numérica
     best-effort a partir de texto livre) — ver ARCHITECTURE_PROPOSAL.md
     secção 5.
  4. `cost_lines.amount` e `material_request_items.unit_price`:
     `Float` → `Numeric(12, 2)`/`Decimal` (D-018).
  5. Documentação campo-a-campo da fonte de verdade do `Project`
     (ARCHITECTURE_PROPOSAL.md secção 5).
  6. Testes novos: hardening de configuração, staging persistente,
     promoção após resolução de conflito, preservação de campos legados,
     precisão monetária.
  7. CI: job PostgreSQL adicional, mantendo o job SQLite (D-021).
- **Entidades:** `import_batches`, `staging_project_records` (substituem
  `sync_runs`/`sync_conflicts`); `projects` ganha `power_raw`, `role`,
  `equipment_notes`, `injection_notes`, `om_notes`,
  `commercial_assumptions`, `upac_registration`, `m2m_card`,
  `upac_connection_date_raw`, `award_year_raw`; `project_history` ganha
  `related_staging_record_id`.
- **Integrações:** nenhuma — continuam todas mock/fallback.
- **Testes:** `test_config_hardening.py`, `test_staging_persistence.py`
  (substitui `test_staging_migration.py`), `test_monetary_precision.py`;
  suite completa a passar em SQLite e (não executável neste ambiente —
  ver D-021) desenhada para passar em PostgreSQL via CI.
- **Riscos:** ver secção "Riscos ainda existentes" no final deste
  documento.
- **Rollback:** reverter para o commit anterior a esta revisão — nenhuma
  integração real foi tocada, nenhum dado real existe ainda; o único
  efeito é no schema local (recriável via `alembic downgrade`/`upgrade`).
- **Critérios de conclusão (cumpridos):** `pytest -q` passa por completo em
  SQLite; migração de hardening testada em `upgrade`→`downgrade`→`upgrade`;
  nenhuma integração real ativada; documentos atualizados.

## Fase 0 — Revisão técnica final (IMPLEMENTADA, antes da Fase 1)

Pedida explicitamente como última revisão do commit da revisão de
hardening acima, antes de considerar a Fase 0 encerrada. Ver
`docs/DECISIONS.md` D-022/D-023.

- **Objetivo:** corrigir um bug real encontrado na revisão anterior
  (`conftest.py` mascarava o job `backend-postgres` do CI como SQLite) e
  fechar uma lacuna real de segurança de dados (promoção silenciosa de
  projeto com PM não resolvido).
- **Correções:**
  1. `tests/conftest.py` deixou de sobrescrever `DATABASE_URL`
     incondicionalmente — só gere um SQLite temporário quando a variável
     não está definida (D-022).
  2. Verificação explícita e obrigatória do dialect ligado
     (`EXPECTED_DB_DIALECT`, `pytest.exit` se divergir +
     `tests/test_database_dialect.py`) nos dois jobs de CI (D-022).
  3. Reconciliação de PM como etapa explícita antes da promoção de
     projetos — `app/migration/people_reconciliation.py`
     (`reconcile_pm_names`/`resolve_person_reconciliation`), mais o
     bloqueio `pm_unresolved` em `ingest_export`/`resolve_conflict` e a
     barreira final, não contornável, em `promote_staging_record` (D-023).
  4. Correção de três contradições documentais (`AUTH_ENABLED` no
     rollback da Fase 1, `GraphAdapter` associado à fase errada, árvore
     de dependências entre fases incompleta) — ver mais abaixo.
- **Tentativa real de validação local contra PostgreSQL:** instalado
  Python 3.12 e o pacote `pgserver` (PostgreSQL embebido, sem Docker, sem
  serviço de sistema); bloqueado por um problema confirmado do
  PostgreSQL-para-Windows com o nome de utilizador local não-ASCII deste
  computador (`FATAL: invalid byte sequence for encoding "UTF8"` no
  `initdb`, independente do diretório ou de `--locale`) — não é um
  problema do código deste repositório; documentado em D-021. A suite
  PostgreSQL fica validada pela primeira vez no GitHub Actions.
- **Entidades:** `person_reconciliation_items` (nova);
  `staging_project_records` ganha `pm_name_raw`,
  `candidate_person_ids_json`, `pm_explicitly_unassigned`.
- **Integrações:** nenhuma — continuam todas mock/fallback.
- **Testes:** `tests/test_people_reconciliation.py` (16 testes, novo);
  `tests/test_database_dialect.py` (2 testes, novo); ajuste a um teste
  pré-existente em `tests/test_staging_persistence.py` que passou a
  exercer também o bloqueio por PM. Suite completa a passar em SQLite
  (72 passed, 2 skipped — os skips são os testes de dialect quando
  `EXPECTED_DB_DIALECT` não está definido, o caso local normal).
- **Riscos:** ver "Riscos técnicos e operacionais" mais abaixo.
- **Rollback:** reverter para o commit anterior a esta revisão — nenhuma
  integração real foi tocada, nenhum dado real existe ainda.
- **Critérios de conclusão:** `pytest -q` a passar por completo em SQLite;
  migrações `upgrade`→`downgrade`→`upgrade` validadas; `npm run build` do
  frontend sem erros; contradições documentais corrigidas; job
  `backend-postgres` do CI corrigido para não poder passar silenciosamente
  contra SQLite (validação real da execução fica para o primeiro push ao
  GitHub Actions, fora do alcance desta sessão local).

## Fase 1 — Autenticação real e primeiros endpoints CRUD

- **Objetivo:** ligar Microsoft Entra ID a sério (substituir o mecanismo de
  desenvolvimento — D-012) e expor os primeiros endpoints de escrita reais
  (projetos, workflow) atrás das permissões já modeladas.
- **Entidades:** `projects`, `project_stage_progress`,
  `project_subtask_progress`, `project_history` (endpoints de leitura e
  escrita, sempre gerando entrada de histórico).
- **Integrações:** Entra ID — substitui a validação `NotImplementedError`
  atual (D-012) por validação real de token OIDC, e só depois define
  `AUTH_ENABLED=true`; `GraphAdapter` continua em fallback local até à
  Fase 3, que é quem o liga a sério (ver "Dependências entre fases").
- **Testes:** testes de integração da API (não só de serviço), teste de que
  um token inválido/expirado é rejeitado, teste de que toda a escrita gera
  histórico.
- **Riscos:** depende de `DECISÃO NECESSÁRIA` sobre o tenant M365 (ver
  `OPEN_QUESTIONS.md`) — sem isso, esta fase fica bloqueada na parte de
  autenticação (mas os endpoints CRUD podem avançar sob o mecanismo de
  desenvolvimento entretanto).
- **Rollback:** em `local`/`test`, manter `AUTH_ENABLED=false` (mecanismo de
  desenvolvimento) como via de recuperação enquanto a integração Entra ID
  não estiver pronta. **Nunca em `staging`/`production`** — aí
  `AUTH_ENABLED=false` está bloqueado estruturalmente pela validação de
  arranque (D-020); a app simplesmente não arranca com essa combinação. Na
  prática isto significa que só se promove esta fase para staging depois
  de a integração Entra ID real estar a funcionar — não há um "voltar
  atrás" para staging/produção sem autenticação real, por desenho.
- **Critérios de conclusão:** um utilizador real autentica-se via Entra ID;
  `/me` reflete os seus papéis reais; criar/editar um projeto sintético via
  API gera uma entrada de `project_history` correta.

## Fase 2 — Migração real dos 295 projetos (staging → produção)

- **Objetivo:** migrar os dados reais do repositório do código legado
  (`files/atribuicoes.json`, fora deste repositório público) para a base de
  dados de staging, resolver a fila de conflitos manualmente (incluindo a
  fila de reconciliação de PMs), e só depois promover para produção.
- **Passo 0, obrigatório, antes de qualquer `ingest_export` real:**
  `app.migration.people_reconciliation.reconcile_pm_names` sobre o payload
  real, para que a fila `person_reconciliation_items` já esteja parcialmente
  resolvida quando a ingestão começar — reduz o número de projetos que
  ficam bloqueados por `pm_unresolved` logo à primeira (ver D-023).
- **Entidades:** todas as tocadas por `app/migration/staging.py` e
  `app/migration/people_reconciliation.py` — `projects`,
  `project_external_ids`, `import_batches`, `staging_project_records`,
  `person_reconciliation_items`.
- **Integrações:** nenhuma nova — reutiliza `reconcile_pm_names`/
  `ingest_export`/`resolve_conflict`/`promote_staging_record`/
  `retry_pm_resolution` já implementados e testados.
- **Testes:** contagem de projetos migrados == 295 (ou o número real no
  momento da migração); amostragem de campos antes/depois; nenhum registo
  `staging_project_records.status='conflict'` (nome ou PM) fica sem revisão
  antes de qualquer promoção; nenhum `person_reconciliation_items.status='pending'`
  fica esquecido sem decisão.
- **Riscos:** divergências já documentadas entre `atribuicoes.json` e
  exports de PM no repositório legado precisam de resolução manual antes
  desta fase — ver a análise desse repositório. Os 8 PMs históricos do
  legado (D-003) provavelmente geram vários itens de reconciliação
  logo na primeira ingestão real — orçamentar tempo de revisão humana para
  isso, não assumir que a maioria resolve automaticamente.
- **Rollback:** `ingest_export` primeiro sempre (nunca toca em `projects`);
  cada `promote_staging_record` é revertível individualmente via
  `rollback_promotion`, com auditoria completa; backup da base de dados
  antes de promover o lote (ver "Plano de backups" abaixo).
- **Critérios de conclusão:** todos os projetos reais migrados ou
  explicitamente na fila de conflitos com decisão registada; nenhum campo
  incompleto foi inventado; checksum e relatório da execução guardados.

## Fase 3 — Página inicial, planeamento e visitas (Microsoft Graph real)

- **Objetivo:** ligar `GraphAdapter` a sério (substituir o fallback local);
  dashboard inicial; fluxo de visitas com proposta de data, rascunho de
  email/evento, aprovação humana antes de envio/marcação real.
- **Entidades:** `visits`, `calendar_events` (endpoints reais).
- **Integrações:** Microsoft Graph real (`GRAPH_ENABLED=true`).
- **Testes:** teste de que nenhum email/evento é criado sem aprovação
  explícita; teste de compatibilidade com Outlook clássico e novo (ambos
  via Graph/Exchange Online — ver `ARCHITECTURE_PROPOSAL.md` secção 8).
- **Riscos:** limites de taxa do Graph API; `DECISÃO NECESSÁRIA` sobre
  calendários/equipas a considerar (ver `OPEN_QUESTIONS.md`).
- **Rollback:** manter `GRAPH_ENABLED=false` (fallback local) como via de
  recuperação até a integração estar validada.
- **Critérios de conclusão:** uma visita sintética percorre proposta →
  aprovação → evento/email reais visíveis no Outlook (clássico e novo).

## Fase 4 — ClickUp real

- **Objetivo:** ligar `ClickUpAdapter` a sério; mapear os projetos migrados
  aos seus `task_id` reais; job agendado (worker — ver
  `ARCHITECTURE_PROPOSAL.md` secção 7) em vez de execução manual.
- **Entidades:** `project_external_ids` (source_system='clickup'),
  `import_batches`, `staging_project_records`.
- **Integrações:** ClickUp REST API real (`CLICKUP_ENABLED=true`).
- **Testes:** regressão para garantir zero updates falsos num input sem
  alterações (corrige o bug conhecido do script legado — ver
  `.planning/codebase/CONCERNS.md`, C-08, no repositório do código legado);
  paginação completa testada.
- **Riscos:** mapeamento inicial de projetos a IDs ClickUp pode exigir
  revisão manual extensa de casos ambíguos.
- **Rollback:** manter o script/processo manual anterior disponível como
  plano B até o job agendado ser validado em produção.
- **Critérios de conclusão:** sincronização agendada a correr sem
  intervenção manual; zero "falsas alterações" num teste de estabilidade.

## Fase 5 — Inventário, pedidos de material e custos

- **Objetivo:** cálculo de stock por movimentos; fluxo completo de pedidos
  de material com estados; linhas de custo por categoria/tipo.
- **Entidades:** `inventory_movements`, `material_requests`,
  `material_request_items`, `cost_lines` (endpoints e regras de negócio).
- **Integrações:** Claude (rascunho de pedido a fornecedor — sempre com
  aprovação humana antes de "pedido enviado"); Financial (quando decidido —
  ver `OPEN_QUESTIONS.md`).
- **Testes:** máquina de estados de `material_requests` (transições
  inválidas bloqueadas); teste de que a IA nunca avança um pedido para
  "adjudicado" sozinha.
- **Riscos:** dados de stock inicial desconhecidos — carga inicial manual
  significativa.
- **Rollback:** módulo aditivo; não afeta a migração de projetos já feita.
- **Critérios de conclusão:** um pedido de material percorre todos os
  estados definidos em `docs/PRODUCT_SCOPE.md` com aprovação humana nos
  passos críticos; stock calculado corretamente a partir dos movimentos.

## Fase 6 — Biblioteca documental e formulários/fotografias

- **Objetivo:** ligar SharePoint/OneDrive real (estende `GraphAdapter` com
  operações de ficheiros — ver `docs/DECISIONS.md`, "âmbito deixado de
  fora"); formulários de visita/comissionamento com bloqueio de fecho sem
  fotos obrigatórias.
- **Entidades:** `documents`, `photos`, `form_templates`, `form_responses`.
- **Integrações:** Microsoft Graph (Files).
- **Testes:** teste de que o fecho é bloqueado sem fotos obrigatórias, com
  aviso claro de quem falta completar.
- **Riscos:** `DECISÃO NECESSÁRIA` sobre estrutura atual da Drive e quem
  pode consultar cada documento.
- **Rollback:** módulo aditivo.
- **Critérios de conclusão:** uma visita técnica e um comissionamento
  sintéticos completos de ponta a ponta, com fotos obrigatórias a bloquear
  o fecho até estarem presentes.

## Fase 7 — Claude/MCP completo e relatório semanal

- **Objetivo:** ativar `ClaudeAdapter` a sério; relatório semanal com
  rascunho gerado por IA e revisão humana obrigatória antes do envio;
  pesquisa documental (RAG) sobre a biblioteca da Fase 6.
- **Entidades:** `ai_audit_log` (já implementado, agora usado a sério).
- **Integrações:** Claude API real (`CLAUDE_ENABLED=true`).
- **Testes:** teste de que cada ferramenta respeita o âmbito de leitura
  definido; teste de que nenhuma ferramenta consegue enviar
  email/criar evento/adjudicar/alterar custo sem aprovação humana (teste de
  contrato, não só manual).
- **Riscos:** custo de uso da API a escalar sem controlo — recomenda-se
  limite/orçamento configurável desde o início.
- **Rollback:** manter `CLAUDE_ENABLED=false` (mock) como via de
  recuperação; cada ferramenta pode ser desativada individualmente.
- **Critérios de conclusão:** relatório semanal gerado, revisto e aprovado
  por pelo menos 4 semanas consecutivas; auditoria completa de todas as
  chamadas de IA, sem nenhum caso de ação irreversível sem aprovação.

## Dependências entre fases

Tabela em vez de árvore de propósito: várias fases dependem de mais do que
uma fase anterior (um grafo, não uma árvore), o que uma árvore ASCII não
consegue representar sem ambiguidade — a versão anterior deste documento
tinha exatamente esse problema (dava a entender que a Fase 3 dependia da
Fase 2, quando na realidade só depende da Fase 1).

| Fase | Depende de | Porquê |
|---|---|---|
| Fase 1 — Auth real + CRUD | Fase 0 | Fundação técnica. |
| Fase 2 — Migração real dos 295 projetos | Fase 1 | Precisa de permissões/auditoria reais antes de tocar em dados reais. |
| Fase 3 — Graph real (visitas/calendário) | Fase 1 | Não depende da migração — só de autenticação/permissões reais. |
| Fase 4 — ClickUp real | Fase 2 | Precisa dos projetos já migrados para mapear `task_id`. |
| Fase 5 — Inventário/custos | Fase 2 | Precisa dos projetos já migrados para atribuir stock/custos. |
| Fase 6 — Biblioteca documental | Fase 3 | Reforça o mesmo `GraphAdapter` já ligado a sério na Fase 3 (operações de ficheiros). |
| Fase 7 — Claude/MCP completo | Fase 5 e Fase 6 | Pedidos de material (Fase 5) e pesquisa documental (Fase 6) são pré-requisitos de ferramentas específicas do Claude. |

**Só a Fase 1 é estritamente bloqueante para todas as restantes.** Depois
dela: Fase 2 e Fase 3 podem correr em paralelo; Fase 4 e Fase 5 só depois
da Fase 2; Fase 6 só depois da Fase 3; Fase 7 só depois de Fase 5 e Fase 6
estarem ambas concluídas.

## Plano de testes

| Área | Estado |
|---|---|
| Permissões por perfil | Implementado e testado (`tests/test_permissions.py`) |
| IDs externos/correspondência estável | Implementado e testado (`tests/test_external_ids.py`) |
| Migração em staging (ingestão, conflitos, promoção, rollback, idempotência) | Implementado e testado (`tests/test_staging_persistence.py`) |
| Reconciliação de PM (fila de revisão, nunca promover PM não resolvido) | Implementado e testado (`tests/test_people_reconciliation.py`) |
| Bloqueio de configuração insegura (staging/produção) | Implementado e testado (`tests/test_config_hardening.py`) |
| Motor de base de dados realmente ligado corresponde ao esperado pelo CI | Implementado e testado (`tests/test_database_dialect.py`) |
| Precisão monetária (`Numeric`/`Decimal`) | Implementado e testado (`tests/test_monetary_precision.py`) |
| Histórico/auditoria (append-only, aprovação de IA) | Implementado e testado (`tests/test_audit.py`) |
| Adapters (mock/fallback, nunca chamada real) | Implementado e testado (`tests/test_adapters.py`) |
| Saúde da API | Implementado e testado (`tests/test_health.py`) |
| Endpoints CRUD reais | Por implementar (Fase 1) |
| Integração Entra ID real | Por implementar (Fase 1) |
| Integração Graph/ClickUp/Financial/Claude reais | Por implementar (Fases 3, 4, 5, 7) |
| Frontend (além do build) | Por implementar — sem testes automatizados de UI nesta fase |

CI (`.github/workflows/ci.yml`) corre a cada push/PR: backend contra SQLite
(rápido, sem serviços), backend contra um serviço PostgreSQL do próprio
GitHub Actions (D-021 — valida `batch_alter_table`, `Numeric`, `GUID` no
motor de produção-alvo), e build do frontend.

## Plano de segurança e privacidade

- Nenhum segredo real neste repositório — só `.env.example` (backend e
  frontend). `.gitignore` bloqueia `.env`, `.secrets/`, `data/`, `files/`,
  backups, bases de dados locais, `.eml`/`.ics` gerados.
- Nenhum dado de produção — fixtures exclusivamente sintéticas
  (`backend/fixtures/`), seed de desenvolvimento com nomes/emails
  claramente fictícios (`*.invalid`).
- Autenticação real (Entra ID) antes de qualquer exposição fora de uma rede
  de confiança — o mecanismo de desenvolvimento (D-012) nunca deve chegar a
  produção.
- Toda a escrita relevante gera histórico (`project_history`) com autor e
  timestamp; toda a ação de IA gera auditoria (`ai_audit_log`) com estado
  de aprovação.
- Antes do primeiro deployment acessível fora da rede local, correr uma
  revisão de segurança dedicada sobre o backend.
- Retenção de dados (backups, logs, exports antigos): `DECISÃO NECESSÁRIA`
  — ver `OPEN_QUESTIONS.md`.

## Plano de backups e recuperação

- **Fase 0 (local/dev):** SQLite em ficheiro — sem backup automatizado
  (dados sintéticos, recriáveis a qualquer momento via
  `alembic upgrade head` + `seed_dev`).
- **Staging/produção (PostgreSQL — quando alojado):** backups automáticos
  diários do serviço gerido escolhido, retenção mínima de 30 dias, teste
  periódico de restauro. `DECISÃO NECESSÁRIA` sobre o alojamento concreto.
- **Antes de cada `apply` de migração real:** backup completo da base de
  dados de staging/produção — nunca aplicar uma migração de dados reais sem
  um ponto de restauro imediatamente anterior.

## Plano de deployment

`DECISÃO NECESSÁRIA`: alojamento (cloud vs. on-premises), orçamento — ver
`OPEN_QUESTIONS.md`. Recomendação por omissão, a confirmar: alojamento cloud
pequeno alinhado com o tenant Microsoft 365 (facilita Entra ID/Graph), com
ambientes `staging` (dados fictícios/reais em teste) e `production`
distintos — nenhuma fase avança para produção sem primeiro passar por
staging.

## Estratégia GitHub

- Repositório `Op_PM` mantém-se **público** (D-015) — regra absoluta: nunca
  dados reais, segredos, ou exports de produção.
- Commits pequenos e claros, um assunto por commit (aplicado nesta sessão —
  ver histórico de commits).
- CI obrigatório a passar antes de qualquer merge para `main`.
- Recomenda-se, quando a equipa crescer além de uma pessoa a commitar,
  ativar proteção de branch e revisão obrigatória de PR — mesmo sendo
  equipa pequena, dado tratar-se (eventualmente) de dados reais de clientes
  num sistema derivado deste código.

## Riscos técnicos e operacionais (consolidado)

| Risco | Tipo | Mitigação |
|---|---|---|
| SQLite em dev/teste divergir de PostgreSQL em produção | Técnico | Tipos portáveis (`GUID`, `Numeric`), sem features exclusivas de um motor nos modelos (D-002); job de CI contra PostgreSQL adicionado (D-021) — tentativa real de validação local feita (PostgreSQL embebido via `pgserver`), bloqueada por um problema confirmado do PostgreSQL-para-Windows com o nome de utilizador local (não relacionado com este código) — ver D-021; primeira execução real fica para o GitHub Actions (runners Linux, sem esse problema) |
| Um job de CI "passar" sem testar o que diz testar | Segurança/Técnico | Já aconteceu uma vez nesta fase (conftest.py sobrescrevia sempre DATABASE_URL, mascarando o job PostgreSQL como SQLite) — corrigido com bloqueio duro (`pytest.exit`) + teste nomeado quando `EXPECTED_DB_DIALECT` diverge do motor real (D-022) |
| Sistema Financial desconhecido | Operacional | Fase 5 isolada para não bloquear as restantes; adapter CSV real já disponível (D-011) |
| Conflitos de dados não resolvidos na migração real | Técnico | Mecanismo de staging+conflitos já testado; nunca aplicar sem revisão humana (D-005, D-017) |
| Deteção de duplicados não cobre lotes de importação diferentes ainda não promovidos | Técnico | Âmbito conhecido e documentado (D-017); mitigação operacional: promover um lote de cada vez antes de ingerir o seguinte, na migração real |
| PM desconhecido/ambíguo bloquear muitos projetos na migração real | Operacional | Reconciliação como passo explícito antes da ingestão (D-023) reduz o número de bloqueios; orçamentar tempo de revisão humana para os 8 PMs históricos do legado |
| Rollback de uma promoção que atualizou um projeto existente depende de `project_history` correlacionado corretamente | Técnico | Testado explicitamente (`test_staging_persistence.py`); nunca apaga histórico, só acrescenta — um erro de rollback é sempre auditável e corrigível manualmente, nunca silencioso |
| Equipa pequena (5 utilizadores) com pouca margem para gerir um novo sistema | Operacional | Monólito modular deliberadamente simples (D-001); scheduler leve em vez de fila pesada (D-013) |
| Repositório público herdar dados reais por engano | Segurança | `.gitignore` + fixtures exclusivamente sintéticas + revisão manual antes de cada commit (D-015) |
| Configuração insegura chegar a staging/produção | Segurança | Bloqueada estruturalmente por dupla verificação (D-020) — a aplicação não arranca, e o mecanismo de utilizador de desenvolvimento não funciona fora de local/test |
| IA usada como atalho para decisões humanas | Segurança/Operacional | Controlo arquitetural (nenhuma ferramenta pode executar ação irreversível — ver `ARCHITECTURE_PROPOSAL.md` secção 8) + auditoria completa |
| Custo de APIs externas (Claude, rotas, geocoding) a escalar | Operacional | Limite/orçamento configurável antes de ativar cada integração real |

## Primeiro MVP recomendado

**MVP = Fase 0 (feita) + Fase 1 + Fase 2**: autenticação real, endpoints
CRUD de projetos/workflow atrás de permissões reais, e os 295 projetos reais
migrados para staging com a fila de conflitos revista e resolvida. Isto
entrega o valor mais crítico (login real, permissões reais, histórico
completo, dados reais preservados e mapeados por ID estável) antes de
qualquer funcionalidade nova — visitas, inventário, custos, documentos e IA
constroem-se todos sobre esta base.
