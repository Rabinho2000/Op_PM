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

## Fase 1 — Autenticação real e primeiros endpoints CRUD

- **Objetivo:** ligar Microsoft Entra ID a sério (substituir o mecanismo de
  desenvolvimento — D-012) e expor os primeiros endpoints de escrita reais
  (projetos, workflow) atrás das permissões já modeladas.
- **Entidades:** `projects`, `project_stage_progress`,
  `project_subtask_progress`, `project_history` (endpoints de leitura e
  escrita, sempre gerando entrada de histórico).
- **Integrações:** Entra ID (`AUTH_ENABLED=true`, `GraphAdapter` continua em
  fallback até à Fase 2).
- **Testes:** testes de integração da API (não só de serviço), teste de que
  um token inválido/expirado é rejeitado, teste de que toda a escrita gera
  histórico.
- **Riscos:** depende de `DECISÃO NECESSÁRIA` sobre o tenant M365 (ver
  `OPEN_QUESTIONS.md`) — sem isso, esta fase fica bloqueada na parte de
  autenticação (mas os endpoints CRUD podem avançar sob o mecanismo de
  desenvolvimento entretanto).
- **Rollback:** manter `AUTH_ENABLED=false` como via de recuperação até a
  integração Entra ID estar validada em staging.
- **Critérios de conclusão:** um utilizador real autentica-se via Entra ID;
  `/me` reflete os seus papéis reais; criar/editar um projeto sintético via
  API gera uma entrada de `project_history` correta.

## Fase 2 — Migração real dos 295 projetos (staging → produção)

- **Objetivo:** migrar os dados reais do repositório do código legado
  (`files/atribuicoes.json`, fora deste repositório público) para a base de
  dados de staging, resolver a fila de conflitos manualmente, e só depois
  aplicar em produção.
- **Entidades:** todas as tocadas por `app/migration/staging.py` —
  `projects`, `project_external_ids`, `import_batches`,
  `staging_project_records`.
- **Integrações:** nenhuma nova — reutiliza `ingest_export`/
  `resolve_conflict`/`promote_staging_record` já implementados e testados.
- **Testes:** contagem de projetos migrados == 295 (ou o número real no
  momento da migração); amostragem de campos antes/depois; nenhum registo
  `staging_project_records.status='conflict'` fica sem revisão antes de
  qualquer promoção.
- **Riscos:** divergências já documentadas entre `atribuicoes.json` e
  exports de PM no repositório legado precisam de resolução manual antes
  desta fase — ver a análise desse repositório.
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

```text
Fase 0 (feito)
   └─► Fase 1 (auth real + CRUD)
          ├─► Fase 2 (migração real dos 295 projetos)
          │      ├─► Fase 4 (ClickUp real, precisa dos projetos migrados)
          │      └─► Fase 5 (inventário/custos)
          ├─► Fase 3 (Graph real — visitas/calendário)
          │      └─► Fase 6 (biblioteca documental, reforça o mesmo GraphAdapter)
          └─► Fase 7 (Claude/MCP completo — precisa de 5 e 6 para pedidos de material e pesquisa documental)
```

Fases 3, 4 e 5 podem ser paralelizadas depois da Fase 2, se houver
capacidade de equipa — só a Fase 1 é estritamente bloqueante para todas.

## Plano de testes

| Área | Estado |
|---|---|
| Permissões por perfil | Implementado e testado (`tests/test_permissions.py`) |
| IDs externos/correspondência estável | Implementado e testado (`tests/test_external_ids.py`) |
| Migração em staging (ingestão, conflitos, promoção, rollback, idempotência) | Implementado e testado (`tests/test_staging_persistence.py`) |
| Bloqueio de configuração insegura (staging/produção) | Implementado e testado (`tests/test_config_hardening.py`) |
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
| SQLite em dev/teste divergir de PostgreSQL em produção | Técnico | Tipos portáveis (`GUID`, `Numeric`), sem features exclusivas de um motor nos modelos (D-002); job de CI contra PostgreSQL adicionado (D-021), mas não executado localmente neste ambiente — primeira execução real fica para o GitHub Actions |
| Sistema Financial desconhecido | Operacional | Fase 5 isolada para não bloquear as restantes; adapter CSV real já disponível (D-011) |
| Conflitos de dados não resolvidos na migração real | Técnico | Mecanismo de staging+conflitos já testado; nunca aplicar sem revisão humana (D-005, D-017) |
| Deteção de duplicados não cobre lotes de importação diferentes ainda não promovidos | Técnico | Âmbito conhecido e documentado (D-017); mitigação operacional: promover um lote de cada vez antes de ingerir o seguinte, na migração real |
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
