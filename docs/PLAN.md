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

## Fase 1 — Autenticação real e primeiros endpoints CRUD (IMPLEMENTADA — código completo, login real ponta-a-ponta pendente do tenant)

Ver `docs/DECISIONS.md` D-024 a D-027 para o detalhe técnico completo.

- **Objetivo:** ligar a validação real de token Microsoft Entra ID
  (substituindo o `NotImplementedError` da Fase 0 — D-012), expor os
  primeiros endpoints CRUD de projetos atrás das permissões já modeladas,
  endpoints para consultar/resolver a migração (lotes, staging,
  reconciliação de PM), e a primeira interface web funcional.
- **O que ficou feito:**
  1. `app/security/entra_auth.py`: validação real (JWKS do tenant, RS256,
     issuer/audience/validade) e um validador mock (chave de teste local,
     nunca alcançável fora de testes — D-024).
  2. `get_current_user` valida `Authorization: Bearer <token>` quando
     `AUTH_ENABLED=true`; liga por `entra_object_id`, com ligação
     "just-in-time" por email para um `User` ainda não ligado (nunca cria
     um `User` novo a partir de um token).
  3. `app/services/projects.py` + `app/api/routes_projects.py`: listar
     (com filtros PM/estado/pesquisa, respeitando `view_all`/`view_own`),
     detalhe, editar (`can_edit_project` antes de qualquer escrita, uma
     entrada de `project_history` por campo alterado), histórico.
  4. `app/api/routes_migration.py`: consultar lotes/registos de
     staging/fila de reconciliação, e as ações de resolução já existentes
     (`resolve-conflict`, `promote`, `rollback`, `retry-pm-resolution`,
     `reconciliation-items/resolve`) — sem endpoint de ingestão (D-026,
     decisão deliberada).
  5. Frontend: `Login`, `ProjectsList`, `ProjectDetail`, `ReconciliationQueue`,
     `react-router-dom` — validado manualmente ponta-a-ponta com o backend
     local (D-027).
- **O que ficou pendente (fora do controlo deste repositório):**
  autenticação real ponta-a-ponta precisa de um tenant Microsoft
  Entra ID/app registration reais (pergunta bloqueante nº 1) para o
  MSAL.js do frontend ter com quem falar — o backend já valida tokens
  reais, mas não há tenant para os emitir. O login do frontend continua a
  usar o mecanismo de desenvolvimento (`X-Dev-User-Email`, só
  local/test), com um aviso explícito no ecrã sobre esta pendência.
- **Entidades:** `projects`, `project_history` (endpoints de leitura e
  escrita); `import_batches`, `staging_project_records`,
  `person_reconciliation_items` (endpoints de leitura e resolução).
  `project_stage_progress`/`project_subtask_progress` (workflow) **ainda
  sem endpoint** — ver "Âmbito deixado de fora da Fase 1" em
  `docs/DECISIONS.md`.
- **Integrações:** nenhuma real ainda — Graph/ClickUp/Financial/Claude
  continuam mock/fallback; `GraphAdapter` fica em fallback local até à
  Fase 6 (renumerada nesta revisão — ver "Dependências entre fases").
- **Testes:** `tests/test_auth_entra.py` (12 — token válido/inválido/
  malformado/expirado/audience errada/issuer errado, ligação por email e
  por `entra_object_id`, utilizador sem papel, X-Dev-User-Email ignorado
  com `AUTH_ENABLED=true`); `tests/test_project_api.py` (8 — PM só edita
  o seu, Chefe edita qualquer um, Comercial só lê, histórico por campo
  alterado, sem entrada quando o valor não muda, pedido não autenticado);
  `tests/test_migration_api.py` (5 — bloqueio de promoção em conflito,
  reconciliação de PM desconhecido via API seguida de promoção,
  `proceed_without_pm` via API, permissão de migração). Suite completa:
  99 passed, 2 skipped (SQLite local).
- **Riscos:** depende de `DECISÃO NECESSÁRIA` sobre o tenant M365 (ver
  `OPEN_QUESTIONS.md`) para o login real ponta-a-ponta — sem isso, a
  aplicação continua a funcionar em `local`/`test` com o mecanismo de
  desenvolvimento, mas nunca pode ser exposta em `staging`/`production`
  (D-020/D-024 bloqueiam isso estruturalmente).
- **Rollback:** em `local`/`test`, manter `AUTH_ENABLED=false` (mecanismo
  de desenvolvimento) como via de recuperação enquanto a integração Entra
  ID não estiver pronta. **Nunca em `staging`/`production`** — aí
  `AUTH_ENABLED=false` está bloqueado estruturalmente pela validação de
  arranque (D-020); a app simplesmente não arranca com essa combinação. Na
  prática isto significa que só se promove esta fase para staging depois
  de a integração Entra ID real estar a funcionar — não há um "voltar
  atrás" para staging/produção sem autenticação real, por desenho.
