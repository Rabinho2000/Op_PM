# Runbook de migração de dados — 295 projetos reais

> Procedimento para migrar os dados reais do repositório do código legado
> (`files/atribuicoes.json` e ficheiros relacionados, fora deste
> repositório público — ver `docs/DECISIONS.md` D-015) para a base de
> dados de `staging`. Pressupõe `docs/STAGING_CHECKLIST.md` já concluído
> (staging a correr, PostgreSQL, autenticação real, 5 utilizadores
> provisionados, backups testados). **Nunca usar este runbook contra
> `production`** — ver secção 8 para como os dados chegam lá depois.
>
> Nenhum passo aqui usa dados reais nos exemplos — os exemplos de comando
> referem sempre `backend/fixtures/synthetic_legacy_export.json` para
> ilustrar a sintaxe; substituir pelo export real só ao executar de
> verdade, nunca commitar esse export neste repositório.

## 1. Pré-condições

- [ ] `docs/STAGING_CHECKLIST.md` completo e assinado.
- [ ] Backup completo da base de dados de staging feito imediatamente
      antes de começar (ver `docs/STAGING_CHECKLIST.md` secção 6).
- [ ] Export real do sistema legado disponível localmente no servidor
      onde o comando vai correr (nunca copiado para este repositório
      Git — `.gitignore` já bloqueia `files/`, mas a disciplina é sempre
      manual: nunca `git add` num ficheiro com dados reais).
- [ ] Confirmar `APP_ENV=staging` no ambiente onde o comando vai correr —
      `app/cli/ingest_staging.py` recusa-se a correr com
      `APP_ENV=production` (modo staging-only, D-037); é também assim que
      se garante que não se está, por engano, a apontar a produção.

## 2. Passo 0 — Reconciliação de PM prévia (antes de ingerir)

**Porquê antes, não depois:** o export legado tem, no mínimo, os 8 PMs
históricos conhecidos (`docs/DECISIONS.md` D-003) — alguns já não têm
`User` (conta de login), só `Person` (para preservar o histórico). Nomes
grafados de forma diferente entre o export e `people` (ex. "PM B"
vs. "PM B.") geram itens na fila de reconciliação
(`person_reconciliation_items`, D-023) que bloqueiam a promoção do(s)
projeto(s) correspondente(s) até serem resolvidos. Resolver isto **antes**
da ingestão principal reduz o número de projetos que ficam bloqueados por
`pm_unresolved` logo à primeira.

- [ ] Correr `app.migration.people_reconciliation.reconcile_pm_names`
      sobre o payload real (ainda sem promover nada — só regista a fila de
      reconciliação):
  ```python
  # a partir de backend/, com DATABASE_URL já apontado a staging
  from app.db import SessionLocal
  from app.migration.people_reconciliation import reconcile_pm_names
  import json

  db = SessionLocal()
  payload = json.load(open("/caminho/para/export_real.json", encoding="utf-8"))
  reconcile_pm_names(db, payload=payload)
  db.close()
  ```
- [ ] Rever a fila (`GET /api/migration/reconciliation-items?status=pending`,
      exige `migration.view` — Administrador ou Chefe de Operações) — para
      cada item:
  - **Ligar a uma `Person` existente** (`action: "link_existing"`) — o
    caso esperado para os 8 PMs históricos já conhecidos, mesmo sem
    `User` (login) associado.
  - **Criar uma `Person` nova** (`action: "create_new"`) — só para um
    nome genuinamente desconhecido (nunca visto no histórico), sempre
    sem `User` (histórica, sem acesso de login) a menos que seja também
    um dos 5 utilizadores ativos.
  - **Ignorar** (`action: "ignore"`) — quando o nome não corresponde a
    nenhuma pessoa real identificável (dado sujo do legado) e a decisão é
    prosseguir sem PM para os projetos afetados.
  - Quem tem autoridade para tomar cada decisão (Chefe de Operações?
    Administrador? confirmação do próprio PM em casos ambíguos?) é
    `DECISÃO NECESSÁRIA` — ver `docs/OPEN_QUESTIONS.md`, pergunta 17.
    Registar aqui, para auditoria própria deste runbook, quem resolveu
    cada item e porquê (fora deste documento — ex. numa folha de cálculo
    de acompanhamento da migração, não necessariamente no Git).