- **Critérios de conclusão:** código de validação real de token completo e
  testado (mock); `/me` reflete papéis/permissões reais; editar um
  projeto sintético via API gera uma entrada de `project_history`
  correta; frontend funcional validado manualmente. **Login real
  ponta-a-ponta com um tenant Entra ID de verdade fica como critério em
  aberto até à pergunta bloqueante nº 1 ser respondida** — não é um
  critério que este repositório possa cumprir sozinho.

## Fase 1 — Fecho técnico para staging/produção (IMPLEMENTADA)

Pedida explicitamente antes de preparar o primeiro deployment de
staging/produção. Ver `docs/DECISIONS.md` D-032 a D-037 para o detalhe
técnico completo; `docs/STAGING_CHECKLIST.md`, `docs/GO_LIVE_CHECKLIST.md`
e `docs/DATA_MIGRATION_RUNBOOK.md` (novos) para os procedimentos
operacionais que dependem deste fecho.

- **Objetivo:** fechar as lacunas identificadas antes de expor a aplicação
  fora de `local`/`test` — configuração obrigatória e completa,
  separação real do login de desenvolvimento, um mecanismo seguro de
  provisionar os 5 utilizadores, uma allowlist de campos de PM sem
  suposições de negócio por confirmar, e uma forma controlada e segura de
  executar a migração real.
- **O que ficou feito:**
  1. `Settings` passa a exigir, em `staging`/`production`,
     `ENTRA_TENANT_ID`/`ENTRA_CLIENT_ID`/`ENTRA_REQUIRED_SCOPE`
     preenchidos, `CORS_ALLOWED_ORIGINS` não vazio, e um override de
     issuer/JWKS/audience sempre completo ou sempre ausente — nunca
     parcial (D-032).
  2. Frontend: o login de desenvolvimento (`X-Dev-User-Email`) nunca
     sobrevive a um build de produção, mesmo com um valor antigo já em
     `localStorage` — primeiro framework de testes automatizados do
     frontend (Vitest), 4 testes (D-033).
  3. `app/cli/provision_entra_user.py`: comando administrativo controlado
     para ligar um `User` já existente ao seu `entra_object_id` real —
     nunca cria utilizadores a partir de um token, nunca reatribui,
     impede reutilização do mesmo `entra_object_id`, sempre auditado
     (D-034).
  4. Allowlist de campos de PM revista: potência, coordenadas, datas
     legadas e `commercial_assumptions` passam a administrativos até
     confirmação de negócio — ver `docs/OPEN_QUESTIONS.md` pergunta 5-B
     (D-035).
  5. `retry_promotion_after_rollback`: fecha um caso não coberto até
     agora — repetir a promoção depois de um rollback sem nunca duplicar
     o projeto (D-036).
  6. `app/cli/ingest_staging.py`: única forma controlada de invocar a
     ingestão para staging fora dos testes, com um modo staging-only
     explícito (recusa `APP_ENV=production`) e contagens de revisão
     (projetos, PMs distintos, com email/contacto/coordenadas, conflitos)
     — D-037.
- **Entidades:** sem alteração de schema — `project_history` ganha o
  valor de `source` `migration_retry` (D-036).
- **Integrações:** nenhuma — continuam todas mock/fallback/por confirmar.
- **Testes:** `test_config_hardening.py` (+14), `client.dev-login.test.ts`
  (novo, frontend, 4), `test_provision_entra_user.py` (12, novo),
  `test_project_field_permissions.py` (+1), `test_staging_persistence.py`
  (+3), `test_migration_api.py` (+2), `test_ingest_staging_cli.py` (10,
  novo). Ver `docs/DECISIONS.md` D-032 a D-037 para os números exatos por
  decisão.
- **Riscos:** ver "Riscos técnicos e operacionais" mais abaixo — a
  allowlist de PM revista (D-035) introduz atrito operacional aceite
  deliberadamente até haver decisão de negócio.
- **Rollback:** reverter para o commit anterior a esta revisão — nenhuma
  integração real foi tocada, nenhum dado real existe ainda.
- **Critérios de conclusão:** suite completa a passar (SQLite local);
  `npm run test`/`npm run build` do frontend sem erros; nenhum segredo,
  dado real, ou base de dados local no commit; documentos de
  staging/go-live/migração criados.

## Fase 1.5 — MVP operacional: dashboard, tarefas e workflow (IMPLEMENTADA)

Pedida explicitamente pelo negócio como o MVP a entregar antes da Fase 2
(migração real dos 295 projetos) — ver "MVP recomendado" mais abaixo para a
justificação de porque este MVP passou à frente daquele. Não depende da
Fase 2: usa só os projetos sintéticos já semeados, exatamente como as fases
anteriores. Ver `docs/DECISIONS.md` D-039 a D-047 para o detalhe técnico
completo.

- **Objetivo:** uma aplicação utilizável internamente desde já — página
  inicial com indicadores reais, tarefas com responsável/prazo/estado por
  projeto, férias/ausências, aniversários — antes de qualquer integração
  externa ou migração de dados reais.
- **O que ficou feito:**
  1. `app/models/task.py`: entidade `Task` genérica (projeto, título, tipo,
     descrição, estado, prioridade, responsável, prazo, data de conclusão,
     notas, criado por, timestamps) + `TaskHistory` append-only. Entidade
     nova, não reaproveita `Phase`/`WorkflowStage`/`ProjectSubtaskProgress`
     já existentes — ver D-039 para a justificação.
  2. Máquina de estados (`todo`/`in_progress`/`blocked`/`done`/
     `cancelled`) aplicada no servidor, nunca confiada ao cliente — D-040.
  3. `app/services/tasks.py:ensure_default_tasks_for_project`: checklist
     padrão de 5 tarefas por projeto (visita técnica, preparação da
     instalação, instalação, comissionamento, colocar fotos na Drive),
     idempotente.
  4. `app/models/absence.py`: entidade `Absence` (pessoa, data
     inicial/final, tipo, nota, estado) — modelo mínimo, sem fluxo de
     aprovação nesta fase (D-042). `Person` ganha `birth_date`.
  5. `GET /api/dashboard/summary`: todos os indicadores da página inicial
     calculados no servidor (projetos ativos, a começar em 30 dias,
     tarefas atrasadas/pendentes esta semana — sempre em `Europe/Lisbon`,
     visitas técnicas/comissionamentos pendentes, projetos sem PM/dados em
     falta, férias atuais/próximas, aniversários próximos, trabalhos
     urgentes) — nunca calculados no frontend a partir de listas completas
     (D-041).
  6. `ProjectRead` ganha indicadores derivados de tarefas: estado
     (`nao_iniciado`/`em_curso`/`concluido`), próxima tarefa e prazo,
     contagem de tarefas atrasadas, progresso do workflow (%), e o aviso
     persistente de fotos pendentes (reaproveita a tarefa padrão
     `fotos_drive`, sem campo novo — D-043).
  7. Matriz de permissões alargada: `task.view_all`/`_own`,
     `task.edit_all`/`_own`, `absence.view_all`/`_own`,
     `absence.manage_all`/`_own` — ver D-045 para a tabela completa por
     perfil. Visibilidade de férias/aniversários no dashboard ligada a
     `absence.view_all`/`_own` (privacidade por omissão — D-044).
  8. Frontend: `/` passa a ser o painel operacional (`Home.tsx`); conteúdo
     técnico anterior preservado em `/status` (`SystemStatus.tsx` — D-047);
     páginas novas `/tasks` e `/vacations`; `ProjectsList`/`ProjectDetail`
     atualizadas com os novos indicadores, tarefas do projeto, e o aviso de
     fotos.
  9. Primeira infraestrutura de testes de frontend (Vitest + Testing
     Library) — D-046.
- **Entidades:** `tasks`, `task_history`, `absences` (novas); `people`
  ganha `birth_date`.
- **Integrações:** nenhuma — continuam todas mock/fallback. Nenhum dado
  financeiro em nenhum indicador (o módulo Financial está fora deste MVP),
  por isso a vista Comercial nunca mostra dado financeiro nenhum, sem
  precisar de nenhuma lógica extra de ocultação (ver D-045).
- **Testes:** `tests/test_tasks_api.py` (17), `tests/test_absences_api.py`
  (10), `tests/test_dashboard.py` (12), `tests/test_project_task_summary.py`
  (6) — adicionados pela Fase 1.5. Depois de integrar com o hardening da
  Fase 1 (`mvp-ready`), a suite completa de backend soma 224 testes a
  passar + 2 skipped em SQLite. Frontend: `src/utils/dates.test.ts`,
  `src/api/taskTransitions.test.ts`, `src/pages/Home.test.tsx` +
  `client.dev-login.test.ts` (D-033, hardening) — 18 testes Vitest no
  total.