- [ ] Confirmar `GET /api/migration/reconciliation-items?status=pending`
      devolve o menor número possível de itens antes de avançar — não é
      exigido chegar a zero (alguns só se resolvem depois de ver os
      projetos concretos na secção 4), mas quanto menos, menos conflitos
      `pm_unresolved` na primeira ingestão.

## 3. Ingestão controlada

- [ ] Correr, a partir do servidor de staging (nunca via endpoint HTTP —
      D-026/D-037):
  ```bash
  cd backend
  python -m app.cli.ingest_staging \
    --file /caminho/para/export_real.json \
    --actor-email <email-de-quem-executa> \
    --source-system legacy_json
  ```
- [ ] Confirmar a saída — nunca escreve em `projects` (D-005/D-017), só em
      `import_batches`/`staging_project_records`:
  ```
  OK: import_batch_id=<uuid> (APP_ENV='staging', source_system='legacy_json')
  Resumo (nunca inclui dados de 'projects' — só do lote de staging):
    projects_seen: <N>
    ready_to_promote: <N>
    conflicts: <N>
    distinct_pm_names: <N>
    with_email: <N>
    with_contact: <N>
    with_coordinates: <N>
  ```
- [ ] Registar estas contagens (fora do Git — ex. na mesma folha de
      acompanhamento da secção 2) como a baseline desta ingestão —
      comparar com o número real de projetos esperado (295, ou o número
      real confirmado no momento — ver `docs/OPEN_QUESTIONS.md`,
      pergunta 12, sobre quantos anos de histórico migrar).
- [ ] Se `projects_seen` não bater com o número esperado de registos do
      export, parar e investigar antes de continuar (nunca assumir que
      "está aproximadamente certo").

## 4. Revisão da fila de conflitos

- [ ] `GET /api/migration/import-batches` (exige `migration.view`) para
      confirmar o `import_batch_id` da secção 3.
- [ ] `GET /api/migration/import-batches/{id}/records?status=conflict`
      para listar todos os registos em conflito. Motivos possíveis
      (`conflict_reason`):
  - `no_name` — registo sem nome de projeto; decidir manualmente
    (provavelmente `skip`, mas confirmar caso a caso — pode ser um dado
    corrompido que vale a pena investigar na origem antes de descartar).
  - `duplicate`/`ambiguous_match` — nome de projeto já existe (ou existe
    mais do que uma vez) — resolver com `POST
    /api/migration/staging-records/{id}/resolve-conflict`:
    - `action: "create_new"` — são projetos genuinamente diferentes com o
      mesmo nome.
    - `action: "link_existing"` com `target_project_id` — são o mesmo
      projeto; o alvo tem de estar entre os candidatos detetados
      automaticamente, a menos que se tenha a permissão
      `migration.link_arbitrary_project` e se forneça uma nota (D-030) —
      nunca ligar às cegas a um projeto arbitrário sem essa nota.
    - `action: "skip"` — rejeita o registo (nunca promovido).
  - `pm_unresolved` — nome de PM ainda sem correspondência clara, apesar
    do passo 2. Resolver com `action: "proceed_without_pm"` (decisão
    explícita de avançar sem PM) ou voltar à fila de reconciliação
    (`resolve_person_reconciliation`) e depois chamar
    `POST /api/migration/staging-records/{id}/retry-pm-resolution`.
- [ ] Repetir até `records_conflicted` chegar a 0 para este lote — nenhum
      registo em conflito pode avançar para promoção sem uma decisão
      humana explícita registada (nunca acontece sozinho — D-023).

## 5. Promoção explícita

- [ ] Confirmar mais uma vez o backup da secção 1 antes deste passo — é o
      único que escreve em `projects`.
- [ ] Para cada registo `ready_to_promote`:
  `POST /api/migration/staging-records/{id}/promote` (exige
  `migration.resolve`).
- [ ] **Recomendação operacional (mitiga uma limitação conhecida,
      documentada em `docs/DECISIONS.md` D-017):** promover todos os
      registos de **um lote** antes de ingerir o lote seguinte — a
      deteção de duplicados de `ingest_export` não cobre lotes diferentes
      ainda não promovidos entre si, só duplicados dentro do mesmo lote e
      contra `projects` já promovidos.
- [ ] Se a migração real vier em múltiplos exports/lotes (por fonte, por
      período, etc.), repetir os passos 2 a 5 lote a lote, nunca ingerir
      todos os lotes de uma vez sem promover o anterior primeiro.