- **Riscos:** ver "Riscos técnicos e operacionais" mais abaixo.
- **Rollback:** módulo aditivo — nenhuma tabela nem endpoint pré-existente
  foi alterado de forma incompatível (só `ProjectRead` ganhou campos novos,
  sempre com omissão razoável). Reverter para o commit anterior a esta fase
  remove `/`, `/tasks`, `/vacations` e os indicadores novos sem afetar
  autenticação, CRUD de projetos, ou migração.
- **Critérios de conclusão (cumpridos):** login com utilizador de
  desenvolvimento funcional; página inicial mostra métricas reais vindas da
  base de dados; abrir um projeto mostra tarefas/histórico/avisos/progresso;
  criar/atribuir/concluir/reabrir tarefas funciona ponta-a-ponta (validado
  manualmente no browser — mudar o estado de "Colocar fotos na Drive" para
  concluída faz o aviso desaparecer e o progresso subir para 100% em tempo
  real); tarefas atrasadas aparecem no dashboard; visita técnica e
  comissionamento geram o aviso das fotos; férias e aniversários aparecem
  no dashboard, respeitando permissões; permissões de PM/Comercial/Chefe/
  Administrador respeitadas (verificado também manualmente trocando de
  utilizador no browser); suite combinada de 224 testes de backend
  (+2 skipped) + 18 de frontend a passar em `mvp-ready`; `npm run build`
  sem erros; nenhum dado real migrado.

## Fase 1.6 — Preparação para staging (IMPLEMENTADA, código; alojamento/tenant reais pendentes)

Pedida explicitamente antes de um primeiro piloto com dados reais em
staging. Ver `docs/DECISIONS.md` D-049 e `docs/STAGING_RUNBOOK.md` (novo)
para o procedimento operacional completo.

- **Objetivo:** tudo o que depende só de código/documentação, sem tenant
  Entra ID nem alojamento reais, ficar pronto — para o dia em que esses
  dois existirem, restar só seguir o runbook.
- **O que ficou feito:**
  1. `app.cli.ingest_staging` ganha `--dry-run`/`--only-ids`/`--limit` —
     testar um piloto de 5 a 10 projetos reais antes dos 295, com
     pré-visualização sem escrever nada (D-049).
  2. Segunda barreira em código (além da disciplina já documentada)
     contra um export com dados reais entrar no Git por engano —
     `assert_file_is_not_trackable_by_git`.
  3. `app.migration.seed_dev.run_seed()` recusa-se a correr em
     staging/produção — antes, só a checklist documentava isto.
  4. `backend/.env.staging.example`/`frontend/.env.staging.example`
     (novos) — todos os valores obrigatórios de staging já assinalados
     com placeholder explícito, distintos dos exemplos de local/dev.
  5. `docs/STAGING_RUNBOOK.md` (novo): procedimento completo — App
     registrations Entra ID (passo a passo exato), PostgreSQL,
     migrações, os 5 utilizadores, health checks, logs, backups/
     rollback, testes de aceitação, o piloto, e como parar o ambiente.
- **Entidades:** sem alteração de schema.
- **Integrações:** nenhuma — continuam todas mock/fallback.
- **Testes:** `tests/test_ingest_staging_cli.py` (+8),
  `tests/test_seed_dev_staging_guard.py` (4, novo).
- **Riscos:** ver `docs/OPEN_QUESTIONS.md` perguntas 25 a 28 (alojamento,
  seed de staging, consentimento, JIT linking) — nenhuma decisão de
  negócio foi assumida.
- **Rollback:** módulo aditivo — reverter para o commit anterior a esta
  revisão não afeta nenhum dado nem funcionalidade já existente.
- **Critérios de conclusão (cumpridos, quanto ao que depende só de
  código):** suite completa a passar; `npm run lint`/`npm test`/
  `npm run build` sem erros; nenhum segredo real nos exemplos de
  configuração. **Em aberto** (dependem de dados externos — ver
  `docs/STAGING_RUNBOOK.md` secção 16): tenant Entra ID real, domínio,
  alojamento — sem eles, staging não pode ser levantado de facto, só
  preparado.

## Fase 1.7 — MVP de demonstração (IMPLEMENTADA)

Ver `docs/MVP_DEMO.md` (guia operacional) e `docs/DECISIONS.md` D-051.

- **Objetivo:** demonstração visualmente convincente para clientes/equipa,
  levantada com um comando e só com dados sintéticos.
- **O que ficou feito:** interface nova (layout com sidebar, painel com
  resumo da semana e aviso de fotografias, projetos com filtros e detalhe
  em separadores, tarefas em lista/Kanban, calendário de férias e
  aniversários, login com modo demo separado do Microsoft);
  extensões aditivas da API (indicadores e filtros novos, permissões
  efetivas por recurso, `DEMO_MODE` bloqueado fora de `local`);
  `app.cli.demo` + seed de demonstração só em `APP_ENV=local`;
  `docker-compose.demo.yml`, `frontend/Dockerfile.demo`,
  `scripts/demo_local.py`; job `demo-smoke` no CI.