## 6. Critérios para aprovar a migração (deste lote)

Todos têm de estar verdadeiros antes de considerar este lote migrado:

- [ ] `records_conflicted` = 0 para o lote (secção 4).
- [ ] Nenhum item pendente na fila de reconciliação de PM que bloqueie um
      projeto deste lote (`PersonReconciliationItem.status='pending'`
      relevante).
- [ ] Todos os registos `ready_to_promote` do lote foram promovidos
      (`status='promoted'`) ou explicitamente rejeitados (`status='rejected'`,
      via `action: "skip"`) — nenhum fica esquecido em
      `pending_review`/`conflict`.
- [ ] Amostragem manual: escolher pelo menos 10 projetos promovidos ao
      acaso e confirmar visualmente (`GET /api/projects/{id}` e
      `GET /api/projects/{id}/history`) que os campos batem com o export
      original (nome, PM, contacto, email, coordenadas, potência, notas
      legadas) e que o histórico regista a criação com `source=
      'import_legacy'`.
- [ ] Confirmar a contagem final: `GET /api/projects` (sem filtro) devolve
      o número total esperado de projetos ativos + inativos.

## 7. Confirmação de que os dados antigos continuam preservados

- [ ] **Nenhum projeto incompleto foi descartado ou inventado.** O modelo
      (`Project`) aceita todos os campos legados como opcionais de
      propósito — um projeto sem PM/email/coordenadas continua migrado,
      só com esses campos a `None` (ver `app/models/project.py`, secção
      "Fonte de verdade por campo"). Confirmar isto na amostragem da
      secção 6 (incluir deliberadamente pelo menos um projeto incompleto
      na amostra).
- [ ] **O payload de origem fica preservado verbatim** —
      `import_batches.raw_payload_json` e
      `staging_project_records.raw_record_json` nunca são reescritos
      depois da ingestão (ver `app/migration/staging.py`). Isto permite
      re-derivar/auditar os campos mapeados no futuro, mesmo que a lógica
      de normalização mude.
- [ ] **Os 8 PMs históricos continuam identificáveis mesmo sem login** —
      confirmar que cada `Person` ligada na secção 2 aparece corretamente
      como `pm_person_id`/no histórico dos projetos correspondentes,
      independentemente de ter ou não um `User` (D-003).
- [ ] Nenhum dado real deste processo entrou no Git deste repositório —
      confirmar `git status`/`git log` do repositório de código (não da
      base de dados) antes e depois da migração.

## 8. Promoção de staging para produção

**Este runbook migra dados só para a base de dados de `staging`** — nunca
diretamente para produção (`app/cli/ingest_staging.py` recusa-se a correr
com `APP_ENV=production`, D-037). Levar os dados já validados em staging
para a base de dados de produção é um passo de infraestrutura distinto,
feito **uma vez**, no momento do go-live (ver `docs/GO_LIVE_CHECKLIST.md`):

- **Mecanismo recomendado (a confirmar como decisão de infraestrutura —
  `DECISÃO NECESSÁRIA`, depende do alojamento escolhido, ainda por
  decidir — ver `docs/OPEN_QUESTIONS.md`):** um `pg_dump`/`pg_restore`
  das tabelas relevantes (`projects`, `project_history`,
  `project_external_ids`, `people`, `person_reconciliation_items` já
  resolvidos, etc.) da base de dados de staging já validada para a base
  de dados de produção, feito diretamente por quem tem acesso de
  administração a ambas — nunca através da aplicação, e nunca re-correndo
  `ingest_staging.py` contra produção (bloqueado por desenho).
- Isto significa que staging deve estar **completamente validado** (todas
  as caixas da secção 6 e 7 marcadas) antes do go-live — qualquer correção
  descoberta depois do `pg_dump`/`pg_restore` tem de ser aplicada duas
  vezes (staging e produção) ou só em produção diretamente, com o mesmo
  cuidado de auditoria.
- `users`/`roles`/`permissions`/`role_permissions` de produção são
  provisionados separadamente (`docs/STAGING_CHECKLIST.md` secção 5,
  repetido para o ambiente de produção com os mesmos 5 utilizadores reais)
  — nunca copiados de staging (staging pode ter utilizadores de teste
  adicionais que não devem chegar a produção).