- **Entidades:** sem alteração de schema (nenhuma migração nova).
- **Integrações:** nenhuma — continuam todas desligadas.
- **Testes:** `tests/test_demo_mvp.py` (25); frontend 53 testes Vitest
  (35 novos: painel, estados, filtros, estado de tarefa, fotografias,
  navegação, permissões).
- **Rollback:** aditivo — reverter a branch remove a interface nova e os
  ficheiros de demo sem afetar dados, autenticação ou migração.

## Fase 2 — Dashboard inicial

**Estado: IMPLEMENTADA — ver Fase 1.5 acima.** O roadmap original desta
fase (estatísticas semanais, separação operacional/comercial, férias e
aniversários) foi entregue integralmente pelo MVP da Fase 1.5
(`GET /api/dashboard/summary`, `Absence`, aniversários) — sem depender da
migração real dos 295 projetos. Mantido aqui só como registo histórico do
roadmap original; ver `docs/DECISIONS.md` D-041/D-044 para o desenho
final e `docs/OPEN_QUESTIONS.md` pergunta 21 para a decisão de
visibilidade ainda em aberto.

## Fase 3 — Workflow de projetos

**Estado: parcialmente coberto pela Fase 1.5, ver nota abaixo.** A Fase
1.5 deu a cada projeto uma checklist de tarefas (`Task`, D-039/D-040) com
responsável, prazo e máquina de estados — cobre a necessidade operacional
imediata de acompanhar o progresso de um projeto sem esperar por este
roadmap. O que **não** foi feito, e continua a descrição original desta
fase abaixo: expor o processo oficial fixo por fases já modelado desde a
Fase 0 (`Phase`/`WorkflowStage`/`WorkflowSubtask` +
`ProjectStageProgress`/`ProjectSubtaskProgress`), que **continua
intacto e sem endpoints/UI**, propositadamente não migrado nem ligado a
`Task` nesta revisão — decisão explícita de não arriscar uma migração de
dados agora (ver `docs/OPEN_QUESTIONS.md` perguntas 22 e 24). Um futuro
formulário de visita técnica/comissionamento deve decidir, antes de ser
construído, qual das duas entidades (ou uma nova) é a fonte de verdade
única — não ambas.

**Estado: por implementar — o modelo de dados (`Phase`, `WorkflowStage`,
`WorkflowSubtask`, `ProjectStageProgress`, `ProjectSubtaskProgress`) já
existe desde a Fase 0 (seed genérico de exemplo em
`app/migration/seed_dev.py`), mas sem endpoints nem estados oficiais
confirmados — ver a nota já registada em `docs/DECISIONS.md` ("Âmbito
deixado de fora da Fase 1").**

- **Objetivo:** expor o processo operacional (fases → etapas →
  subtarefas) já modelado como um workflow utilizável — estado de cada
  projeto, responsável por etapa, tarefas, datas, e o que é exigido para
  avançar de fase.
- **Funcionalidades pedidas (âmbito, não desenho de detalhe):**
  1. Estados oficiais do processo — o seed atual (`GENERIC_WORKFLOW` em
     `seed_dev.py`) é deliberadamente genérico/de exemplo, não o processo
     real de 6 fases da Solcor; carregar o processo real é
     `DECISÃO NECESSÁRIA` (confirmar fases/etapas/subtarefas oficiais,
     não assumidas aqui).
  2. Responsáveis por etapa — `WorkflowStage.responsible_role_code` já
     existe (papel, não pessoa); falta confirmar se a atribuição real é
     sempre "o PM do projeto" ou se varia por etapa.
  3. Tarefas — `ProjectSubtaskProgress` já modela conclusão de subtarefa;
     falta o endpoint/UI para marcar/desmarcar.
  4. Datas — `WorkflowStage.planned_start_offset_days`/
     `planned_end_offset_days` já existem (offset em dias desde o início
     do projeto); falta confirmar a partir de que data se conta
     (`start_date`? data de handover?).
  5. Requisitos para avançar de fase — **não modelado ainda**: hoje nada
     impede marcar qualquer etapa/subtarefa em qualquer ordem. Que
     combinação de etapas/subtarefas concluídas é exigida para uma fase
     ser considerada "fechada" é `DECISÃO NECESSÁRIA`, para não inventar
     uma regra de bloqueio que trave o trabalho real por engano.
- **Entidades:** `phases`, `workflow_stages`, `workflow_subtasks`,
  `project_stage_progress`, `project_subtask_progress` — todas já
  existentes desde a Fase 0; endpoints novos (leitura do processo,
  marcar/desmarcar progresso, respeitando permissões já modeladas).
- **Integrações:** nenhuma nova.
- **Testes:** transição de fase bloqueada sem os requisitos definidos
  acima (quando essa regra existir); progresso de subtarefa só alterável
  por quem tem `project.edit_own_progress`/`project.edit_all` no projeto
  em causa.
- **Riscos:** carregar o processo real errado (fases/etapas/ordem) exige
  confirmação humana antes de qualquer projeto real passar por aqui —
  nunca assumir que o seed genérico de exemplo é o processo real.
- **Rollback:** módulo aditivo — não altera `projects` diretamente, só as
  tabelas de progresso já existentes.
- **Critérios de conclusão:** processo real carregado e confirmado;
  endpoints de leitura/progresso testados; requisitos de avanço de fase
  definidos e testados (quando confirmados como decisão de negócio).

## Fase 4 — Migração real dos 295 projetos (staging → produção)

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

## Fase 5 — Inventário e pedidos de material

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

## Fase 6 — Planeamento e visitas (Microsoft Graph real)

- **Objetivo:** ligar `GraphAdapter` a sério (substituir o fallback local);
  fluxo de visitas com proposta de data, rascunho de email/evento,
  aprovação humana antes de envio/marcação real. Emails, calendário e
  documentos reais, por esta ordem de prioridade (documentos aprofundados
  na Fase 9).
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

## Fase 7 — Claude: propostas de agenda, preparação de emails e relatórios

- **Objetivo:** ativar `ClaudeAdapter` a sério, com o âmbito pedido nesta
  revisão do roadmap — propostas de agenda (datas de visita), preparação
  de rascunhos de email, e relatório semanal — **sempre com aprovação
  humana antes de qualquer ação real** (enviar email, marcar evento,
  publicar relatório). Nenhuma ferramenta de IA executa uma ação
  irreversível sozinha (ver `ARCHITECTURE_PROPOSAL.md` secção 8).
- **Nota sobre âmbito reduzido face à versão anterior deste roadmap:** a
  versão anterior incluía aqui "pesquisa documental (RAG) sobre a
  biblioteca" — essa funcionalidade dependia da Biblioteca Documental
  (agora Fase 9, depois desta, para respeitar a ordem pedida nesta
  revisão). Fica como um incremento futuro de Claude, depois da Fase 9,
  não como parte do âmbito imediato desta fase.
- **Entidades:** `ai_audit_log` (já implementado, agora usado a sério).
- **Integrações:** Claude API real (`CLAUDE_ENABLED=true`).
- **Testes:** teste de que cada ferramenta respeita o âmbito de leitura
  definido; teste de que nenhuma ferramenta consegue enviar
  email/criar evento/publicar relatório sem aprovação humana (teste de
  contrato, não só manual).
- **Riscos:** custo de uso da API a escalar sem controlo — recomenda-se
  limite/orçamento configurável desde o início (ver `OPEN_QUESTIONS.md`,
  pergunta 14).
- **Rollback:** manter `CLAUDE_ENABLED=false` (mock) como via de
  recuperação; cada ferramenta pode ser desativada individualmente.
- **Critérios de conclusão:** relatório semanal gerado, revisto e aprovado
  por pelo menos 4 semanas consecutivas; auditoria completa de todas as
  chamadas de IA, sem nenhum caso de ação irreversível sem aprovação.

## Fase 8 — ClickUp real

**Nota sobre posição no roadmap:** não fazia parte da ordem de seis itens
pedida nesta revisão (Dashboard → Workflow → Migração → Inventário →
Graph → Claude) — mantida no roadmap, colocada depois dessas seis por não
haver indicação de prioridade relativa; só depende tecnicamente da Fase 4
(migração), nunca das Fases 5 a 7. Se a prioridade real for outra, é uma
reordenação simples desta secção, sem impacto técnico.

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

## Fase 9 — Biblioteca documental e formulários/fotografias

**Nota sobre posição no roadmap:** tal como a Fase 8 (ClickUp), não fazia
parte da ordem de seis itens pedida nesta revisão — mantida depois dela,
sem prioridade relativa confirmada face a essas seis. Depende
tecnicamente da Fase 6 (Graph real), única razão para vir depois dela.

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

## Dependências entre fases

Tabela em vez de árvore de propósito: várias fases dependem de mais do que
uma fase anterior (um grafo, não uma árvore), o que uma árvore ASCII não
consegue representar sem ambiguidade.

A ordem de números das Fases 2 a 7 segue a prioridade pedida explicitamente
nesta revisão (Dashboard → Workflow → Migração → Inventário → Graph →
Claude) — nem sempre coincide com a ordem de dependência técnica estrita
(ex.: a Fase 4, Migração, só depende tecnicamente da Fase 1, não da 2/3;
sequenciada depois delas por prioridade de negócio, não por bloqueio
técnico). As Fases 8 e 9 (ClickUp, Biblioteca documental) não faziam parte
dessa ordem pedida — ver a nota em cada uma.

| Fase | Depende tecnicamente de | Porquê |
|---|---|---|
| Fase 1 — Auth real + CRUD | Fase 0 | Fundação técnica. |
| Fase 1.5 — MVP operacional (dashboard/tarefas/workflow) | Fase 1 | Precisa de permissões/CRUD de projetos reais para ter algo a mostrar; usa só os projetos sintéticos, não depende da migração. |
| Fase 1.6 — Preparação para staging | Fase 1 e Fase 1.5 | Precisa do fecho técnico (Fase 1) e do MVP a proteger (Fase 1.5) antes de decidir o que fica seguro/pronto para expor em staging; não depende da Fase 4 (a migração real é o que a Fase 1.6 prepara o terreno para receber, via piloto). |
| Fase 2 — Dashboard inicial | Fase 1.5 | Implementada pela Fase 1.5 — linha mantida só como registo histórico do roadmap original. |
| Fase 3 — Workflow de projetos | Fase 1.5 | Parcialmente coberta pela Fase 1.5 (`Task`); o processo fixo por fases (`Phase`/`WorkflowStage`) continua sem endpoints — ver nota na secção da Fase 3. |
| Fase 4 — Migração real dos 295 projetos | Fase 1 | Precisa de permissões/auditoria reais antes de tocar em dados reais. Não depende tecnicamente das Fases 2/3 — pode correr em paralelo com a Fase 1.5. |
| Fase 5 — Inventário/pedidos de material | Fase 4 | Precisa dos projetos já migrados para atribuir stock/custos. |
| Fase 6 — Graph real (visitas/calendário) | Fase 1 | Não depende da migração — só de autenticação/permissões reais. |
| Fase 7 — Claude (agenda/emails/relatórios) | Fase 5 e Fase 6 | Pedidos de material (Fase 5) e propostas de agenda/email (Fase 6) são pré-requisitos das ferramentas específicas do Claude descritas aqui. |
| Fase 8 — ClickUp real | Fase 4 | Precisa dos projetos já migrados para mapear `task_id`. |
| Fase 9 — Biblioteca documental | Fase 6 | Reforça o mesmo `GraphAdapter` já ligado a sério na Fase 6 (operações de ficheiros). |

**Só a Fase 1 é estritamente bloqueante para todas as restantes.** A Fase
1.5 (implementada) só depende da Fase 1 e correu em paralelo com o resto
do roadmap. Depois da Fase 1: Fases 2, 3 e 6 podem correr em paralelo;
Fase 4 só precisa da Fase 1 (sequenciada depois de 2/3 por prioridade de
negócio); Fase 5 e Fase 8 só depois da Fase 4; Fase 9 só depois da Fase 6;
Fase 7 só depois de Fase 5 e Fase 6 estarem ambas concluídas.

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
| Validação de token Entra ID (real e mock) | Implementado e testado (`tests/test_auth_entra.py`) |
| Endpoints CRUD de projetos + permissões + histórico | Implementado e testado (`tests/test_project_api.py`) |
| Endpoints de migração (resolução, nunca ingestão) | Implementado e testado (`tests/test_migration_api.py`) |
| Configuração obrigatória completa em staging/produção (Entra ID/CORS) | Implementado e testado (`tests/test_config_hardening.py`, D-032) |
| Login de desenvolvimento nunca sobrevive fora de local/test (frontend) | Implementado e testado (`frontend/src/api/client.dev-login.test.ts`, D-033) |
| Provisionamento administrativo de utilizadores (`entra_object_id`) | Implementado e testado (`tests/test_provision_entra_user.py`, D-034) |
| Allowlist de campos de PM sem suposições de negócio por confirmar | Implementado e testado (`tests/test_project_field_permissions.py`, D-035) |
| Repetição segura de promoção após rollback (nunca duplica projeto) | Implementado e testado (`tests/test_staging_persistence.py`, `tests/test_migration_api.py`, D-036) |
| Ingestão controlada staging-only, com contagens de revisão | Implementado e testado (`tests/test_ingest_staging_cli.py`, D-037) |
| Tarefas: CRUD, máquina de estados, atribuição, permissões, histórico | Implementado e testado (`tests/test_tasks_api.py`, D-039/D-040) |
| Indicadores derivados de projeto (estado, próxima tarefa, progresso, aviso de fotos) | Implementado e testado (`tests/test_project_task_summary.py`, D-043) |
| Férias/ausências: CRUD, validação de datas, permissões | Implementado e testado (`tests/test_absences_api.py`, D-042/D-044) |
| Dashboard: cada indicador, escopo por perfil, fuso Europe/Lisbon | Implementado e testado (`tests/test_dashboard.py`, D-041) |
| Frontend: funções puras, máquina de estados espelhada, fumo do painel inicial | Implementado e testado (Vitest — `src/utils/dates.test.ts`, `src/api/taskTransitions.test.ts`, `src/pages/Home.test.tsx`) |
| Autenticação Entra ID real ponta-a-ponta (tenant de verdade) | Bloqueado pela pergunta nº 1 — código pronto, validado só com mock |
| Integração Graph/ClickUp/Financial/Claude reais | Por implementar (Fases 6, 7, 8, e a parte Financial da Fase 5) |
| Frontend end-to-end (fluxos completos, não só funções/fumo) | Sem Playwright/Cypress ainda — ver D-027/D-046; Vitest cobre login de desenvolvimento (D-033) e a suite de UI da Fase 1.5 (D-046) |

CI (`.github/workflows/ci.yml`) corre a cada push/PR: backend contra SQLite
(rápido, sem serviços), backend contra um serviço PostgreSQL do próprio
GitHub Actions (D-021 — valida `batch_alter_table`, `Numeric`, `GUID` no
motor de produção-alvo), e o job de frontend (lint/`tsc --noEmit`, Vitest,
build — D-046).

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
| Configuração insegura chegar a staging/produção | Segurança | Bloqueada estruturalmente por tripla verificação (D-020, D-024) — a aplicação não arranca sem AUTH_ENABLED/SECRET_KEY/DATABASE_URL/ENTRA_VALIDATION_MODE corretos, e o mecanismo de utilizador de desenvolvimento não funciona fora de local/test |
| Login real ponta-a-ponta continua por confirmar sem um tenant Entra ID de verdade | Operacional/Técnico | Validação de token já implementada e testada com uma chave mock (D-024) — só falta o tenant/app registration (pergunta bloqueante nº 1); nenhuma parte do backend precisa de ser reescrita quando esse tenant existir |
| `can_edit_project` é tudo-ou-nada por projeto, não por campo (um PM podia, em teoria, editar `clickup_status_mirror` se estivesse em `ProjectUpdate`) | Técnico | Mitigado nesta fase por desenho: `clickup_status_mirror` fica fora de `ProjectUpdate` (D-025); restrição por campo mais fina fica para quando o workflow (progresso vs. identidade) tiver a sua própria UI |
| IA usada como atalho para decisões humanas | Segurança/Operacional | Controlo arquitetural (nenhuma ferramenta pode executar ação irreversível — ver `ARCHITECTURE_PROPOSAL.md` secção 8) + auditoria completa |
| Custo de APIs externas (Claude, rotas, geocoding) a escalar | Operacional | Limite/orçamento configurável antes de ativar cada integração real |

## Primeiro MVP recomendado

**Recomendação original desta análise:** Fase 0 + Fase 1 + Fase 4
(autenticação real, CRUD de projetos/workflow atrás de permissões reais, e
os 295 projetos reais migrados para staging com a fila de conflitos revista
e resolvida) — priorizava dados reais preservados e mapeados por ID
estável antes de qualquer funcionalidade nova.

**MVP efetivamente pedido e construído: Fase 0 + Fase 1 + Fase 1.5**
(dashboard/tarefas/workflow — ver acima), deliberadamente **sem** a Fase 4
(migração real). O negócio decidiu ter uma ferramenta internamente
utilizável (acompanhar projetos, tarefas, trabalhos pendentes) o mais cedo
possível, com dados sintéticos, antes de investir no esforço de revisão
manual que a migração real dos 295 projetos exige (reconciliação de PM,
resolução de conflitos — ver Fase 4 acima). Isto inverte a recomendação
original por decisão de negócio, não por descoberta técnica nova — os
riscos documentados da Fase 4 continuam válidos e por resolver quando essa
fase avançar.

**Consequência prática:** este MVP é demonstrável e usável com dados
sintéticos (seed), mas **nenhum projeto real está na plataforma ainda** —
até a Fase 4 avançar, esta app funciona em paralelo com o processo/
repositório legado, não o substitui.
