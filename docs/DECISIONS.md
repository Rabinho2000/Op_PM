# Decisões de arquitetura — Op_PM

> Registo das decisões tomadas como arquiteto/implementador desta fase, com a
> justificação. Onde a decisão depende de informação que só o negócio tem
> (orçamento, sistema Financial real, tenant M365), fica marcada
> `DECISÃO NECESSÁRIA` e listada também em `OPEN_QUESTIONS.md` — este
> documento não inventa essas respostas, só regista o que foi decidido
> tecnicamente dentro do que já estava definido.

## D-001 — Monólito modular, não microserviços

**Decisão:** um único backend (FastAPI/Python) organizado em módulos internos
(`models`, `adapters`, `security`, `migration`, `api`, `audit`), não vários
serviços independentes. Um frontend separado (SPA). Um processo de
worker/scheduler separado (D-013) que reutiliza o mesmo código, não um
serviço com a sua própria base de código.

**Porquê:** até 5 utilizadores, sem requisito de escala horizontal, a
complexidade operacional de microserviços (deployment, rede interna,
observabilidade distribuída) não se paga a si própria. Um monólito modular
bem separado por módulos é mais simples de operar, depurar e evoluir, e
ainda assim mantém fronteiras claras (nenhum módulo de UI fala diretamente
com um SDK externo, por exemplo — sempre através de `adapters`).

## D-002 — PostgreSQL como alvo; SQLite como conveniência de Fase 0

**Decisão:** o schema (SQLAlchemy + Alembic) é desenhado para correr em
PostgreSQL (staging/produção) e em SQLite (local/CI), usando só tipos
portáveis — o único ponto de adaptação é `app/db.py:GUID`, um
`TypeDecorator` que usa `UUID` nativo em PostgreSQL e `CHAR(36)` em SQLite.
`DATABASE_URL` por omissão aponta para um ficheiro SQLite local
(`./data/op_pm_local.db`).

**Porquê:** o ambiente onde esta fase foi construída não tem Docker nem
PostgreSQL instalados (confirmado antes de decidir — ver verificação de
ambiente no histórico da sessão). Instalar e operar um PostgreSQL real fica
fora do que é razoável pedir a um scaffold de Fase 0 correr sozinho. SQLite
elimina essa dependência sem comprometer o desenho do schema, porque nenhum
tipo específico de PostgreSQL é usado nos modelos.

**Importante:** isto é uma conveniência de desenvolvimento, não uma mudança
de arquitetura-alvo. `docs/ARCHITECTURE_PROPOSAL.md` continua a definir o
PostgreSQL como a única fonte de verdade operacional em staging/produção.
`requirements-postgres.txt` e `docker-compose.yml` preparam esse caminho;
`docker-compose.yml` não pôde ser validado neste ambiente por falta de
Docker — reveja antes da primeira utilização real.

## D-003 — `Person` separado de `User`

**Decisão:** `people` guarda qualquer ser humano referenciado no histórico
operacional; `users` guarda só quem tem conta de login (no máximo os
utilizadores ativos decididos pelo negócio). Um `Person` sem `User`
associado continua visível em `pm_person_id`, `created_by_person_id`, etc.

**Porquê:** cumpre literalmente "até 5 utilizadores ativos, mas não pode
apagar o histórico dos 8 PMs existentes" — sem esta separação, reduzir o
número de contas de login obrigaria a apagar ou a inventar um dono para o
histórico de quem perdesse o acesso.

## D-004 — IDs internos UUID; nome nunca é chave

**Decisão:** toda a entidade de negócio usa um UUID gerado em Python
(`app/db.py:new_uuid`) como chave primária. A correspondência com sistemas
externos (ClickUp, Financial, o próprio export legado) vive em
`project_external_ids` (`source_system`, `external_id`), com restrição de
unicidade composta — nunca se infere a partir do nome do projeto em tempo de
leitura.

**Porquê:** corrige diretamente o risco C-07 do sistema legado
(`clickup_sync.py` fazia correspondência por nome exato — ver
`.planning/codebase/CONCERNS.md` no repositório do código legado), onde
uma renomeação podia criar um projeto duplicado ou atualizar o registo
errado. Um teste (`tests/test_external_ids.py`) confirma explicitamente que
renomear um projeto não quebra a ligação ao ClickUp.

## D-005 — Toda a sincronização externa passa por staging com fila de conflitos

**Decisão:** `app/migration/staging.py` nunca escreve num projeto existente
por adivinhação. Um registo de origem sem `ProjectExternalId` prévio e com
nome ambíguo (mais do que um candidato, seja já na base de dados, seja
dentro do mesmo lote importado) fica em `staging_project_records` com
`status='conflict'`, para revisão humana — nunca é ligado automaticamente.

**Porquê:** é exatamente o requisito "detetar duplicados e correspondências
ambíguas" + "criar uma fila de conflitos para revisão manual". Testado em
`tests/test_staging_persistence.py`, incluindo o caso de dois registos do
mesmo lote partilharem nome.

**Revisto na revisão de hardening da Fase 0 — ver D-017**: esta decisão
mantém-se, mas o desenho original (`dry_run`/`apply` numa única função, que
nunca persistia nada em `dry_run`) foi substituído por um staging
persistente com promoção explícita, porque a ingestão em si já não tem
nada de arriscado a simular — nunca toca em `projects`.

## D-006 — Histórico append-only aplicado por convenção nesta fase

**Decisão:** `project_history` não tem `updated_at` (testado explicitamente
— `test_project_history_has_no_updated_at_field`) e só é escrito através de
`app/audit/log.py:record_project_change`, que nunca faz UPDATE/DELETE.

**Limitação conhecida:** nesta fase, isto é imposto pela disciplina do
código (um serviço mal escrito no futuro *poderia* tecnicamente fazer
UPDATE na tabela). Reforçar isto com uma regra ao nível da base de dados
(trigger ou permissão que impede UPDATE/DELETE na tabela para o utilizador
aplicacional) é trabalho recomendado para quando a base de dados real for
PostgreSQL em produção — ver `docs/PLAN.md`, plano de segurança.

## D-007 — Workflow como dados em base de dados, não constantes no código

**Decisão:** `phases` → `workflow_stages` → `workflow_subtasks` são tabelas,
com `code` como chave estável e `id` (UUID) nunca reindexado por posição.
`project_stage_progress`/`project_subtask_progress` referenciam esses IDs
por chave estrangeira — nunca uma string posicional como `"12.3"`.

**Porquê:** corrige o padrão legado documentado em
`.planning/codebase/CONCERNS.md` (C-18): no sistema anterior, `STAGES` era
uma constante JavaScript em `solcor-gestao.html`, e tanto
`AtualizacoesSemanais_v6/app.py` como `mark_certified_done.py` duplicavam
essa estrutura separadamente (um por regex sobre o próprio HTML). Uma
mudança de fases exigia edição sincronizada em três sítios.

**Nota sobre os dados semeados:** o seed de desenvolvimento
(`app/migration/seed_dev.py`) usa fases/etapas **genéricas e fictícias**
com a mesma forma do processo legado (6 fases), não o texto real do
processo da empresa nem nomes de pessoas reais — este repositório é
público (ver D-015).

## D-008 — Permissões só no servidor, nunca "papel" escolhido no cliente

**Decisão:** `roles`/`permissions`/`role_permissions`/`user_roles` como
tabelas; `app/security/permissions.py:load_auth_context` calcula as
permissões efetivas de um utilizador a partir da base de dados a cada
pedido. `can_edit_project`/`can_view_project` verificam a permissão e, para
PMs, o `pm_person_id` do projeto — nunca um valor vindo do frontend.

**Porquê:** corrige diretamente C-03 do sistema legado ("PM" vs. "Chefe de
operações" era um `STATE.role` local, sem qualquer verificação real).
Testado em `tests/test_permissions.py`, incluindo o caso de um utilizador
sem papel associado não herdar nenhuma permissão.

## D-009 — Integrações só através de interface + fábrica de adapters

**Decisão:** `Claude`, `Microsoft Graph`, `ClickUp` e `Financial` são
acedidos exclusivamente através de uma interface (`Protocol`) definida em
`app/adapters/<integração>/base.py`. `app/adapters/__init__.py` decide qual
implementação devolver a partir das flags de configuração — hoje, sempre
mock ou fallback local; ativar uma flag `*_ENABLED` sem a implementação real
correspondente levanta `NotImplementedError` de propósito, em vez de cair
silenciosamente para o mock.

**Porquê:** nenhuma chamada real pode "escapar" por acidente nesta fase, e
trocar mock por implementação real mais tarde não exige tocar em código
fora do respetivo pacote de adapter.

## D-010 — Fallback do Graph nunca envia nem publica nada real

**Decisão:** `LocalFallbackGraphAdapter` escreve sempre um ficheiro `.eml`
ou `.ics` local. Mesmo os métodos `send_mail`/`create_event` — que exigem
`approved_by` preenchido — só gravam o ficheiro; nunca há entrega real.

**Porquê:** cumpre as regras de segurança do pedido ("não implementar envio
real de emails nem criação real de eventos nesta fase") de forma estrutural
— não é possível enviar um email real através deste adapter, seja qual for
o estado de aprovação, porque a implementação simplesmente não tem nenhum
código de entrega de rede.

## D-011 — Financial: modo CSV real além do mock

**Decisão:** além do mock, existe `CsvFinancialAdapter`, uma implementação
real (sem rede) que lê um CSV com colunas fixas
(`external_project_ref,category,amount,currency,reference`). Modos `api` e
`excel` ficam definidos na interface mas não implementados.

**Porquê:** o sistema Financial real não está identificado
(`OPEN_QUESTIONS.md`, pergunta bloqueante). Um conector CSV é o caminho mais
provável de funcionar no primeiro dia, independentemente da resposta final
— muitos sistemas financeiros exportam CSV mesmo sem API.

## D-012 — Autenticação: utilizador de desenvolvimento explícito, não Entra ID ainda

**Decisão:** `AUTH_ENABLED=false` por omissão. Com essa flag, o backend
resolve o "utilizador atual" a partir do cabeçalho `X-Dev-User-Email`, que
tem de corresponder a um `User` já semeado — nunca cria um utilizador a
partir do cabeçalho. Com `AUTH_ENABLED=true`, o código levanta
`NotImplementedError` de propósito.

**Porquê:** permite testar toda a camada de permissões/API sem depender de
um tenant Microsoft 365 configurado (que ainda não foi confirmado — ver
`OPEN_QUESTIONS.md`), sem fingir que existe autenticação real.

## D-013 — Worker/scheduler: desenhado, não implementado nesta fase

**Decisão:** as tarefas demoradas (sincronização ClickUp, importação
Financial, indexação documental) devem correr num processo separado do
backend web, que reutiliza os mesmos modelos SQLAlchemy e adapters — nunca
duplica lógica. Recomenda-se um scheduler leve (ex. APScheduler dentro de
um processo Python dedicado, ou uma tarefa cron do sistema operativo a
invocar um comando CLI do backend) em vez de uma fila pesada tipo
Celery+Redis, dado o volume esperado (5 utilizadores, sincronizações pouco
frequentes). Esta é uma recomendação revisível se o volume real justificar
uma fila de tarefas mais robusta.

**Porquê não está implementado já:** nesta fase não existe nenhuma tarefa
real para agendar — todas as integrações estão em modo mock/local (D-009).
Construir um processo de worker antes de haver algo real para ele fazer
seria trabalho especulativo. `app/migration/staging.py` já está desenhado
para ser chamado tanto por um endpoint da API como por um futuro comando de
worker, sem alteração.

## D-014 — CI com SQLite e PostgreSQL

**Decisão original:** o workflow em `.github/workflows/ci.yml` corria só
contra SQLite. **Revisto na revisão de hardening (ver D-021):** passou a
ter dois jobs de backend — um contra SQLite (rápido, sem serviços) e outro
contra um serviço PostgreSQL do próprio GitHub Actions — mais o build do
frontend.

**Porquê:** SQLite continua a ser o suficiente para desenvolvimento local
rápido, mas só correr testes contra SQLite escondia divergências de
comportamento entre motores (ex. `Numeric`, tipos de data, `batch_alter_table`
nas migrações) até só serem descobertas em staging/produção — já tarde
demais. Ver D-021 para o detalhe do job novo.

## D-015 — Repositório mantém-se público

**Decisão:** conforme instrução explícita do utilizador nesta sessão, o
repositório `Op_PM` mantém-se público. Isto substitui a pergunta bloqueante
nº 1 do `docs/OPEN_QUESTIONS.md` anterior ("continuar público ou passar a
privado") — a resposta é: público, com a regra absoluta de nunca conter
dados reais, segredos, ou exports de produção, reforçada por `.gitignore`,
fixtures exclusivamente sintéticas, e revisão manual antes de cada commit.

## D-016 — Ambiente Python usado para validar esta fase

**Nota técnica (não uma decisão de arquitetura):** o ambiente onde esta fase
foi construída e testada tem Python 3.14 instalado; o CI usa 3.12 para
maior estabilidade/reprodutibilidade num runner padrão. Ambas as versões
foram confirmadas capazes de instalar todas as dependências, incluindo o
driver PostgreSQL opcional (`psycopg[binary]`).

## Revisão de hardening da Fase 0 (antes de iniciar a Fase 1)

As decisões D-017 a D-021 documentam a revisão de hardening pedida
explicitamente antes de avançar para a Fase 1 — nenhuma delas liga
qualquer integração real (Entra ID, Graph, ClickUp, Financial, Claude
continuam todos em modo mock/fallback).

## D-017 — Staging persistente + promoção explícita substitui `dry_run`/`apply`

**Decisão:** o mecanismo de migração deixou de ser uma única função
`run_staging_import(mode='dry_run'|'apply')` (que nunca persistia nada em
`dry_run`) e passou a três etapas distintas e persistentes, em
`app/migration/staging.py`:

1. `ingest_export` — lê o export, cria `ImportBatch` +
   `StagingProjectRecord`. Sempre persiste (commit imediato). Nunca toca em
   `projects`.
2. `resolve_conflict` — só para registos com `status='conflict'`; decide
   `create_new`/`link_existing`/`skip`.
3. `promote_staging_record` — só isto escreve em `projects`
   (criação ou atualização), sempre com entradas de `project_history` por
   campo alterado.

Mais `rollback_promotion`, que desfaz uma promoção: inativa
(`is_active=False`, nunca `DELETE`) se a promoção tinha criado o projeto;
reaplica os valores anteriores campo a campo (via `project_history`,
correlacionado por `related_staging_record_id` — nunca por adivinhação de
texto) se a promoção tinha atualizado um projeto já existente.

**Porquê:** o desenho anterior confundia duas coisas distintas —
"experimentar sem consequência" (que já não fazia sentido, porque a
ingestão nunca tocava em `projects`) e "aplicar de vez" — numa única
função com um parâmetro `mode`. Separar em três funções/tabelas torna cada
etapa auditável, testável e revertível isoladamente, e cumpre à letra o
pedido: "separa: ingestão do export; revisão de conflitos; promoção
explícita para os dados canónicos. Todas as promoções devem gerar
auditoria e permitir rollback."

**Âmbito conhecido:** a deteção de duplicados por nome só olha para
`projects` já promovidos e para o lote atual — não deteta dois lotes
diferentes, ainda não promovidos, com o mesmo nome. Aceitável para Fase 0
(só dados sintéticos); antes de uma migração real, promover um lote de
cada vez (ou reforçar a deteção) evita este cenário.

## D-018 — `Numeric`/`Decimal` para todos os valores monetários

**Decisão:** `cost_lines.amount` e `material_request_items.unit_price`
passaram de `Float` para `Numeric(12, 2)` (`decimal.Decimal` em Python).
`FinancialCostRecord.amount` (adapter) e `CsvFinancialAdapter` seguiram a
mesma mudança — o CSV é lido com `Decimal(str)` diretamente, nunca
`float(...)` a meio do caminho.

**Porquê:** `float` não representa exatamente a maioria dos valores
decimais em binário (`0.1 + 0.1 + 0.1 != 0.3`) — inaceitável para dinheiro.
`Numeric` é portável entre SQLite e PostgreSQL sem tipo customizado (ao
contrário de UUID, não precisou de um `GUID`-like `TypeDecorator`). Testado
em `tests/test_monetary_precision.py` com um caso que demonstra o erro que
`float` cometeria.

**Nota:** quantidades (`inventory_movements.quantity`,
`material_request_items.quantity`, `inventory_items.min_stock`)
mantiveram-se `Float` — não são valores monetários, e o pedido delimitou
explicitamente "valores monetários".

## D-019 — Campos legados adicionais como texto, não `Date`/`Integer`

**Decisão:** os novos campos do `Project` vindos do IDF legado
(`upac_connection_date_raw`, `award_year_raw`, e também `power_raw`) são
`String`, não `Date`/`Integer` — apesar de os nomes sugerirem esses tipos.

**Porquê:** o formato real destes campos no export legado não foi
confirmado nesta fase (o repositório do código legado não foi tocado para
esta revisão). Tipar como `Date`/`Integer` e falhar ao importar um valor
real com formato inesperado seria pior do que preservar o texto — cada um
tem também um campo companheiro com o melhor esforço de interpretação
(`start_date` como `Date`, `power_kwp` como `float`) quando a extração é
possível, sem nunca perder o original. Revisitar quando os formatos reais
forem confirmados.

## D-020 — Duas barreiras independentes contra configuração insegura em staging/produção

**Decisão:**

1. `Settings` (pydantic) valida, à construção — logo, ao arrancar a
   aplicação — que `APP_ENV in ('staging', 'production')` implica
   `AUTH_ENABLED=true`, `SECRET_KEY` diferente do valor de desenvolvimento,
   e `DATABASE_URL` não-SQLite. Viola qualquer uma → `ValidationError`,
   processo não arranca.
2. `get_current_user` (o mecanismo de utilizador de desenvolvimento)
   verifica `settings.app_env` a cada pedido, independentemente da
   validação acima — defesa em profundidade para o caso (não esperado em
   condições normais) de a aplicação correr com `APP_ENV=local`/`test` mas
   ligada por engano a infraestrutura de staging/produção.

**Porquê:** o pedido foi explícito — "impede que a aplicação arranque" E
"o cabeçalho X-Dev-User-Email deve funcionar apenas em local/test" são duas
garantias distintas; a primeira sozinha não cobre o cenário de
configuração parcialmente incorreta (`APP_ENV` errado, mas o resto certo).
Testado em `tests/test_config_hardening.py`.

## D-021 — CI: job PostgreSQL adicional, sem remover o job SQLite

**Decisão:** `.github/workflows/ci.yml` ganhou um segundo job de backend
(`backend-postgres`), que sobe um serviço `postgres:16` no próprio runner
do GitHub Actions, corre `alembic upgrade head` e `pytest -q` contra
`DATABASE_URL=postgresql+psycopg://...`, com `requirements.txt` +
`requirements-postgres.txt` instalados. O job SQLite original mantém-se.

**Porquê:** cumpre o pedido diretamente; garante que a migração
(`batch_alter_table`, `Numeric`, `GUID`) e a suite de testes funcionam
também no motor de produção-alvo, não só em SQLite.

**Tentativa real de validação local (revisão de hardening seguinte) e o
que bloqueou:** sem Docker disponível (D-002), tentou-se instalar
PostgreSQL embebido via o pacote `pgserver` (binários portáveis, sem
serviço de sistema, sem admin) — foi necessário instalar Python 3.12 à
parte (só há wheels `pgserver` até cp312), o que funcionou. O `initdb`
do PostgreSQL embebido, porém, falha sempre neste computador com
`FATAL: invalid byte sequence for encoding "UTF8"`, independentemente do
diretório de dados escolhido ou de `--locale`/variáveis de ambiente
`USERNAME` sobrepostas: o binário lê o nome da conta Windows atual
("Sérgio", com acento) através de uma API que não faz a transcodificação
correta para UTF-8 antes de o passar ao script de bootstrap SQL — um
problema conhecido de builds de PostgreSQL para Windows com nomes de
utilizador não-ASCII, não um problema no código deste repositório.
Não foi contornável em tempo razoável sem alterar a conta Windows do
utilizador (fora de questão) ou compilar um binário próprio.

Conclusão: o job continua **não executado localmente**, mas por uma
limitação confirmada do ambiente local (não do código), depois de uma
tentativa real e documentada — não apenas por falta de Docker. A primeira
execução real continua a ficar para o GitHub Actions, onde os runners
`ubuntu-latest` não têm este problema (contas de serviço Linux, sempre
ASCII).

## D-022 — `conftest.py` nunca sobrescreve `DATABASE_URL`; dialect verificado explicitamente

**Decisão:** `tests/conftest.py` só cria/gere um ficheiro SQLite temporário
quando `DATABASE_URL` **não** está definido no ambiente. Quando está
definido — pelo CI (`backend-postgres`) ou por um dev a testar contra
PostgreSQL manualmente — é respeitado tal como está, nunca sobreposto.
Além disso, `_prepare_database` (fixture de sessão, `autouse=True`) chama
`pytest.exit(...)` — abortando toda a sessão de testes, antes de qualquer
teste correr — se a variável `EXPECTED_DB_DIALECT` estiver definida e não
corresponder ao dialect do motor realmente ligado
(`engine.dialect.name`). `tests/test_database_dialect.py` acrescenta um
resultado nomeado e visível para a mesma garantia.
`.github/workflows/ci.yml` define `EXPECTED_DB_DIALECT=postgresql` no job
`backend-postgres` e `EXPECTED_DB_DIALECT=sqlite` no job `backend-sqlite`.

**Porquê — bug real corrigido, não só um risco teórico:** a versão
anterior de `conftest.py` fazia sempre
`os.environ["DATABASE_URL"] = f"sqlite:///{...}"` incondicionalmente, ANTES
de qualquer teste correr — isto significava que o job `backend-postgres`
do CI (que define `DATABASE_URL=postgresql+psycopg://...` no ambiente)
teria essa variável **imediatamente substituída por SQLite** assim que
`pytest` importasse `conftest.py`, e a suite inteira corria — e "passava"
— contra SQLite, sem nunca tocar em PostgreSQL. O job ficaria verde sem
validar nada do que dizia validar. Confirmado e corrigido nesta revisão,
com teste de regressão (`test_dev_header_mechanism_*` e a suite geral
correndo com um `DATABASE_URL` externo antes e depois da correção).

## D-023 — Reconciliação de PM como etapa explícita antes da promoção de projetos

**Decisão:** `app/migration/people_reconciliation.py` introduz uma etapa
— chamada antes de `ingest_export`, mas cujo efeito de bloqueio se aplica
durante toda a ingestão/promoção — com duas responsabilidades:

1. `reconcile_pm_names(db, payload=...)`: para cada nome de PM distinto no
   export, verifica se corresponde a exatamente um `Person` conhecido; se
   não (zero ou mais do que uma correspondência), regista um
   `PersonReconciliationItem` (`status='pending'`) — nunca cria nem liga
   uma `Person` sozinho. Idempotente por nome normalizado.
2. `resolve_person_reconciliation(...)`: a única forma de sair de
   `pending` — `link_existing` (liga a uma `Person` já existente),
   `create_new` (cria uma `Person` nova, **sempre `is_active=False` e sem
   `User`** — nunca dá login automaticamente), ou `ignore` (decisão
   explícita de não associar nenhuma pessoa a este nome).

`app/migration/staging.py` usa `classify_pm_name` (a mesma função usada
pela reconciliação) em três pontos, para nunca haver duas lógicas de
decisão divergentes sobre o que conta como "PM resolvido":

- `ingest_export`: se um registo tem PM presente mas não resolvido, fica
  `status='conflict'`, `conflict_reason='pm_unresolved'` — mesmo que a
  parte de identidade do projeto (nome, sem duplicados) esteja
  perfeitamente limpa. A resolução do projeto (`create_new`/
  `update_existing`) fica já calculada e guardada, para não se perder
  quando o PM for resolvido.
- `resolve_conflict`: ganhou a ação `proceed_without_pm` (só válida para
  `conflict_reason='pm_unresolved'`) — decisão humana explícita de avançar
  sem PM. Quando um conflito de NOME de projeto é resolvido
  (`create_new`/`link_existing`) e o registo tinha também um PM por
  resolver, o registo não salta para `ready_to_promote`: volta a ficar
  `conflict`/`pm_unresolved`, porque o problema de PM nunca tinha sido
  endereçado (só o de nome). Ambos os caminhos passam pelo mesmo
  `_finalize_status_given_pm`, para nunca divergirem.
- `promote_staging_record`: verifica **outra vez**, já na promoção, se o
  PM está resolvido ou explicitamente dispensado — mesmo que o registo
  tenha chegado a `ready_to_promote` por alguma via que não passasse pelas
  barreiras normais (testado explicitamente forçando o estado
  diretamente). Esta é a garantia final e não contornável de "nunca
  promover silenciosamente um projeto com PM conhecido mas não resolvido".
- `retry_pm_resolution`: reclassifica um registo bloqueado por
  `pm_unresolved` depois de a reconciliação resolver o nome em causa —
  desbloqueia sem repetir a ingestão.

**Porquê:** cumpre os quatro requisitos pedidos diretamente — preservar
todos os PMs históricos como `Person` já era uma propriedade do modelo
(D-003), aqui reforçada ao nunca apagar/ignorar um `Person` existente;
`User` só é criado por decisão humana separada (a reconciliação nunca cria
um); nomes desconhecidos/ambíguos vão sempre para a fila
`person_reconciliation_items`; e a barreira em `promote_staging_record` é
estrutural, não contornável por um caminho alternativo dentro do código.
Testado em `tests/test_people_reconciliation.py` (16 testes) e no ajuste
correspondente em `tests/test_staging_persistence.py`.

**Âmbito conhecido:** tal como a deteção de duplicados de projeto (D-017),
`reconcile_pm_names` só vê o `payload` que lhe é passado — não deteta
proativamente nomes de PM pendentes de lotes anteriores ainda por
reconciliar; isso já é coberto, na prática, porque `classify_pm_name`
consulta sempre `person_reconciliation_items` para decisões já tomadas
(`ignored`/resolvidas), e um item `pending` de um lote anterior continua
`pending` e continua a bloquear qualquer registo com esse nome, em
qualquer lote.

## Âmbito deliberadamente deixado de fora da Fase 0

- Métodos de ficheiros (SharePoint/OneDrive) na interface do `GraphAdapter`
  — só existem hoje `get_availability`/`create_draft_email`/`send_mail`/
  `create_event`. Operações de documentos entram quando a Fase da biblioteca
  documental (ver `docs/PLAN.md`) for trabalhada.
- Migração dos 295 projetos reais — só a mecânica (ingestão, staging, IDs
  externos, conflitos, promoção explícita, rollback, checksum) está
  implementada e testada com dados sintéticos.
- Deteção de duplicados entre lotes de importação diferentes ainda não
  promovidos (ver D-017, âmbito conhecido).
- Regra de base de dados (trigger/permissão) que impeça UPDATE/DELETE em
  `project_history` — continua aplicada só por convenção de código (D-006).

# Fase 1 — Autenticação real, CRUD, reconciliação por API, frontend

Nenhuma destas decisões liga uma integração externa real — Graph, ClickUp,
Financial e Claude continuam mock/fallback (D-009 a D-011); os 295
projetos reais continuam por migrar (D-005/D-017).

## D-024 — Validação real de token Entra ID, dupla barreira contra o modo mock

**Decisão:** `app/security/entra_auth.py` valida tokens OIDC do Microsoft
Entra ID (assinatura RS256, `iss`, `aud`, `exp`/`iat`, claims obrigatórias)
com duas implementações atrás da mesma interface:

- `RealEntraTokenValidator`: busca o JWKS do tenant real via rede
  (`PyJWKClient`, com cache), issuer/audience derivados de
  `ENTRA_TENANT_ID`/`ENTRA_CLIENT_ID` (ou explícitos via
  `ENTRA_ISSUER`/`ENTRA_AUDIENCE`/`ENTRA_JWKS_URL`).
- `MockEntraTokenValidator`: valida contra uma chave RSA de teste fixa,
  gerada uma única vez para este repositório, embutida no código — sem
  qualquer chamada de rede. **Não é um segredo real**: nunca validaria
  nada vindo de um Entra ID de verdade (issuer/audience diferentes), serve
  só para assinar/validar tokens sintéticos em `issue_mock_token` (testes).

`Settings.entra_validation_mode` (`'real'` por omissão) escolhe qual —
`app/security/entra_auth.py:get_token_validator` é o único ponto que
decide isto, nunca instanciado diretamente fora daí.

`get_current_user` (app/security/current_user.py) liga o `oid` do token a
`User.entra_object_id`; se ainda não houver ligação, tenta uma ligação
"just-in-time" por email — só para um `User` já existente, ativo, sem
`entra_object_id`, e só se exatamente um corresponder (nunca cria um
`User` novo a partir de um token; provisionamento continua um passo
administrativo separado). Ambíguo ou inexistente → 401 genérico (nunca
revela ao chamador HTTP qual validação específica falhou — assinatura,
issuer, audience, ou validade — só ao log do servidor).

**Porquê a dupla barreira ser necessária:** `ENTRA_VALIDATION_MODE=mock`
nunca pode ser alcançável em staging/produção, senão qualquer token
assinado com a chave de teste (pública neste repositório) autenticaria
como qualquer utilizador. `Settings._enforce_hardening_in_non_local_envs`
(D-020) foi estendida para também exigir `ENTRA_VALIDATION_MODE='real'`
nesses ambientes — a aplicação recusa-se a arrancar caso contrário.
Testado em `tests/test_config_hardening.py` (bloqueio de arranque) e
`tests/test_auth_entra.py` (12 testes: token válido, ligação por email,
segunda autenticação já ligada por `entra_object_id`, assinatura inválida,
token malformado, `Authorization` em falta, token expirado, audience
errada, issuer errado, utilizador sem papel, email/object_id
desconhecidos, e X-Dev-User-Email nunca é sequer lido quando
`AUTH_ENABLED=true`).

## D-025 — CRUD de projetos: permissões e histórico só na camada de serviço

**Decisão:** `app/services/projects.py` é o único sítio que escreve num
`Project` a partir da API (`app/api/routes_projects.py`). `update_project`
verifica `can_edit_project` (D-008) antes de tocar em qualquer campo, e usa
`model_dump(exclude_unset=True)` para só considerar campos explicitamente
presentes no pedido — um campo omitido nunca é tocado, um campo presente
com `null` limpa-o explicitamente. Cada campo efetivamente alterado gera
uma entrada de `project_history` (`source='ui'`,
`changed_by_person_id=<pessoa do utilizador autenticado>`) através do
mesmo `record_project_change` já usado pela migração (D-005) — nunca uma
escrita silenciosa, e um valor igual ao anterior não gera entrada (mesma
regra que corrige C-08 desde a Fase 0).

`GET /api/projects` e `GET /api/projects/{id}` filtram por
`can_view_project`/`visible_projects_query` — um PM sem `project.view_all`
só vê os seus próprios projetos, nunca recebe uma lista completa filtrada
no cliente. Não existe nenhum endpoint que escreva em `project_history`
diretamente — só leitura (`GET /api/projects/{id}/history`).

`clickup_status_mirror` fica deliberadamente fora de `ProjectUpdate` — é
espelho só-de-leitura do ClickUp (fonte de verdade externa), nunca editado
pela UI desta plataforma.

Testado em `tests/test_project_api.py`: PM só edita o seu próprio projeto
(403 no outro), Chefe de Operações edita qualquer um, Comercial só lê
(403 em qualquer PATCH), histórico criado por cada campo alterado, nenhuma
entrada gerada quando o valor não muda, pedido não autenticado rejeitado.

## D-026 — Endpoints de migração: consulta e resolução, nunca ingestão

**Decisão:** `app/api/routes_migration.py` expõe leitura
(`import-batches`, `staging-records`, `reconciliation-items`) e as ações
de resolução já existentes em `app/migration/staging.py`/
`people_reconciliation.py` (`resolve-conflict`, `promote`, `rollback`,
`retry-pm-resolution`, `reconciliation-items/{id}/resolve`) — mas
**nenhum endpoint para `ingest_export`**. Duas novas permissões:
`migration.view` e `migration.resolve`, concedidas a Administrador e
Chefe de Operações (a recomendação por omissão da pergunta aberta nº 17).

**Porquê não expor ingestão via API:** a ingestão de um export real é uma
operação controlada e pouco frequente (por lote, não por pedido HTTP
casual), e expor um endpoint para ela convidaria a experimentar com dados
reais antes de tempo — contrariando a regra explícita desta fase ("não
migrar ainda os 295 projetos reais"). Quando a fase de migração real
chegar (Fase 2 no roadmap desta altura, renumerada para Fase 4 em
docs/PLAN.md — ver D-037), a ingestão real continua a ser um
comando/script operado deliberadamente (`app/cli/ingest_staging.py`),
não um botão da UI.

Testado em `tests/test_migration_api.py`: bloqueio de promoção com
registo em conflito (incluindo `pm_unresolved`), resolução de PM
desconhecido via API seguida de promoção bem-sucedida,
`proceed_without_pm` via API, e que um PM sem `migration.view` não
consegue ver nem resolver nada de migração.

## D-027 — Frontend Fase 1: login (mecanismo de dev), lista, detalhe, reconciliação

**Decisão:** primeira interface web funcional — `Login` (guarda o email de
desenvolvimento em `localStorage`, nunca um token — ver nota abaixo),
`ProjectsList` (filtros por PM/estado/pesquisa), `ProjectDetail` (edição
dos campos permitidos + histórico ao lado), `ReconciliationQueue` (liga/
cria/ignora um nome de PM pendente). `react-router-dom` para a navegação;
`RequireAuth` redireciona para `/login` sem um email de dev guardado.

**Login com Entra ID real não foi ligado ao frontend nesta fase** — exigia
MSAL.js e valores reais de app registration (tenant ID, client ID) que
este repositório não tem (ver `docs/OPEN_QUESTIONS.md`, pergunta 1); o
ecrã de login diz isto explicitamente ao utilizador, em vez de fingir uma
opção que não funciona. O backend já valida tokens reais (D-024) — falta
só a configuração do tenant para o MSAL.js ter com quem falar.

Validado manualmente ponta-a-ponta (backend + frontend a correr
localmente): login, listagem com filtros, edição de um projeto com
histórico a aparecer imediatamente com autor/fonte corretos, fila de
reconciliação vazia a renderizar sem erros, logout a limpar a sessão.

## Âmbito deliberadamente deixado de fora da Fase 1

- Endpoints de workflow (`project_stage_progress`/`project_subtask_progress`)
  — só os campos de identidade do `Project` são editáveis via API nesta
  fase; progresso de checklist fica para quando o workflow (fases/etapas)
  ganhar a sua própria UI.
- Ingestão real de projetos via API (D-026, decisão deliberada).
- Testes de UI automatizados (Playwright/Cypress) — validação desta fase
  e da revisão de hardening seguinte (D-028 a D-031) foi manual, via
  navegador, documentada acima e abaixo.

> As duas lacunas identificadas nesta lista na versão anterior deste
> documento — "restrição de campos por perfil" e "autenticação real
> ponta-a-ponta (MSAL.js)" — foram fechadas pela revisão de hardening a
> seguir (D-028 e D-031, respetivamente). O tenant Microsoft 365 real
> continua por confirmar (pergunta bloqueante nº 1) — D-031 deixa o login
> real MSAL implementado e configurável, mas sem um `VITE_ENTRA_CLIENT_ID`/
> `VITE_ENTRA_TENANT_ID`/`VITE_ENTRA_API_SCOPE` reais para lhe dar
> credenciais, o botão fica visivelmente desativado.

## Revisão de hardening da Fase 1 (antes de iniciar a Fase 2)

As decisões D-028 a D-031 documentam a revisão de hardening pedida
explicitamente antes de avançar para a Fase 2 (a partir do commit
`401ebf6`) — nenhuma liga qualquer integração real (Entra ID, Graph,
ClickUp, Financial e Claude continuam todos em modo mock/fallback) nem
migra qualquer um dos 295 projetos reais.

## D-028 — Permissões de edição de projeto: lista explícita de campos por perfil, aplicada no servidor

**Decisão:** `project.edit_all` (Chefe de Operações/Administrador) continua
a poder alterar qualquer campo de `ProjectUpdate`. Quem só tem
`project.edit_own_progress` (PM, no seu próprio projeto) fica limitado a
uma lista explícita — `PM_EDITABLE_PROJECT_FIELDS` em
`app/security/project_fields.py` (`lat`, `lon`, `power_kwp`, `power_raw`,
`start_date`, `role`, `equipment_notes`, `injection_notes`, `om_notes`,
`commercial_assumptions`, `upac_connection_date_raw`, `award_year_raw`,
`notes`) — nunca pode tocar em `name`, `client_name`, `client_contact`,
`client_email`, `address`, `pm_person_id`, `is_active`,
`upac_registration` ou `m2m_card` (`ADMIN_ONLY_PROJECT_FIELDS`, a mesma
lista documentada por oposição, para nunca haver um campo "esquecido" no
meio).

**Desenho deliberado — allowlist, não denylist:** `PM_EDITABLE_PROJECT_FIELDS`
é a lista que importa; `ADMIN_ONLY_PROJECT_FIELDS` existe só para um teste
confirmar que as duas juntas cobrem exatamente `ProjectUpdate.model_fields`
(nenhum campo esquecido de um lado ou do outro). Um campo novo adicionado
a `ProjectUpdate` no futuro e esquecido nesta lista fica automaticamente
só para quem tem `project.edit_all` — nunca editável por omissão.

**Aplicado inteiramente no servidor**, independentemente do frontend:
`update_project()` (`app/services/projects.py`) calcula
`disallowed_fields = alterações pedidas − PM_EDITABLE_PROJECT_FIELDS`
depois de confirmar que o ator pode editar o projeto mas antes de
escrever qualquer campo — um pedido com um único campo fora da lista é
rejeitado por inteiro (nenhum efeito secundário parcial), com a mensagem
a nomear os campos recusados.

**Testes (`tests/test_project_field_permissions.py`, 12 casos):**
disjunção e cobertura total das duas listas contra `ProjectUpdate`; PM
edita um campo permitido (200); PM tenta cada campo administrativo
individualmente (403, parametrizado); PM tenta reatribuir `pm_person_id`
(403); pedido misto (um campo permitido + um proibido) rejeitado por
inteiro, confirmado sem qualquer alteração na BD nem entrada de
histórico; Chefe de Operações edita campos administrativos (200); PM
tenta editar um projeto que não é seu, mesmo só com campos permitidos
(403).

## D-029 — Reforço da autenticação Entra ID: `oid` obrigatório, tenant/scp/`nbf` validados, JIT linking configurável e auditado, validador cacheado

**Decisão:**

- **`oid` obrigatório, nunca `sub` como identidade persistente** — um
  token sem `oid` (ou com `oid` vazio) é sempre recusado; `sub` deixou de
  ser sequer consultado para identidade (`REQUIRED_CLAIMS` inclui `oid`).
- **Tenant, issuer, audience, assinatura, expiração e `nbf`** — issuer/
  audience/assinatura/`exp` já eram validados desde D-024; `nbf`, quando
  presente, é validado pelo comportamento por omissão do PyJWT (nunca
  desativado); `tid` é comparado a `ENTRA_TENANT_ID` quando este está
  configurado (sem tenant configurado, `tid` não é verificado —
  comportamento existente, preservado deliberadamente).
- **Só tokens delegados** — `_validate_delegated_token` exige a claim
  `scp` não vazia; um token só com `roles` (aplicação, não delegado) é
  recusado. `ENTRA_REQUIRED_SCOPE`, quando configurado, tem de aparecer
  literalmente em `scp`.
- **JIT linking por email configurável, desligado por omissão fora de
  local/test** — `Settings.entra_jit_link_by_email` (`bool | None`);
  `resolved_entra_jit_link_by_email()` devolve o valor explícito se
  definido, senão `True` em local/test e `False` em staging/produção. Uma
  ligação automática bem-sucedida grava sempre uma entrada em
  `AuthAuditLog` (evento `jit_link_by_email`, com o `oid` de origem).
- **Validador e cliente JWKS cacheados no processo** —
  `get_token_validator` passou a devolver uma instância partilhada via
  `functools.lru_cache` (chave: issuer/audience/jwks_url/tenant_id/
  required_scope), tanto para o validador real (que usa `PyJWKClient`,
  cujo cache HTTP das chaves passa a ser reaproveitado entre pedidos) como
  para o mock — nunca um `PyJWKClient` novo por pedido.

**Nova tabela `auth_audit_log`** (`AuthAuditLog`, append-only, sem
`updated_at`) — migração `67150240f450`.

**Testes (`tests/test_auth_entra_hardening.py`, 15 casos):** token sem
`oid` (com/sem `sub`) recusado; `nbf` no futuro recusado, no passado
aceite; token sem `scp` recusado como token de aplicação; âmbito
configurado a corresponder aceite, a não corresponder recusado; tenant
errado recusado quando configurado, correto aceite, sem verificação
quando não configurado; ligação JIT grava auditoria; JIT desligado
recusa um utilizador por ligar e não altera `entra_object_id`; JIT
desligado por omissão em staging (e ligado por omissão em local),
substituível explicitamente; validador é a mesma instância para
configurações equivalentes, instância diferente para `required_scope`
diferente.

## D-030 — Migração: `target_project_id` validado contra os candidatos detetados, ligação a projeto arbitrário exige permissão + nota

**Decisão:** `resolve_conflict(..., action="link_existing")` passou a
validar `target_project_id` contra `resolve_candidate_project_ids()` — o
conjunto de projetos que o sistema detetou automaticamente como
candidatos para este registo (por nome, na ingestão). Ligar a um projeto
fora desse conjunto exige `allow_target_outside_candidates=True` **e**
uma nota não vazia; sem as duas coisas, `resolve_conflict` recusa com
`ValueError`, mesmo chamado diretamente sem passar pela API (defesa em
profundidade deliberada — a decisão de permitir isto é da API, mas o
valor por omissão do serviço continua a recusar).

A API (`POST /api/migration/staging-records/{id}/resolve-conflict`)
verifica isto antes de chamar o serviço: se o alvo estiver fora dos
candidatos, exige a nova permissão `migration.link_arbitrary_project`
(403 sem ela — só concedida ao Administrador por omissão, não ao Chefe de
Operações) e uma nota não vazia (400 sem ela) antes de passar
`allow_target_outside_candidates=True` ao serviço.

**Bug encontrado e corrigido durante a implementação:** um candidato
detetado dentro do mesmo lote de importação (duplicado por nome, D-017)
fica registado como `"batch:<id_externo>"` até o registo irmão ser
promovido — só nesse momento é que existe um `Project` real para essa
referência. Uma primeira versão desta validação filtrava esses
candidatos "batch:" fora do conjunto válido em vez de os resolver,
partindo silenciosamente o fluxo legítimo já testado em
`test_resolve_conflict_then_promote_links_to_target_project`. Corrigido
com `resolve_candidate_project_ids()` — usada tanto pelo serviço como
pela API, para nunca haver duas lógicas divergentes sobre o que conta
como candidato válido — que traduz `"batch:<id>"` para o `Project` real
via `ProjectExternalId`, quando este já existe.

**Testes (`tests/test_migration_target_validation.py`, 7 casos, mais o
teste de regressão já existente em `test_staging_persistence.py`):**
alvo fora dos candidatos recusado por omissão; aceite com
`allow_target_outside_candidates=True` + nota; nota vazia continua
recusada mesmo com a flag; um candidato "batch:" já promovido resolve
corretamente e não exige a permissão especial; Chefe de Operações sem a
permissão recebe 403 pela API; Administrador com a permissão mas sem nota
recebe 400; Administrador com permissão + nota liga com sucesso, promove,
e a reversão (`rollback_promotion`) continua a funcionar normalmente —
ação sempre auditada e reversível, tal como pedido.

## D-031 — Login real MSAL no frontend (Authorization Code + PKCE), configurável, login de desenvolvimento claramente separado

**Decisão:** `frontend/src/auth/msal.ts` usa `@azure/msal-browser`
diretamente (`PublicClientApplication`) — sem `@azure/msal-react`, para
manter a mesma forma de módulo singleton já usada em `api/client.ts`, sem
introduzir Context/Provider só para isto. O MSAL browser só suporta
Authorization Code + PKCE para SPAs desde a v2 — não há "implicit flow"
para desativar, é sempre PKCE.

- **Nunca o ID token como autorização** — `acquireTokenSilent`/
  `loginRedirect` pedem sempre um âmbito dedicado à API
  (`VITE_ENTRA_API_SCOPE`, ex. `api://<client-id-da-api>/access_as_user`);
  só `result.accessToken` sai deste módulo, nunca `result.idToken`.
- **`Authorization: Bearer <token>` em todos os pedidos** —
  `api/client.ts:request()` decide por sessão (nunca por pedido): havendo
  uma conta MSAL ativa, todo o pedido leva o Bearer token; senão, cai
  para `X-Dev-User-Email` se houver um utilizador de desenvolvimento —
  os dois nunca são enviados ao mesmo tempo, tal como o backend só aceita
  um dos dois caminhos por `AUTH_ENABLED` (nunca ambos).
- **Renovação silenciosa** — cada pedido chama `acquireTokenSilent`
  (dentro de `getApiAccessToken()`), que o MSAL já resolve com o token em
  cache ou renovado silenciosamente sem qualquer interação visível;
  só levanta `SessionExpiredError` quando o MSAL confirma
  `InteractionRequiredAuthError` (refresh token expirado/revogado, MFA
  adicional exigido).
- **Logout e sessão expirada** — `logoutCurrentSession()` chama
  `logoutRedirect()` para uma sessão MSAL real (ou só limpa o
  `localStorage` para uma sessão de desenvolvimento); um `401` do backend
  numa sessão MSAL, ou uma `SessionExpiredError` do MSAL, redirecionam
  sempre para `/login?sessionExpired=1` em vez de repetir o pedido às
  cegas ou deixar a app num estado inconsistente.
- **Login de desenvolvimento claramente separado** —
  `devLoginEnabled` (`src/auth/msal.ts`) fica ligado por omissão em
  `vite dev`/testes (`import.meta.env.DEV`) e desligado por omissão num
  build de produção, substituível só por `VITE_ENABLE_DEV_LOGIN`
  explícito; o ecrã de login (`src/pages/Login.tsx`) só renderiza essa
  secção quando `devLoginEnabled` é true, sempre visualmente separada
  (aviso "Apenas desenvolvimento/testes", nunca disponível em
  staging/produção — mesma regra que o backend já aplicava do lado do
  servidor).

**Sem tenant/app registration reais** (pergunta bloqueante nº 1 — por
resolver), `VITE_ENTRA_CLIENT_ID`/`VITE_ENTRA_TENANT_ID`/
`VITE_ENTRA_API_SCOPE` ficam vazios por omissão; `isEntraConfigured` fica
`false` e o botão "Entrar com Microsoft" aparece desativado com uma
explicação — nunca inventa credenciais nem finge uma sessão real.

**Dependência nova:** `@azure/msal-browser` (`^5.21.0`).

**Vulnerabilidades npm revistas, não corrigidas nesta revisão:**
`npm audit` reporta 4 vulnerabilidades (3 moderadas, 1 alta) em `vite`
(via `esbuild`, servidor de desenvolvimento) e `react-router-dom`
(open-redirect via `\` em `<Link>`/`useNavigate`) — nenhuma tem correção
dentro do intervalo semver já instalado (`npm outdated` confirma "Wanted"
= "Current" para ambos); a única correção disponível é um salto de versão
maior (`vite` 5→8, `react-router-dom` 6→7), uma alteração desnecessária e
potencialmente disruptiva para uma revisão de hardening focada noutra
coisa. Registado como risco pendente (ver `docs/OPEN_QUESTIONS.md`) em
vez de forçado com `npm audit fix --force`.

**Atualizado por D-048:** a vulnerabilidade **alta** do `vite` tem, afinal,
correção sem salto de major — `vite@6.4.3` (não precisa de ir a 8) resolve
GHSA-fx2h-pf6j-xcff mantendo compatibilidade total com o resto do
frontend. Aplicado na integração dos dois PRs (`mvp-ready`) — ver D-048.
A de `react-router-dom` (moderada) continua sem correção fora de um
major e foi mantida como risco aceite.

**Validado manualmente ponta-a-ponta** (backend + frontend a correr
localmente, sem tenant Entra real): ecrã de login sem erros de consola
com a configuração MSAL vazia (placeholder), botão "Entrar com Microsoft"
visivelmente desativado com a explicação, secção de desenvolvimento
separada por um divisor visual; login de desenvolvimento continua
funcional ponta-a-ponta (entrar, `NavBar` a mostrar a sessão, listagem de
projetos a carregar, logout a limpar a sessão e devolver a `/login`).

## D-032 — Validação de configuração obrigatória, completa, em staging/produção

**Decisão:** `Settings._enforce_hardening_in_non_local_envs` (D-020,
`app/config.py`) passa a exigir, além das quatro condições já existentes
(`AUTH_ENABLED=true`, `SECRET_KEY` real e não vazio, `DATABASE_URL`
PostgreSQL, `ENTRA_VALIDATION_MODE=real`):

- `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID` e `ENTRA_REQUIRED_SCOPE`
  preenchidos — sem eles não há tenant/scope real a validar, e
  `resolved_entra_issuer()`/`resolved_entra_jwks_url()` apontariam para um
  URL Entra ID sintaticamente válido mas apontado a um tenant vazio
  (`.../v2.0`), um erro silencioso só visível ao primeiro pedido real.
- `CORS_ALLOWED_ORIGINS` não vazio — em staging/produção, vazio significa
  "nenhuma origem aceite" (`resolved_cors_origins`), que quase certamente
  não é a intenção de quem está a configurar; falha já no arranque em vez
  de deixar a API inacessível a qualquer frontend sem explicação.
- Se algum de `ENTRA_ISSUER`/`ENTRA_JWKS_URL`/`ENTRA_AUDIENCE` for
  definido explicitamente, os três têm de estar — um override parcial
  deixaria os campos não definidos a cair para o valor derivado de
  `ENTRA_TENANT_ID`/`ENTRA_CLIENT_ID`, uma mistura inesperada entre um
  valor manual e um valor derivado que nunca foi pedida como
  funcionalidade e é fácil de configurar por engano.

Todos os problemas continuam a ser reportados de uma vez na mesma mensagem
(comportamento já existente desde D-020), nunca só o primeiro — poupa
ciclos de tentativa-erro em staging.

**Porquê agora:** parte do fecho técnico da Fase 1 antes da preparação de
staging/produção — a validação anterior já impedia as combinações mais
óbvias, mas deixava passar uma configuração "tecnicamente válida" (auth
ligado, Postgres, modo real) que na prática nunca conseguiria autenticar
ninguém (tenant/scope em falta) ou nunca seria alcançável por um frontend
real (CORS vazio).

**Testado em** `tests/test_config_hardening.py` — um teste por condição
nova (staging e produção), mais o override parcial de
issuer/jwks/audience (com e sem os três presentes) e a mensagem agregada
com todos os problemas em simultâneo. `local`/`test` continuam nunca
bloqueados (mesmos testes de sempre, sem alteração).

**Sem impacto em `local`/`test`:** estas variáveis continuam opcionais
nesses ambientes — a Fase 1 já funciona sem tenant real via o mecanismo de
desenvolvimento (D-012); só passam a ser exigidas quando `APP_ENV` é
`staging`/`production`.

## D-033 — Login de desenvolvimento nunca sobrevive num build de produção, mesmo com `localStorage` antigo

**Decisão:** `src/pages/Login.tsx` já só renderizava a secção de login de
desenvolvimento quando `devLoginEnabled` (D-031); mas `src/api/client.ts`
continuava a ler/escrever `localStorage` incondicionalmente
(`getDevUser`/`setDevUser`/`hasActiveSession`/`request()`), pelo que um
valor gravado numa sessão de desenvolvimento anterior (ou escrito
manualmente por alguém a inspecionar o browser) continuava a ser enviado
como `X-Dev-User-Email` mesmo num build com `devLoginEnabled=false`.
Corrigido:

- `getDevUser()`/`setDevUser()` devolvem/ignoram sempre que
  `devLoginEnabled` é `false` — nunca tocam em `localStorage` nesse caso;
  `clearDevUser()` continua incondicional (limpar é sempre seguro).
- Ao carregar o módulo com `devLoginEnabled=false`, qualquer valor antigo
  já em `localStorage` é limpo imediatamente — nunca fica só "invisível
  para a leitura seguinte", é removido.
- `hasActiveSession()`/`getSessionDisplayName()`/`request()` já usavam
  `getDevUser()`, por isso herdam o bloqueio sem alteração adicional.

**Testado em** `frontend/src/api/client.dev-login.test.ts` (Vitest, novo —
o frontend não tinha nenhum framework de testes automatizados até agora,
só validação manual ponta-a-ponta e `tsc --noEmit`/`vite build`): grava e
lê corretamente com `devLoginEnabled=true`; nunca grava nem lê com
`devLoginEnabled=false`; um valor antigo em `localStorage` é limpo ao
carregar o módulo; um pedido HTTP nunca leva `X-Dev-User-Email` mesmo com
`localStorage` manipulado depois de o módulo já estar carregado. CI
(`frontend` job) passa a correr `npm run test` antes de `npm run build`.

**Dependências novas (dev):** `vitest@^3.2.7`, `jsdom` — só para testes,
sem impacto no bundle de produção (`vite build` não os inclui). Fixado em
`3.2.7` (não `^2`, a versão inicialmente instalada) especificamente porque
`npm audit` reportou uma vulnerabilidade **crítica** no servidor de UI do
Vitest (`GHSA-5xrq-8626-4rwp`, corrigida em `vitest@3.2.6`) — nunca
aceitável deixar por corrigir só porque é uma dependência de
desenvolvimento. Uma vulnerabilidade moderada remanescente em
`@vitest/mocker` (`GHSA-82fw-gwwq-j7x9`) só se resolve com `vitest@5`
(exige `vite@6+`, fora do âmbito desta revisão) — registada em
`docs/OPEN_QUESTIONS.md` junto das outras atualizações major já adiadas
(`vite`, `react-router-dom`).

## D-034 — Provisionamento administrativo de `User.entra_object_id`: comando controlado, nunca um endpoint HTTP

**Decisão:** `app/cli/provision_entra_user.py` — comando de linha de
comandos (`python -m app.cli.provision_entra_user`), corrido manualmente
por alguém com acesso direto ao servidor/base de dados de
staging/produção, nunca um endpoint da API. Liga `User.entra_object_id` a
um `User` já existente e ativo — este é o mecanismo real de
provisionamento dos 5 utilizadores em staging/produção, onde o JIT linking
por email fica desligado por omissão (`resolved_entra_jit_link_by_email`,
D-029).

**Regras, sempre no núcleo `link_user_to_entra_object_id`** (nunca só no
`main()` da CLI, para que os testes exerçam exatamente a mesma lógica):

- **Nunca cria um `User` novo** — só liga a um já existente e ativo; email
  desconhecido ou inativo é sempre erro.
- **Nunca reatribui** — um `User` já ligado a qualquer `entra_object_id`
  (mesmo repetir o mesmo valor) é sempre erro; desligar fica fora do
  âmbito deste comando, de propósito (mantém-no pequeno e sem
  ambiguidade).
- **Nunca reutiliza um `entra_object_id` em dois utilizadores** —
  verificação explícita (mensagem compreensível) mais a restrição UNIQUE
  já existente em `User.entra_object_id` na base de dados como barreira
  final, independente da aplicação.
- **Sempre auditado** — uma entrada `AuthAuditLog` (evento
  `admin_provision_link`) com o email do utilizador, o `entra_object_id`, e
  `actor_label` (quem executou, obrigatório — sem isto o comando recusa-se
  a correr).
- **`--confirm` obrigatório para escrever** — sem essa flag, a CLI só
  mostra o que faria (dry-run), proteção simples contra execução
  acidental.

**Porquê um comando, não um endpoint:** até 5 utilizadores (D-003) é uma
operação rara — um endpoint novo seria uma superfície de API permanente
para uma ação administrativa esporádica, e manteria `get_current_user`
livre de qualquer lógica de "criar/ligar identidade" (separação já
deliberada — ver docstring de `app/security/current_user.py`). Satisfaz o
requisito "permissão administrativa OU comando administrativo controlado"
pela segunda via: quem consegue correr este comando já precisa de acesso
direto ao servidor/base de dados, um controlo de acesso independente do
`admin.manage_users` da aplicação.

**JIT linking continua desligado em produção por omissão** (D-029, sem
alteração aqui) — este comando é o caminho normal; o JIT por email
continua disponível só como conveniência de local/test, ou se alguém
definir `ENTRA_JIT_LINK_BY_EMAIL=true` explicitamente em staging/produção
(decisão de negócio explícita, não a omissão).

**Testado em** `tests/test_provision_entra_user.py` (12 testes): ligação
bem-sucedida, entrada de auditoria correta, case-insensitive no email,
email desconhecido/inativo rejeitados, nunca cria `User`, reatribuição
rejeitada, `entra_object_id` duplicado rejeitado (com e sem a verificação
explícita — o teste da restrição UNIQUE da base de dados confirma a
barreira final independente da aplicação), argumentos vazios rejeitados.

## D-035 — Allowlist de campos PM revista: campos com impacto comercial ficam administrativos até decisão de negócio

**Decisão:** `app/security/project_fields.py` (D-028) tinha classificado
`lat`, `lon`, `power_kwp`, `power_raw`, `start_date`,
`commercial_assumptions`, `upac_connection_date_raw` e `award_year_raw`
como PM-editáveis (`project.edit_own_progress`) — uma omissão técnica
razoável na Fase 1, mas nunca confirmada como decisão de negócio. Revisto
nesta preparação para staging/produção: estes oito campos passam a
`ADMIN_ONLY_PROJECT_FIELDS` (só `project.edit_all` os edita). Ficam
PM-editáveis só `role`, `equipment_notes`, `injection_notes`, `om_notes` e
`notes` — texto de acompanhamento operacional, sem valor comercial nem
usado por outra integração.

**Porquê:** potência e coordenadas afetam o dimensionamento e a
localização real reportada da instalação; `commercial_assumptions` é, pelo
nome, um pressuposto comercial; as datas legadas (`start_date`,
`upac_connection_date_raw`, `award_year_raw`) podem ter valor contratual.
Nenhum destes teve uma resposta explícita de "um PM pode corrigir isto no
seu próprio projeto sem aprovação?" — seguindo a regra geral desta revisão
("sem confirmação de negócio, usar a opção mais restritiva"), ficam
administrativos até essa confirmação existir. Registado como pergunta em
aberto — `docs/OPEN_QUESTIONS.md`, pergunta 5-B.

**Impacto operacional conhecido, aceite deliberadamente:** uma correção
legítima destes campos por um PM (ex.: coordenadas erradas vindas da
migração) passa a exigir sempre um Chefe de Operações/Administrador —
possível atrito se a resposta de negócio acabar por ser "sim, o PM pode
editar X". Prefere-se este atrito a um PM poder alterar, sem aprovação,
um valor com peso comercial/contratual antes de existir uma decisão.

**Testado em** `tests/test_project_field_permissions.py` — teste novo
confirma explicitamente que os oito campos ficam em
`ADMIN_ONLY_PROJECT_FIELDS` e que um PM recebe 403 ao tentar alterar
`power_kwp` no seu próprio projeto; os testes existentes (disjunção,
cobertura total de `ProjectUpdate`, `notes` continua PM-editável)
continuam a passar sem alteração.

## D-036 — Repetir a promoção depois de um rollback: nunca um segundo projeto

**Problema encontrado:** `rollback_promotion` (D-017) desativa o projeto
(caso `create_new`) ou restaura os valores anteriores (caso
`update_existing`/`link_existing`), e deixa o registo de staging em
`pending_review`. Nenhuma função existente devolvia esse registo a
`ready_to_promote` — `promote_staging_record` exige exatamente esse
estado, `resolve_conflict` exige `conflict`. Pior: mesmo que alguém forçasse
manualmente `status='ready_to_promote'` num registo `resolved_action=
'create_new'` já revertido, promover outra vez criaria um **segundo**
`Project` com o mesmo `external_id` — violando a restrição UNIQUE
`(source_system, external_id)` de `ProjectExternalId` já a meio da
transação, ou pior, duplicando o projeto se a violação não fosse
apanhada a tempo. Isto é exatamente o cenário "promover → algo está
errado → reverter → corrigir → promover outra vez" que uma migração real
dos 295 projetos vai precisar.

**Decisão:** `app/migration/staging.py:retry_promotion_after_rollback` —
passo explícito e obrigatório entre um rollback e uma nova promoção (nunca
automático, tal como `resolve_conflict`/`promote_staging_record` já eram
dois passos distintos):

- Só aceita um registo `pending_review` com `reverted_at` preenchido
  (ou seja, que passou mesmo por `rollback_promotion`) — rejeita qualquer
  outro estado, incluindo um registo nunca promovido.
- Se `resolved_action` era `'create_new'`, reescreve para
  `'update_existing'` apontado ao `promoted_project_id` já existente —
  **nunca volta a passar por `create_new`**, eliminando a via de
  duplicação. Para `'update_existing'`/`'link_existing'`, o alvo já
  estava certo, sem alteração.
- Reativa o projeto (`is_active=True`) se necessário, com uma entrada de
  `project_history` própria (fonte nova `migration_retry`, distinta de
  `migration_rollback` — nunca esconde que uma reativação aconteceu numa
  entrada que parece um rollback).
- Reaplica a mesma verificação de PM (`_finalize_status_given_pm`) das
  outras etapas — nunca duas lógicas divergentes sobre quando promover.

Endpoint novo, mesma permissão (`migration.resolve`):
`POST /api/migration/staging-records/{id}/retry-promotion`.

**Testado em** `tests/test_staging_persistence.py` (3 testes: caso
`create_new` confirma mesmo `project.id`, nenhuma duplicação de
`ProjectExternalId`, contagem de projetos inalterada; caso
`update_existing` confirma reaplicação do campo; rejeição de um registo
nunca revertido) e `tests/test_migration_api.py` (2 testes: ciclo completo
via API — promover → reverter → repetir → promover, mesmo `project_id`; e
a permissão `migration.resolve` exigida, PM sem essa permissão recebe
403).

## D-037 — Ingestão controlada para staging: comando administrativo, modo staging-only, contagens de revisão

**Decisão:** `app/cli/ingest_staging.py` — comando de linha de comandos
(`python -m app.cli.ingest_staging --file <export.json> [--actor-email
...]`), a única forma de invocar `ingest_export` fora dos testes. Nunca um
endpoint HTTP (D-026 já excluía isso deliberadamente da API).

- **Modo staging-only:** `assert_staging_only_environment` recusa-se a
  correr com `APP_ENV=production` — a migração real passa sempre primeiro
  por `staging` para revisão manual da fila de conflitos
  (docs/DATA_MIGRATION_RUNBOOK.md), nunca diretamente para produção por
  este comando. `local`/`test` continuam permitidos, para ensaiar o fluxo
  com fixtures sintéticas. Segunda barreira independente: em `production`
  real (configuração completa — D-032), `get_settings()` já teria
  bloqueado o processo inteiro no arranque (`AUTH_ENABLED`, PostgreSQL,
  etc.) antes mesmo deste comando correr — mas esta verificação cobre
  também o caso (impossível em produção real, mas possível num ambiente
  mal configurado) de alguém correr o comando com `APP_ENV=production`
  apontado a uma base de dados que não devia.
- **Contagens de revisão** (`app/migration/staging.py:summarize_import_batch`):
  `projects_seen`, `ready_to_promote`, `conflicts`, `distinct_pm_names`,
  `with_email`, `with_contact`, `with_coordinates` — sempre derivadas de
  `mapped_fields_json` já persistido, nunca relidas do payload bruto (para
  nunca divergir de `_map_legacy_fields`). Nunca inclui nada sobre
  `projects` — só sobre os registos de staging deste lote.
- **`--actor-email` opcional** — quando fornecido, tem de corresponder a um
  `User` ativo já existente (nunca inventa nem ignora silenciosamente um
  email desconhecido); grava `ImportBatch.started_by_person_id`.
- **Nunca escreve em `projects`** (comportamento herdado de `ingest_export`,
  sem alteração) — a mensagem final do comando lembra sempre isto e aponta
  para o endpoint de revisão da fila de conflitos.

**Testado em** `tests/test_ingest_staging_cli.py` (10 testes): barreira
staging-only (produção rejeitada, os restantes ambientes permitidos);
nunca escreve em `projects`; payload preservado verbatim; contagens
corretas contra a fixture sintética (`synthetic_legacy_export.json`, 3
projetos: 2 PMs distintos, 2 com email, 2 com contacto, 2 com
coordenadas); resolução de `--actor-email` (existente, desconhecido,
omitido). Validado manualmente também via linha de comandos: recusa
correta em `APP_ENV=production` (bloqueado já pela validação de
configuração — D-032) e execução completa com resumo correto em `local`.

## D-038 — Roadmap funcional reordenado: Dashboard → Workflow → Migração → Inventário → Graph → Claude

**Decisão:** `docs/PLAN.md` renumerado por pedido explícito — a ordem de
prioridade passa a ser Dashboard inicial (Fase 2, nova) → Workflow de
projetos (Fase 3, nova) → Migração real dos 295 projetos (Fase 4, era
Fase 2) → Inventário e pedidos de material (Fase 5, sem alteração de
número) → Microsoft Graph real (Fase 6, era Fase 3) → Claude — propostas
de agenda, preparação de emails e relatórios, sempre com aprovação humana
(Fase 7, era Fase 7, âmbito reduzido — ver abaixo). ClickUp real (Fase 8,
era Fase 4) e Biblioteca documental (Fase 9, era Fase 6) não faziam parte
da ordem de seis itens pedida — mantidos no roadmap, colocados depois
dessas seis, sem prioridade relativa inventada; cada secção documenta a
sua própria dependência técnica (ClickUp de Fase 4, Documental de Fase 6).

**Duas fases novas, só roadmap nesta revisão (sem implementação):**
- **Fase 2 — Dashboard inicial:** estatísticas semanais, trabalhos
  pendentes, visão operacional, visão comercial, férias e aniversários.
  Nenhuma métrica/campo obrigatório foi assumido — "férias e aniversários"
  não tem sequer modelo de dados hoje (`Person` sem data de nascimento,
  sem entidade de ausências). Registado como pergunta 18 em
  `docs/OPEN_QUESTIONS.md`.
- **Fase 3 — Workflow de projetos:** o modelo de dados
  (`phases`/`workflow_stages`/`workflow_subtasks`/
  `project_stage_progress`/`project_subtask_progress`) já existe desde a
  Fase 0, semeado só com um processo genérico de exemplo — carregar o
  processo real de 6 fases da Solcor e definir os requisitos para avançar
  de fase (hoje nada bloqueia isto) ficam como decisão de negócio,
  registada como pergunta 19.

**Consequência aceite:** a Fase 4 (Migração) só depende tecnicamente da
Fase 1, não das Fases 2/3 — a nova sequência é uma escolha de prioridade
de negócio, não uma dependência técnica; a tabela "Dependências entre
fases" em `docs/PLAN.md` documenta isto explicitamente para não passar a
impressão de um bloqueio que não existe. O âmbito da Fase 7 (Claude) fica
reduzido face à versão anterior do roadmap: a pesquisa documental (RAG)
sobre a biblioteca dependia da Biblioteca Documental, que passa a vir
depois (Fase 9) — fica registada como um incremento futuro de Claude,
não como parte do âmbito imediato desta fase.

**Nada disto implica trabalho de implementação nesta sessão** — pedido
explícito era só reordenar o roadmap, nunca implementar as integrações
externas ou o dashboard/workflow em si.
# Fase 1.5 — MVP dashboard/workflow

Pedido explicitamente pelo negócio como o MVP a entregar antes da Fase 2
(migração real dos 295 projetos) — ver a secção "MVP recomendado" em
`docs/PLAN.md` para a justificação de porque este MVP avança antes daquele.
Nenhuma integração real (Graph/ClickUp/Financial/Claude), sem envio de
email, sem eventos reais, sem mapas/inventário/pedidos de
material/biblioteca documental, sem migração de dados reais — tudo isso
continua fora de âmbito e documentado no roadmap (`docs/PLAN.md`).

## D-039 — `Task` como entidade nova, não reaproveitamento de `Phase`/`WorkflowStage`/`ProjectSubtaskProgress`

**Contexto:** já existia em `app/models/workflow.py` +
`app/models/project.py` um sistema de processo fixo — `Phase` →
`WorkflowStage` → `WorkflowSubtask` (catálogo) e
`ProjectStageProgress`/`ProjectSubtaskProgress` (progresso booleano por
projeto). O pedido deste MVP é uma tarefa genérica com responsável,
prioridade, prazo, notas, estado (`todo`/`in_progress`/`blocked`/`done`/
`cancelled`) e histórico de alterações — criável/editável livremente pelo
utilizador, não só um checklist de catálogo fixo.

**Decisão:** criar `app/models/task.py` (`Task`, `TaskHistory`) como
entidade nova, em vez de alargar `ProjectSubtaskProgress` com todos estes
campos. As duas estruturas **coexistem nesta fase, sem nenhuma migração de
dados entre elas** — `Phase`/`WorkflowStage`/`WorkflowSubtask` continuam
semeados (`seed_workflow`) mas sem endpoint nem UI ligados nesta fase (já
assim antes desta sessão — ver "Âmbito deixado de fora da Fase 1").

**Porquê não reaproveitar:** `ProjectSubtaskProgress` é uma tabela de
junção `(projeto, subtarefa) → done`, com a subtarefa definida uma vez no
catálogo (`WorkflowSubtask`) e partilhada por todos os projetos —
alargá-la para ter responsável/prioridade/prazo/notas próprios por
projeto exigiria duplicar `WorkflowSubtask` por projeto (perdendo a
vantagem de catálogo único) ou mover esses campos para uma tabela nova de
qualquer forma. Criar `Task` direta e simples é menos código e mais claro
do que forçar um encaixe.

**Consequência assumida:** o sistema tem agora dois modelos de "trabalho a
fazer" com propósitos ligeiramente diferentes — decisão consciente,
registada aqui e em `docs/OPEN_QUESTIONS.md` como pergunta em aberto para
uma fase futura decidir se compensa unificar (ex.: `WorkflowSubtask`
passar a gerar automaticamente uma `Task` por projeto).

## D-040 — Máquina de estados de `Task`: `blocked` nunca salta direto para `done`; `done`/`cancelled` só reabrem para `todo`/`in_progress`

**Decisão** (`app/services/tasks.py:TASK_TRANSITIONS`):

```text
todo         -> todo, in_progress, blocked, done, cancelled
in_progress  -> in_progress, todo, blocked, done, cancelled
blocked      -> blocked, todo, in_progress, cancelled       (nunca done)
done         -> done, todo, in_progress                     (reabertura)
cancelled    -> cancelled, todo                              (reabertura)
```

Uma transição para o mesmo estado é sempre um no-op permitido (sem gerar
histórico); qualquer transição fora desta tabela é rejeitada com `400` e
sem qualquer escrita (`InvalidTaskTransition`,
`app/api/routes_tasks.py`).

**Porquê:** o pedido explícito era "criadas, editadas, atribuídas,
concluídas, reabertas" — não uma máquina de estados detalhada, por isso a
regra concreta é uma decisão de implementação, não um requisito do
negócio (registado aqui para revisão, não assumido como definitivo). A
única regra de negócio considerada não-arbitrária: uma tarefa bloqueada
não devia poder "saltar" para concluída sem primeiro ser desbloqueada —
sinaliza um erro operacional real (ex. marcar como feito por engano sem
resolver o bloqueio). `done`/`cancelled` só reabrirem para `todo`/
`in_progress` (nunca um do outro diretamente) mantém o histórico legível:
reabrir sempre volta ao início do fluxo ativo, nunca troca diretamente
entre dois estados terminais.

`completed_at` é sempre derivado do lado do servidor a partir da
transição de/para `done` — nunca um campo editável em `TaskUpdate`
(`app/schemas/tasks.py`), para não haver uma segunda fonte de verdade
sobre "quando foi concluída".

**Testes:** `tests/test_tasks_api.py` (transição válida com histórico e
`completed_at`; `blocked → done` rejeitado; `cancelled` só reabre para
`todo`; reabrir `done` limpa `completed_at`).

## D-041 — Dashboard: endpoint de resumo único, calculado inteiramente no servidor; semana sempre em Europe/Lisbon; indicadores operacionais só contam projetos ativos

**Decisão:** `GET /api/dashboard/summary` (`app/services/dashboard.py`)
devolve todos os indicadores da página inicial já calculados e já
filtrados pela visibilidade do utilizador — o frontend nunca soma/filtra
listas completas para produzir uma métrica (requisito explícito: "os
dados devem vir de endpoints próprios de resumo/dashboard").

**Fuso horário centralizado:** `app/utils/timezones.py` (`today_lisbon()`,
`week_range_lisbon()`) é o único ponto que sabe que "hoje"/"esta semana"
usam `Europe/Lisbon` — usado por `Task.is_overdue`,
`app/services/tasks.py` (filtro `overdue_only`), e
`app/services/dashboard.py`. Sem isto, um servidor alojado noutro fuso
(UTC, por exemplo) calcularia "esta semana" de forma diferente do que uma
pessoa em Portugal veria no calendário. Dependência nova: `tzdata` — o
Windows (e alguns Linux mínimos) não trazem a base de dados IANA que
`zoneinfo` precisa; confirmado neste ambiente de desenvolvimento
(`ZoneInfoNotFoundError` sem o pacote).

**Só projetos ativos entram nos indicadores operacionais** —
`active_projects_count`, "a começar em 30 dias", "sem PM", "dados em
falta" já filtravam por `is_active` desde a primeira versão; durante a
verificação manual em navegador desta sessão encontrou-se um bug real: as
tarefas de um projeto inativo (`Instalação Sintética H — Inativa`, com
checklist padrão semeada de propósito para testar isto) apareciam em
"visitas técnicas pendentes"/"comissionamentos pendentes"/"tarefas
atrasadas", porque esses indicadores vinham de `visible_tasks_query` sem
o mesmo filtro. Corrigido filtrando pelas tarefas do **próprio projeto**
(`t.project.is_active`), não pela lista de projetos ativos já calculada —
para não excluir por engano uma tarefa atribuída diretamente ao
utilizador num projeto ativo que não é o seu como PM. Teste de regressão:
`tests/test_dashboard.py::test_tasks_of_inactive_projects_never_appear_in_operational_lists`.

**Testes:** `tests/test_dashboard.py` (escopo por perfil, semana em
Europe/Lisbon, cada indicador com pelo menos um caso semeado real).

## D-042 — `Absence`: modelo mínimo, sem fluxo de aprovação nesta fase

**Decisão:** `Absence` (`app/models/absence.py`) tem só os campos
pedidos — pessoa, data inicial, data final, tipo (`ferias`/
`baixa_medica`/`outro`), nota, estado (`aprovada`/`cancelada`). Criar uma
ausência já a marca `aprovada` — não existe um estado `pendente` nem um
passo de aprovação por outra pessoa. Depois de criada, só `status` e
`note` são editáveis (`AbsenceUpdate`) — alterar datas/pessoa/tipo exige
cancelar e criar de novo, para o registo nunca ficar ambíguo sobre "o que
mudou realmente" sem precisar de histórico próprio (ao contrário de
`Task`/`Project`, `Absence` não tem uma tabela de histórico — âmbito
deliberadamente mínimo).

**Porquê:** o pedido foi "criar entidade... e uma interface simples para
consultar e registar férias" — não descreveu um fluxo de
pedido→aprovação. Assumir `aprovada` por omissão evita inventar um
fluxo que o negócio pode não querer. **Registado como pergunta em
aberto** em `docs/OPEN_QUESTIONS.md`: se for necessário um fluxo real de
aprovação (ex. PM pede, Chefe aprova), isto exige um novo estado
`pendente` e uma ação de aprovação — mudança pequena e aditiva quando
decidido.

**Testes:** `tests/test_absences_api.py` (criação fica `aprovada`, datas
inválidas rejeitadas, permissões por perfil, cancelamento).

## D-043 — Aviso de fotos pendentes: reaproveita a tarefa padrão `fotos_drive`, sem novo campo booleano

**Decisão:** o pedido "quando uma tarefa de visita técnica ou
comissionamento for concluída, mostrar um aviso persistente para
confirmar que as fotos foram colocadas na Drive" é resolvido inteiramente
a partir das tarefas já existentes — `ProjectRead.photos_pending_warning`
(`app/services/projects.py:compute_project_task_summary`) é `True` quando
pelo menos uma tarefa `visita_tecnica`/`comissionamento` está `done` **e**
a tarefa `fotos_drive` desse projeto ainda não está `done`. Sem nenhum
campo novo em `Project` nem em `Task` — o aviso desaparece sozinho assim
que alguém marcar "Colocar fotos na Drive" como concluída.

**Porquê:** a checklist padrão de 5 tarefas por projeto já inclui
"Colocar fotos na Drive" como a última etapa (pedido explícito da secção
2) — usá-la como o próprio sinal do aviso evita um segundo lugar para a
mesma informação poder divergir (ex. um booleano `photos_confirmed` que
alguém esquece de sincronizar com o estado real da tarefa).

**Nesta fase o aviso é só informativo** (banner na página do projeto,
ícone ⚠️ na lista de projetos) — nunca bloqueia nenhuma ação, tal como
pedido explicitamente ("nesta fase o aviso é apenas interno; não fazer
integração com a Drive").

**Testes:** `tests/test_project_task_summary.py` (aviso só quando visita/
comissionamento concluída e fotos não; desaparece ao concluir fotos);
validado também manualmente no browser (ver verificação end-to-end desta
sessão).

## D-044 — Visibilidade de férias/aniversários no dashboard ligada a `absence.view_all`/`absence.view_own`

**Decisão:** quem tem `absence.view_all` (Chefe de Operações,
Administrador) vê as férias/ausências e os aniversários de toda a gente
no dashboard; quem só tem `absence.view_own` (PM, Comercial, Financeiro)
só vê os seus próprios — nunca os de terceiros. O mesmo par de permissões
controla os dois indicadores (não há uma permissão separada só para
aniversários) porque são a mesma categoria de informação pessoal de baixa
sensibilidade, tratada com o mesmo nível de acesso.

**`PersonRead` (`GET /api/people`, disponível a qualquer utilizador
autenticado para preencher filtros/dropdowns) nunca inclui `birth_date`**
— só o endpoint do dashboard expõe data de nascimento, e só ao subconjunto
de pessoas que a permissão do utilizador autoriza (`BirthdayMini`, via
`_birthday_scoped_people_query` em `app/services/dashboard.py`). Evita que
adicionar `birth_date` a `Person` vaze essa informação por um caminho não
pensado para isso.

**Porquê esta escolha e não "todos veem tudo":** o pedido dizia
explicitamente "não expor informação sensível desnecessária" na secção de
férias/aniversários — restringir por omissão é mais seguro do que expor
por omissão e ter de restringir depois. **Registado como pergunta em
aberto** em `docs/OPEN_QUESTIONS.md`: pode ser que o negócio prefira que
todos vejam as férias/aniversários da equipa toda (prática comum em
empresas pequenas) — mudar é trivial (dar `absence.view_all` a mais
perfis), mas decidido aqui pelo lado mais restritivo até confirmação.

**Testes:** `tests/test_dashboard.py::test_pm_without_absence_view_all_only_sees_own_birthday`.

## D-045 — Matriz de permissões alargada: `task.*`/`absence.*`, e o que cada perfil ganhou

**Decisão** (`app/security/catalog.py`):

| Permissão | Chefe Operações | PM | Comercial | Financeiro |
|---|---|---|---|---|
| `task.view_all` / `task.view_own` | `view_all` | `view_own` | `view_all` | `view_all` |
| `task.edit_all` / `task.edit_own` | `edit_all` | `edit_own` | — | — |
| `absence.view_all` / `absence.view_own` | `view_all` | `view_own` | `view_own` | `view_own` |
| `absence.manage_all` / `absence.manage_own` | `manage_all` | `manage_own` | `manage_own` | `manage_own` |

`can_edit_task`/`can_create_task`/`can_view_task` e
`can_manage_absence`/`can_view_absence`/`can_create_absence_for`
(`app/security/permissions.py`) seguem exatamente o mesmo padrão já
estabelecido por `can_edit_project`/`can_view_project` — nunca um "papel"
lido do cliente, sempre a permissão + a relação (PM do projeto, ou
responsável direto pela tarefa/ausência).

**Comercial e Financeiro passam a ter `task.view_all`** (consistente com
o `project.view_all` que já tinham) mas **não** `task.edit_all`/`_own` —
continuam só de leitura sobre tarefas, tal como já eram só de leitura
sobre projetos (`test_comercial_is_read_only_on_tasks`). Nenhuma alteração
a permissões pré-existentes (`project.*`, `cost.*`, etc.) — só aditivo.

**Sobre dados financeiros na vista Comercial** (requisito explícito: "a
vista Comercial não deve mostrar dados financeiros que não tenha
permissão para consultar"): nenhum indicador do dashboard, da lista de
projetos, ou de tarefas desta fase depende de `cost.view` ou mostra
qualquer valor monetário — o módulo Financial está inteiramente fora
deste MVP. O requisito fica automaticamente satisfeito por
não haver dado financeiro nenhum para mostrar; quando a Fase 5
(custos/margens) for construída, quem desenhar essas vistas tem de
repetir este cuidado explicitamente (não há nada nesta fase que o faça
automaticamente para telas futuras).

## D-046 — Frontend: Vitest + Testing Library como primeira infraestrutura de testes automatizados

**Decisão:** `vitest`, `@testing-library/react`, `@testing-library/jest-dom`
e `jsdom` adicionados a `devDependencies`; configuração em
`frontend/vitest.config.ts` (ambiente `jsdom`, `globals: true`, setup em
`src/setupTests.ts`); `npm test` corre `vitest run`. Não existia nenhuma
suite de testes de frontend antes desta fase (`docs/PLAN.md` já
documentava isto como lacuna conhecida — "Frontend (além do build e
validação manual): sem testes automatizados de UI ainda").

**Cobertura desta fase:** funções puras (`src/utils/dates.ts`,
`src/utils/dates.test.ts`), invariantes da máquina de estados espelhada no
cliente (`src/api/taskTransitions.test.ts` — mesma tabela de D-040, só
para desenhar a UI, nunca a fonte de verdade), e um teste de fumo do
painel inicial com a API mockada (`src/pages/Home.test.tsx`) confirmando
que os indicadores devolvidos pelo endpoint aparecem no ecrã. Não é
cobertura exaustiva de componentes — âmbito deliberadamente pequeno para
esta fase, ver `docs/OPEN_QUESTIONS.md` sobre Playwright/Cypress
end-to-end como possível passo seguinte.

## D-047 — `/` passa a ser o painel operacional; conteúdo anterior movido para `/status`

**Decisão:** `frontend/src/pages/Home.tsx` (novo) é a página inicial —
antes, `/` redirecionava para `/projects` e a página `Dashboard.tsx`
(saúde do backend + utilizador de desenvolvimento) vivia em `/status`.
Esse conteúdo técnico foi preservado tal como estava, só renomeado para
`SystemStatus.tsx`, continua acessível em `/status` como diagnóstico —
nada foi perdido, só deixou de ser a primeira coisa que se vê ao entrar
(requisito explícito: "criar a página `/` como página principal depois do
login").

**Testes:** `tests/test_dashboard.py` (backend); `Home.test.tsx`
(frontend, ver D-046).

## D-048 — Integração de PR #1 (hardening) + PR #2 (MVP) em `mvp-ready`

**Contexto:** os dois PRs foram desenvolvidos em paralelo a partir do
mesmo commit em `main` (`b39be01`), cada um continuando a numeração de
decisões a partir de D-031 — resultando em duas séries de decisões D-032
a D-040/D-038 incompatíveis, e conflitos reais em `docs/PLAN.md`,
`docs/DECISIONS.md`, `docs/OPEN_QUESTIONS.md`, `README.md`,
`.github/workflows/ci.yml` e `frontend/package.json`/`vitest.config.ts`.

**Decisão:**
1. `mvp-ready` parte de `origin/main`, integra primeiro
   `staging-prod-hardening` (fast-forward, sem conflitos — as duas séries
   de commits não se sobrepõem em código) e só depois
   `mvp-dashboard-workflow` (onde os conflitos reais acontecem).
2. As decisões do MVP (D-032 a D-040 na numeração original do PR #2) foram
   renumeradas para D-039 a D-047, preservando a numeração D-032 a D-038
   do hardening (PR #1) inalterada — evita reescrever qualquer referência
   já feita a D-032..D-038 fora deste merge.
3. `docs/PLAN.md`: a numeração de fases do hardening (Fase 4 = Migração,
   Fase 5 a 9 = Inventário/Graph/Claude/ClickUp/Biblioteca) foi mantida
   sem alteração — evita quebrar as várias referências cruzadas a "Fase N"
   espalhadas pelo documento. As antigas Fase 2 (Dashboard inicial) e
   Fase 3 (Workflow de projetos), que eram só roadmap por implementar,
   foram anotadas como cobertas pela nova Fase 1.5 (MVP, implementada) —
   ver essas secções para o detalhe de o que ficou coberto e o que não
   (o processo fixo `Phase`/`WorkflowStage` continua sem endpoints).
4. `frontend/package.json`: Vitest mantido em `3.2.7` (nunca voltar a
   2.x — vulnerabilidade crítica que motivou o hardening). `vite`
   atualizado de `5.4.11` para `6.4.3` — necessário para eliminar
   GHSA-fx2h-pf6j-xcff (`server.fs.deny` bypass no Windows, severidade
   alta, CVSS 7.5), que não tem correção na série 5.x; compatível com
   `@vitejs/plugin-react@4.3.4` (aceita `vite ^6.0.0`) e com a suite
   Vitest existente — `npm run lint`/`npm test`/`npm run build`
   confirmados depois da atualização. Vulnerabilidades moderadas
   remanescentes (`@vitest/mocker`/`vitest` — precisa de Vitest 4.x;
   `react-router`/`react-router-dom` — precisa de major 7.x) não foram
   corrigidas nesta revisão para não forçar upgrades major
   desnecessários fora do que foi pedido — mesma política já registada
   acima para o `npm audit` da Fase 1.
5. `.github/workflows/ci.yml`/`vitest.config.ts`: combinados sem perda —
   o job de frontend corre `lint` + `test` (Vitest) antes do `build`
   (D-039 do PR #2, preservado), e a configuração de testes junta
   `globals`/`setupFiles` (suite de UI, D-046) com o `include` explícito
   do hardening.
6. `Task` mantém-se como a única unidade operacional usada pelo MVP; os
   modelos antigos `Phase`/`WorkflowStage`/`WorkflowSubtask` não foram
   tocados nem migrados — decisão explícita de não arriscar uma migração
   de dados agora (ver `docs/OPEN_QUESTIONS.md` perguntas 22 e 24). Um
   futuro formulário de visita técnica/comissionamento tem de escolher
   uma única fonte de verdade entre as duas antes de ser construído.

**Validação pós-merge:** 224 testes de backend a passar + 2 skipped
(SQLite; PostgreSQL não pôde ser validado neste ambiente Windows por
falta de Docker — mesmo bloqueio já documentado em D-021 — fica para o
job `backend-postgres` do CI em `GitHub Actions`); 18 testes Vitest no
frontend; `npm run build`/`npm run lint` sem erros; testado manualmente
no browser com os 5 utilizadores sintéticos do seed (permissões de
PM/Chefe/Comercial/Financeiro/Admin, aviso de fotos pendentes,
transições de estado inválidas bloqueadas, validação de datas de férias,
projeto inativo excluído do dashboard, fluxo de ingestão para staging
com contagens/conflitos/promoção/rollback).

## D-049 — Preparação para staging: piloto de importação, seed bloqueado, .env.staging.example

**Contexto:** antes de um primeiro piloto com dados reais em staging,
faltavam três coisas: uma forma segura de testar 5 a 10 projetos reais
sem arriscar os 295 de uma vez; uma barreira de código (não só
disciplina documentada) contra o seed sintético correr em staging; e
exemplos de configuração dedicados a staging, distintos dos de
local/dev, com todos os valores obrigatórios já assinalados.

**Decisão:**

1. `app.migration.staging.ingest_export` ganha `only_external_ids`,
   `limit` e `dry_run`, expostos em `app.cli.ingest_staging` como
   `--only-ids`, `--limit`, `--dry-run` — permite pré-visualizar
   (contagens, conflitos) e depois ingerir só um subconjunto do export
   real, sem tocar nos restantes 285-290 projetos. `dry_run=True` corre
   exatamente a mesma lógica (incl. deteção de duplicados contra a base
   de dados real) mas nunca commita — o chamador reverte a transação
   depois de ler o resumo, para não deixar nenhum vestígio nem em
   `import_batches`/`staging_project_records`.
2. `app.cli.ingest_staging` recusa-se a ler um ficheiro que esteja
   dentro da árvore de trabalho do Git e que **não** esteja coberto pelo
   `.gitignore` (`assert_file_is_not_trackable_by_git`) — uma segunda
   barreira, em código, contra um export com dados reais ser
   acidentalmente `git add`ado, além da disciplina manual já documentada
   em `docs/DATA_MIGRATION_RUNBOOK.md`. Nunca falha "a fechado": qualquer
   erro a invocar o Git (ausente, timeout, ambiente sem repositório)
   deixa passar — o disparador real (`.gitignore` + revisão manual de
   `git status`) continua sempre ativo.
3. `app.migration.seed_dev.run_seed()` recusa-se a correr em
   `staging`/`production` (`assert_seed_allowed_environment`, mesma
   barreira `HARDENED_ENVIRONMENTS` de `app/config.py`) — antes desta
   revisão, nada impedia tecnicamente correr o seed sintético contra uma
   base de dados de staging, só a disciplina documentada em
   `docs/STAGING_CHECKLIST.md`.
4. `backend/.env.staging.example` e `frontend/.env.staging.example`
   (novos, distintos de `.env.example` de local/dev): todos os valores
   obrigatórios em staging já com placeholder explícito (nunca um valor
   plausível-mas-falso que alguém possa esquecer-se de substituir),
   comentários a explicar a origem de cada um (qual app registration
   Entra ID, qual secção do runbook). `docs/STAGING_RUNBOOK.md` (novo) é
   o procedimento operacional completo — comandos exatos para as duas
   app registrations Entra ID, PostgreSQL, migrações, os 5 utilizadores,
   health checks, logs, backups/rollback, testes de aceitação, o piloto
   de 5 a 10 projetos, e como parar o ambiente; `docs/STAGING_CHECKLIST.md`
   passa a ser só o registo de sign-off, apontando para lá.

**Por decidir, não assumido nesta revisão (ver `docs/OPEN_QUESTIONS.md`):**
quem cria `Person`/`User`/`UserRole` reais em staging antes do primeiro
provisionamento (não existe ainda um script de seed dedicado a staging,
só o SQL/Python manual documentado em `docs/STAGING_RUNBOOK.md` secção
9.1); alojamento concreto (condiciona os comandos exatos de arranque,
logs e backups automáticos); "who can consent" no scope
`access_as_user`; ativar `ENTRA_JIT_LINK_BY_EMAIL` em staging (por
omissão, desligado).

**Testes:** `tests/test_ingest_staging_cli.py` (+8 — dry-run, subconjunto
por IDs/limite, barreira do Git), `tests/test_seed_dev_staging_guard.py`
(4, novo).

## D-050 — Bootstrap idempotente de utilizadores de staging, Dockerfiles, docker-compose.staging.example.yml

**Contexto:** D-049 deixou explicitamente por resolver quem cria os
`Person`/`User`/`UserRole` reais em staging — só um procedimento manual
Python/SQL documentado na secção 9.1 do runbook
(`docs/OPEN_QUESTIONS.md` pergunta 26). Também não existia nenhum
Dockerfile nem `docker-compose` de staging — só o `docker-compose.yml`
de desenvolvimento local (Postgres), sem imagens do backend/frontend.

**Decisão:**

1. `app.cli.provision_staging` (novo, mesmo desenho de
   `provision_entra_user.py`/`ingest_staging.py` — núcleo testável
   separado do `main()`/argparse, erro de negócio numa exceção dedicada):
   lê um ficheiro JSON **externo ao repositório** (reutiliza
   `assert_file_is_not_trackable_by_git` de `app.cli.ingest_staging`, sem
   duplicar essa lógica) e, de forma **idempotente**, semeia o catálogo
   de papéis/permissões (reutiliza `seed_catalog()` de
   `app.migration.seed_dev` tal como está — já seguro em qualquer
   ambiente) e cria/atualiza exatamente os `Person`/`User`/`UserRole`
   indicados, associando `entra_object_id` quando fornecido (mesma regra
   de não-reatribuição de `link_user_to_entra_object_id`, mas idempotente
   quando o valor já corresponde). Nunca cria projetos/tarefas/dados
   sintéticos; nunca remove um papel existente que não esteja no
   ficheiro; nunca guarda password (não existe esse campo no modelo,
   autenticação é sempre delegada ao Entra ID). Rejeita email/papel/
   Object ID duplicados ou inválidos antes de escrever seja o que for
   (validação atómica). Exige `--confirm` para escrever — sem essa flag,
   comporta-se sempre como `--dry-run`. Cada criação/atualização é
   auditada em `auth_audit_log` (evento `admin_bootstrap_user`; ligação
   de `entra_object_id`, evento `admin_provision_link`, mesmo nome já
   usado por `provision_entra_user.py`).

   **Revisão de hardening (antes do merge do PR #5) — duas barreiras
   adicionais, ambas na CLI real (`main()`), nunca no núcleo testável:**
   - **Staging-only:** `assert_staging_environment` recusa `main()` fora
     de `APP_ENV=staging` — nunca `production` (fora do âmbito deste
     comando), nunca `local` (usar `app.migration.seed_dev`), nunca
     `test` (os testes chamam `bootstrap_staging_users` diretamente,
     nunca via CLI, para continuarem a correr em SQLite).
   - **`--actor-email` deixa de ser texto livre:** `main()` resolve o
     email a um `User` ativo e confirma a permissão `admin.manage_users`
     (`_resolve_and_authorize_actor`) antes de qualquer escrita — email
     desconhecido, utilizador inativo, ou utilizador sem essa permissão
     são todos recusados, e nada é escrito (nem o catálogo) se a
     autorização falhar. Um utilizador comum nunca consegue criar nem
     promover ninguém (incl. administradores) através deste comando.
     Exceção deliberada e estreita: se a base de dados ainda não tiver
     nenhum `User` (arranque a frio — o mesmo problema do "primeiro
     administrador" de qualquer sistema novo), a verificação é
     dispensada só nesse caso, porque não existe nenhum "utilizador
     comum" que pudesse abusar da ausência de verificação; assim que o
     primeiro `User` existir, todas as corridas seguintes voltam a
     exigir um ator autorizado. `AuthAuditLog.detail` passa a incluir o
     `user_id`/`person_id` reais do ator verificado (nunca só o email em
     texto livre, exceto no próprio caso de arranque a frio, onde ainda
     não existe nenhum `User` a referenciar).
2. `backend/Dockerfile` (multi-stage, utilizador não-root, `HEALTHCHECK`
   em `/health`, **nunca corre `alembic upgrade head` no arranque do
   container**) e `frontend/Dockerfile` (multi-stage, build Node com as
   `VITE_*` passadas por `--build-arg`, `VITE_ENABLE_DEV_LOGIN=false`
   fixado no Dockerfile — nunca um `ARG` —, servido por nginx com
   fallback de SPA). `docker-compose.staging.example.yml` (novo, raiz do
   repositório) compõe os dois + um serviço `backend-migrate` separado
   (sob `--profile migrate`, nunca corre com um simples `docker compose
   up`) — documenta explicitamente que o PostgreSQL de staging deve ser
   um serviço gerido/externo (o serviço `db` comentado no ficheiro é só
   para testar a composição localmente). Nenhum recurso cloud é criado
   por estes ficheiros; não decide o alojamento (`docs/OPEN_QUESTIONS.md`
   pergunta 25 continua aberta) — só torna o arranque repetível
   independentemente do alojamento escolhido depois.
3. `docs/STAGING_BOOTSTRAP.md` (novo) — procedimento executável do
   bootstrap, sem exigir conhecimento de código. `docs/STAGING_RUNBOOK.md`
   secção 9.1 passa a apontar para `provision_staging` em vez do
   procedimento manual; secção 2 ganha uma subsecção sobre logout/
   renovação de sessão (comportamento já implementado em
   `frontend/src/auth/msal.ts`, agora documentado do ponto de vista do
   operador); secção 7 ganha a opção de arranque por containers.
   `docs/STAGING_CHECKLIST.md` secções 4/5/7 atualizadas para
   referenciar o novo comando e os dois eventos de auditoria esperados.
4. `.github/workflows/ci.yml` ganha o job `docker-build` (novo) —
   `docker build` do backend e do frontend (este último com placeholders
   óbvios via `--build-arg`, nunca segredos reais) e
   `docker compose -f docker-compose.staging.example.yml config` para
   validar a composição, com um `backend/.env` temporário (placeholders,
   apagado no fim do job) — nenhum destes passos sobe containers nem
   precisa de PostgreSQL real. Resolve a ressalva "não foi possível
   validar localmente sem Docker" desta mesma revisão.

**Por decidir, não assumido nesta revisão (ver `docs/OPEN_QUESTIONS.md`):**
alojamento concreto dos containers (cloud vs. on-premises, fornecedor);
tenant Entra ID real; domínio de staging; "who can consent" no scope
`access_as_user`; ativar `ENTRA_JIT_LINK_BY_EMAIL` em staging.

**Testes:** `tests/test_provision_staging_cli.py` (30, +14 na revisão de
hardening) — idempotência, criação/atualização, rejeição de email/papel/
Object ID duplicados ou inválidos, nunca reatribui um `entra_object_id`
já ligado, nunca cria `Project`, `dry_run` sem rasto, barreira do
ficheiro Git reutilizada; e, novos: `assert_staging_environment` recusa
`production`/`local`/`test` e aceita `staging`; ator desconhecido,
inativo, e sem `admin.manage_users` são todos recusados; ator autorizado
tem sucesso; `AuthAuditLog` grava o `user_id`/`person_id` reais do ator;
nenhum registo (incl. catálogo) é escrito quando a validação do payload
ou a autorização do ator falha; exceção de arranque a frio funciona uma
única vez (sem nenhum `User` na base de dados) e deixa de se aplicar
assim que existe pelo menos um. Suite completa: 266 passed, 2 skipped
(SQLite). Dockerfiles/`docker-compose.staging.example.yml` continuam por
validar com `docker build`/`docker compose` reais neste ambiente (sem
Docker disponível na sandbox onde este PR foi preparado) — YAML validado
sintaticamente (`ci.yml` e `docker-compose.staging.example.yml`
carregados com PyYAML sem erro); o novo job `docker-build` do CI corre
isto a sério no GitHub Actions (que tem Docker disponível), a confirmar
quando o CI remoto correr.

## D-051 — MVP de demonstração: interface nova, arranque num comando, modo demo só em `local`

**Pedido:** uma demonstração visualmente desenvolvida, em português de
Portugal, que qualquer pessoa consiga levantar com um comando e dados
sintéticos, sem Entra ID, alojamento, Graph, Claude, Financial nem dados
reais. Guia operacional: `docs/MVP_DEMO.md`.

**Decisões:**

1. **Interface sem biblioteca de UI externa.** Design system próprio em
   `frontend/src/styles/app.css` (tokens de cor com contraste AA, sidebar,
   cartões, tabelas, badges, barras de progresso, alertas, estados de
   carregamento/vazio/erro, modais, notificações) e ícones SVG inline
   (`src/components/Icon.tsx`). Nenhuma dependência nova no
   `package.json` — menos superfície de ataque, funciona offline, sem
   fontes remotas. Responsivo: sidebar completa em desktop, compacta
   (só ícones) em tablet, gaveta em ecrãs estreitos; ligação "saltar para
   o conteúdo", foco visível, separadores com setas, modais com Escape e
   foco contido.
2. **Indicadores sempre da API.** O painel apresenta só o que
   `GET /api/dashboard/summary` devolve. Dois campos aditivos no
   servidor: `projects_photos_pending` (mesma regra de D-043, via
   `compute_project_task_summary`) e `week_overview` (por dia da semana
   em Europe/Lisbon: tarefas abertas com prazo, tarefas concluídas,
   pessoas ausentes). "Ausentes hoje"/"próximas" na página de férias
   também vêm do dashboard.
3. **Permissões efetivas expostas por recurso, não deduzidas no
   cliente.** `ProjectRead.editable_fields` (mesma regra de D-028/D-035:
   todos os campos com `project.edit_all`, só a allowlist PM com
   `project.edit_own_progress` no próprio projeto, nada caso contrário),
   `ProjectRead.can_manage_tasks`, `TaskRead.can_edit` e
   `AbsenceRead.can_cancel`. A UI só mostra o que estes campos permitem;
   o servidor continua a validar cada escrita (nenhuma regra de
   autorização mudou). `/me` ganha `display_name` e `role_labels`.
4. **Filtros novos no servidor, não no cliente:** `GET /api/projects`
   aceita `status` (derivado das tarefas, filtrado depois do cálculo —
   nunca uma segunda regra), `start_from`, `start_to`;
   `GET /api/tasks` aceita `priority`.
5. **`DEMO_MODE` (omissão `false`)** — informativo (banner na UI,
   `/health.demo_mode`), mas **bloqueia o arranque em staging/produção**
   (`_enforce_hardening_in_non_local_envs`), tal como `AUTH_ENABLED=false`
   ou SQLite. `/health` expõe também `dev_login_available`
   (`APP_ENV` local/test e `AUTH_ENABLED=false`); o ecrã de login só
   mostra os utilizadores de demonstração quando o build o permite
   (`devLoginEnabled`) **e** o servidor o confirma — contra staging/
   produção a secção nunca aparece, e uma sessão de demonstração antiga é
   descartada.
6. **Seed de demonstração separado do seed de desenvolvimento.**
   `app/migration/seed_demo.py` só acrescenta (14 projetos, 2 técnicos
   sem login, ausências, histórico), nunca altera os dados de
   `seed_dev.py` de que os testes dependem, nunca cria `User` (continuam
   5 — D-003), é idempotente (projeto marcador) e gera datas relativas a
   hoje. `app/cli/demo.py` (`setup` = `alembic upgrade head` + seeds;
   `reset --yes` = `downgrade base` + `upgrade head` + seeds) recusa
   qualquer `APP_ENV` que não seja `local` — mais restrito do que o seed
   de desenvolvimento (que também aceita `test`), antes de tocar na base
   de dados. Nunca imprime a password do `DATABASE_URL`.
7. **Docker da demo sem tocar nas imagens de staging.**
   `docker-compose.demo.yml` reutiliza `backend/Dockerfile` (migrações e
   seed num serviço `demo-setup` explícito que termina antes de o
   `backend` arrancar — mesmo princípio de D-050: migrações nunca no
   arranque da app) e usa um `frontend/Dockerfile.demo` próprio
   (`VITE_ENABLE_DEV_LOGIN=true`, API na mesma origem via
   `docker/nginx.demo.conf`). `frontend/Dockerfile` continua a fixar
   `VITE_ENABLE_DEV_LOGIN=false`. SQLite num volume próprio — PostgreSQL
   não é necessário para a demonstração. Portas publicadas só em
   `127.0.0.1`. Alternativa sem Docker: `scripts/demo_local.py`
   (Windows/Linux/macOS).
8. **CI:** `docker-build` constrói também `Dockerfile.demo`; job novo
   `demo-smoke` arranca a composição e verifica frontend, `/health`,
   painel com dados sintéticos, 401 sem sessão e idempotência do seed ao
   recriar os containers.

**Validado nesta máquina:** backend 291 passed + 2 skipped (SQLite, 25
testes novos em `tests/test_demo_mvp.py`); frontend `npm run lint`,
`npm test` (53 testes, 35 novos) e `npm run build`; migrações
round-trip (`upgrade head` → `downgrade base` → `upgrade head`) e
`alembic check` sem diferenças; `app.cli.demo setup/reset`; aplicação
percorrida no browser como Chefe, PM e Comercial (desktop e tablet);
build "mesma origem" do `Dockerfile.demo` servido por um proxy local
equivalente ao nginx. **Não validado localmente (sem Docker nesta
máquina):** `docker build`/`docker compose` — ficam a cargo dos jobs
`docker-build` e `demo-smoke` do CI.

# Fase 2 — MVP de Operações

As decisões D-052 a D-056 documentam a fatia 1 do MVP de Operações
(inventário com reservas, dados satélite de projeto, mapa, calendário
ligado a tarefas, permissões de tarefas revistas, metas e indicadores
fundidos com o histórico) — ver `docs/PLAN_OPERATIONS_MVP.md` para o
desenho completo. D-057 documenta a fatia 2, que fecha o que tinha
ficado para depois: importadores implementados (não só desenhados), UI
de mapa/planeamento/dados de projeto, e a tab de inventário por projeto.
Nenhuma integração externa real foi ligada (Graph/ClickUp/Financial/
Claude continuam mock/fallback); nenhum dado real entrou no repositório.

## D-052 — Tarefas: visibilidade global do PM, escrita por identidade (criador/atribuído), nunca por ser o PM do projeto

**Decisão:** `task.view_all` passa a ser concedida também ao papel PM
(mantendo `task.edit_own`) — um PM vê tarefas de todos os projetos, não só
os seus (`can_view_task`/`visible_tasks_query`). Em contrapartida,
`can_edit_task`/`can_create_task` deixam de usar
`task.project.pm_person_id == ctx.person_id` como critério de posse para
quem só tem `task.edit_own`: passa a ser
`task.created_by_person_id == ctx.person_id OR
task.assigned_to_person_id == ctx.person_id`. `create_task` força
`assigned_to_person_id = ctx.person_id` quando o ator só tem
`task.edit_own` e rejeita (400) qualquer tentativa de indicar outra
pessoa; `update_task` rejeita (400) por inteiro qualquer pedido que toque
`assigned_to_person_id` vindo desse mesmo ator — nunca reatribuição,
mesmo para si próprio.

**Porquê:** pedido explícito da secção de tarefas do MVP de Operações —
um PM deixa de estar limitado aos seus projetos para *ver* o que se
passa na operação (coordenação entre equipas), mas continua sem poder
alterar o trabalho de outra pessoa só por ser o PM do projeto onde essa
tarefa vive. `task.edit_all` (Chefe/Administrador) não muda.

**Testes:** `tests/test_tasks_api.py` — visibilidade global confirmada
(`test_pm_sees_tasks_from_every_project`), edição só por
criador/atribuído mesmo dentro do próprio projeto
(`test_pm_cannot_edit_task_of_own_project_not_created_by_or_assigned_to_them`),
nunca reatribuição (`test_pm_cannot_reassign_task_even_one_they_created`),
criação só atribuída a si mesmo
(`test_pm_can_only_create_task_assigned_to_self`), Chefe continua a
reatribuir livremente (`test_chefe_can_reassign_any_task`).

## D-053 — Inventário: reserva/consumo/libertação/devolução como operações distintas; Admin, Chefe e PM partilham o stock físico central

**Decisão:** `app/services/inventory.py` implementa as quatro operações
do pedido como funções distintas e transacionais sobre
`InventoryMovement` — nunca um total editável. `InventoryItem.min_stock`,
`InventoryMovement.quantity` e `MaterialRequestItem.quantity` passam de
`Float` para `Numeric(14,3)` (pedido explícito desta fase, alargando a
regra já aplicada a dinheiro desde D-018).
`InventoryLocation` (novo) modela `central`/`project`/`vehicle`/
`supplier`; o seed cria uma única localização central
(`code="IDEALMINDE"`), nunca usada para decidir lógica de negócio por
comparação de texto.

`reserve_for_project` nunca deixa o disponível negativo;
`consume_from_project` exige reserva ativa suficiente no projeto (decisão
assumida — o pedido não define "consumo sem reserva", ver
`docs/OPEN_QUESTIONS.md` pergunta 29); `return_to_stock` aumenta o físico
central sem reabrir a reserva de origem (pergunta 30). Todas as operações
aceitam `idempotency_key` opcional — repetir a mesma chave devolve o
movimento já existente em vez de duplicar.

**Revisto depois do relatório inicial — PM recebe `inventory.manage_central`.**
A primeira versão desta decisão excluía o PM de `inventory.manage_central`
("opção mais segura" perante uma aparente contradição no pedido entre
secções). **O negócio confirmou explicitamente que essa leitura estava
errada:** Administrador, Chefe de Operações e PM podem todos gerir o
inventário central (entrada/ajuste), sem distinção — só
`allocate_project`/`consume_project`/`release_project` continuam
compostas com o âmbito de projeto já existente via `can_edit_project`
(reservar/consumir/libertar continuam limitados aos projetos que o PM
gere; entrada/ajuste não são um recurso por projeto). Corrigido em
`app/security/catalog.py` (`ROLE_PM` ganha `inventory.manage_central`) —
ver `docs/OPEN_QUESTIONS.md` pergunta 28 (resolvida).

**Testes:** `tests/test_inventory_ledger.py` (11, incluindo o exemplo
exato do pedido — 100 km entram, reserva 20, consome 5, liberta 10 ⇒
físico 95/disponível 90/reservado 5/consumido 5), `tests/test_inventory_api.py`
(11, permissões por perfil e por âmbito de projeto, incluindo a prova
ponta-a-ponta das seis operações que o PM tem de conseguir fazer).

## D-054 — Dados satélite de projeto (instalação/licenciamento/comunicação): três tabelas 1:1, nunca campos novos em `Project`

**Decisão:** `ProjectInstallationData`, `ProjectLicensingData`,
`ProjectCommunicationData` (novas, 1:1 com `Project`) em vez de alargar
`Project` — evita transformá-lo numa tabela com centenas de campos
opcionais. Uma única tabela de histórico partilhada,
`ProjectDataHistory` (`entity_type` distingue qual das três), em vez de
três tabelas de histórico quase idênticas. `PATCH` cria o registo na
primeira edição — nunca exige um passo de "criar" separado.

Permissões por domínio (`project.view_installation_data`,
`project.edit_communication_data`, etc.) compõem-se sempre com o âmbito
de projeto já existente (`can_view_project`/`can_edit_project`) — nunca
uma segunda lógica de "próprio projeto" duplicada por domínio.
`ProjectCommunicationData` nunca tem campos para PIN/PUK/password/login/
token — por desenho, não por validação de conteúdo (que não seria
fiável).

**Testes:** `tests/test_project_data_api.py` (9) — permissões por perfil
e por âmbito de projeto, criação na primeira edição, histórico por campo
alterado, nenhuma entrada duplicada quando o valor não muda.

## D-055 — Mapa, calendário ligado a tarefas: backend completo (UI implementada depois, ver D-057)

**Decisão:** `GET /api/map/data` devolve um único payload já filtrado
pela visibilidade do utilizador (projetos com/sem coordenadas,
fornecedores, pontos de recolha, pendências) — nunca listas completas
para o cliente filtrar. `ProjectIssue` pode ser convertida numa `Task`
(`related_task_id` liga as duas, nunca duplica a entidade).
`MAP_PROVIDER_ENABLED`/`MAP_TILE_URL`/`MAP_TILE_ATTRIBUTION` (novos,
`app/config.py`) tornam o provider de tiles configurável e opcional — sem
ele, o endpoint continua a funcionar, sem depender de um serviço externo.

`CalendarEvent` ganha `task_id`/`assigned_to_person_id`; a camada de
serviço valida sempre `task.project_id == event.project_id` antes de
gravar, em criação e edição — nunca confiado ao cliente. Continua
inteiramente local, sem Microsoft Graph (`graph_event_id` nunca
preenchido — D-010 mantém-se).

**Sem otimização automática de rotas**, por pedido explícito — a UI
implementada em D-057 só oferece seleção/ordenação manual e um link para
rota externa (Google Maps), nunca um cálculo de rota próprio.

**UI destas duas áreas, e das tabs de dados de projeto no detalhe do
projeto, implementadas numa fatia seguinte — ver D-057.**

**Testes:** `tests/test_map_api.py` (7), `tests/test_planning_api.py` (9)
— incluindo o bloqueio de uma tarefa de projeto diferente do evento.

## D-056 — Metas e indicadores: página única, reaproveita a definição de "instalação concluída" do dashboard

**Decisão:** `GoalPeriod` (+ `GoalPeriodHistory`) por trás de uma única
página "Metas e indicadores" — nunca duas entradas de menu separadas
("Metas"/"Dashboards"). Progresso (`realizado`/`percent`/`falta`/
`ritmo_esperado`/`projeção`) sempre calculado no servidor (mesma regra já
aplicada ao dashboard, D-041), nunca no frontend a partir de listas
completas. `expected_pace`/`projection` são quantizados a 3 casas
decimais — sem isto, divisão de `Decimal` produz dízimas com dezenas de
casas.

"Instalação concluída" reaproveita tal e qual a definição já usada pelo
dashboard (`Task.task_type == "comissionamento"` e `status == "done"`,
na data de `completed_at`) — nunca uma segunda definição divergente,
conforme o próprio pedido instrui explicitamente ("se o código existente
tiver fonte de verdade mais adequada, reutilizá-la e documentar").
`installations`/`projects_completed` e `kwp`/`power_installed`/
`power_delivered` produzem hoje o mesmo valor, por falta de dados para as
distinguir de facto — ver `docs/OPEN_QUESTIONS.md` pergunta 31.

**Testes:** `tests/test_performance_api.py` (8) — permissões, cálculo de
progresso a partir de tarefas reais, âmbito por PM vs. empresa inteira.

## D-057 — MVP de Operações, fatia 2: UI do mapa/planeamento, importadores implementados, tab de inventário por projeto

**Contexto:** uma auditoria contra o pedido original, feita depois do
relatório da fatia 1, apontou que várias peças descritas como "desenho
completo" ou "backend completo, sem UI" ainda não tinham interface nem
estavam realmente implementadas — nomeadamente o importador de notas
iniciais (documentado, não codificado), o mapa e o calendário de
planeamento (só API), e a ausência de qualquer forma de reservar/consumir
material por projeto a partir do browser. Esta decisão fecha essas
lacunas.

**Importador de notas iniciais — implementado (não só desenhado):**
`app/services/imports_notes.py` (extração de `<script type="application/
json" id="notas-iniciais-data">` de HTML via `html.parser`, nunca
`eval`/motor de JS; versão lida de `payload.formVersion`, nunca do nome
do ficheiro — testado explicitamente com um ficheiro chamado
`notas-iniciais-v11.html` cujo conteúdo é v12), `app/models/imports.py`
(`FieldImportBatch`/`Record`/`Conflict`), 4 endpoints
(`app/api/routes_imports.py`): preview (idempotente por hash),
`GET /{batch_id}`, listar/resolver conflitos, `apply` (exige confirmação
explícita e todos os conflitos resolvidos). UI em
`frontend/src/pages/ImportNotes.tsx` (arrastar ficheiro, preview,
resolução de conflitos, confirmação). Ver `docs/DATA_IMPORTS.md`.

**Documento original preservado, não só o payload extraído.** A primeira
versão desta funcionalidade guardava apenas `raw_payload_json` (o JSON já
normalizado) — uma auditoria de "criar auditoria"/"guardar o documento
original" confirmou que o ficheiro tal como foi submetido nunca ficava
persistido, impossibilitando confirmar uma importação contra a fonte
original. Corrigido com `FieldImportBatch.raw_document_text` (o texto
completo do ficheiro carregado) e `GET /api/imports/{batch_id}/document`
para o consultar — migração `f1134f80f657`.

**Importador de licenciamento (Excel) — confirmado implementado:**
`app/services/imports_licensing.py` + `app/cli/import_licensing.py`
(`--dry-run`/`--apply`/`--rollback`), nunca uma UI — decisão de segurança
mantida (ficheiro real nunca commitado, só a fixture sintética).

**Mapa (`/map`) e Planeamento (`/planning`) — UI implementada.**
`frontend/src/pages/Map.tsx`: Leaflet quando há `MAP_TILE_URL`
configurado, lista funcional sempre que não há (nunca depende de um
serviço externo para o resto da app funcionar); filtros, painel "sem
coordenadas" com edição manual, seleção múltipla + link de rota externa
(sem otimização automática, por pedido explícito), formulários de
fornecedor/ponto de recolha, pendências com conversão em tarefa.
`frontend/src/pages/Planning.tsx`: vistas de semana/mês/lista; filtros
todos/meus/por PM/por projeto/por responsável; criar e reagendar pelo
mesmo formulário; **deteção de conflitos de horário só no cliente**, a
partir dos eventos já carregados para o período visível — avisa
sobreposições para o mesmo responsável e exige confirmação explícita
antes de gravar, mas não bloqueia nem valida no servidor (o pedido não
especificava bloqueio rígido; o backend não tem essa restrição — ver
`docs/OPEN_QUESTIONS.md` pergunta 34).

**Tab "Inventário" no detalhe do projeto (nova).** Não existia nenhuma
forma de reservar/consumir/libertar/devolver material a partir do
browser — só `/inventory` (stock central) tinha UI. Adicionada uma tab
que mostra as necessidades de material do projeto e os seus movimentos,
com um formulário para as quatro operações — reaproveita os endpoints já
existentes e testados de `app/api/routes_inventory.py`
(`inventory.allocate_project`/`consume_project`/`release_project`,
validados sempre no servidor).

**Tarefas: cenário de dois PMs explicitamente testado.** Os testes já
cobriam "PM não edita tarefa de projeto sem PM" e "PM não edita tarefa de
outra pessoa no seu próprio projeto", mas não o caso pedido
explicitamente — uma tarefa de um projeto gerido por **outro PM**.
Adicionado `test_pm_can_view_but_not_edit_or_reassign_task_of_another_pms_project`
em `tests/test_tasks_api.py`, confirmando visibilidade (`task.view_all`)
sem direito de escrita nem de reatribuição.

**Seed:** `seed_dev.py:seed_calendar_events` acrescenta 3 `CalendarEvent`
sintéticos ligados a projetos/tarefas/pessoas reais, para `/planning` não
abrir vazio — mesma convenção das outras áreas do MVP (mapa, inventário,
metas).

**Testes:** +2 no backend (documento original preservado; cenário de
dois PMs) — 380 no total (+2 skipped); `tests/test_imports_notes.py` (16),
`tests/test_import_licensing_cli.py` (10), `tests/test_map_api.py` (7),
`tests/test_planning_api.py` (9) confirmados a passar. Frontend: +12
testes novos (`Map.test.tsx`, `Planning.test.tsx`) — 85 no total.
Validação visual manual de 22 cenários (login por perfil, todas as tabs
do projeto, mapa, planeamento, inventário por projeto, metas com todos
os filtros) contra dados de demonstração reais, incluindo o ciclo
completo notas→projeto→mapa→pendência→tarefa→calendário→inventário→metas.

## D-058 — Mapa operacional: `Task.category` e `attention` derivado (backend), reaproveitando o `/api/map/data` e o `InventoryLocation` já existentes

**Contexto:** um pedido nesta sessão descrevia um "Mapa Operacional" a
construir de raiz — `InventoryLocation`, endpoint `/api/operations-map`,
UI Leaflet nova — partindo do princípio de que nada disto existia ainda.
**Não era verdade:** `/api/map/data` (`app/api/routes_map.py`,
D-052/D-055), `InventoryLocation` (D-052), `ProjectIssue`/`PickupPoint`, e
a UI Leaflet de `/map` (D-057) já estavam implementados, testados, e
documentados (`docs/PLAN_OPERATIONS_MVP.md`, `docs/MAP_AND_PLANNING.md`,
`docs/INVENTORY_RULES.md`). Confirmado com o utilizador antes de
implementar (repositório como fonte de verdade, não o pedido colado) —
âmbito revisto para **só** as duas peças que de facto não existiam:
`Task.category` e um estado `attention` (green/yellow/red) derivado sobre
o endpoint já existente, sem UI nova nesta sessão, sem duplicar
`InventoryLocation`/mapa.

**`Task.category`** (`app/models/task.py`) — vocabulário pequeno e
controlado (`workflow|field|material|documentation|commercial|other`),
distinto de `task_type` (tipo funcional específico). `OPERATIONAL_TASK_CATEGORIES
= {field, material}` é a única definição no código (nunca strings
`"field"`/`"material"` soltas noutros ficheiros — `app/services/map.py`
importa a constante). Migração `25103ca9bfeb`: coluna `NOT NULL` com
`server_default` transitório (mesmo padrão de `f1134f80f657`), backfill
das 5 tarefas padrão via `DEFAULT_TASK_TYPE_CATEGORIES` (`visita_tecnica`/
`preparacao_instalacao`/`instalacao`/`comissionamento` → `workflow`,
`fotos_drive` → `documentation`); qualquer tarefa `custom` existente fica
em `other` — nunca inventada. `TaskCreate`/`TaskUpdate` validam contra
`TASK_CATEGORIES`; uma alteração de categoria gera `TaskHistory`, tal como
qualquer outro campo (nenhum endpoint dedicado).

**`attention` (green/yellow/red)** — nunca persistido, sempre calculado em
`app/services/map.py:_compute_attention` sobre `visible_projects_query`
(nunca `visible_tasks_query` — uma tarefa atribuída a alguém fora do
projeto que gere pode continuar visível em `/tasks`, mas nunca torna esse
projeto visível no mapa; testado explicitamente,
`test_task_assigned_to_pm_outside_their_projects_never_leaks_project_on_map`
em `tests/test_map_attention.py`). Regras: **red** se existir uma tarefa
operacional aberta (`category` em `field`/`material`, estado em
`OPEN_TASK_STATUSES`) `blocked`, `urgent`, ou atrasada (`Task.is_overdue`,
já em `Europe/Lisbon` — nenhuma lógica de fuso paralela); **yellow** se
não for red e existir uma tarefa operacional aberta, ou (só quando
`ctx.has_permission("inventory.view")`) material físico no local; **green**
caso contrário. Tarefas `workflow`/`documentation` nunca alteram
`attention` (testado). `next_operational_task` é determinístico
(due_date mais próxima → sem data por último → `created_at` → `id`).

**Material "no local" reaproveita o saldo reservado líquido já modelado**
(`reserva − liberta_reserva − consumo` por (item, projeto) — mesmo
conceito de `app/services/inventory.py:reserved_for_project`, D-053) —
este MVP não tem ainda um movimento de "entrega física" distinto de
"reserva", por isso não distingue as duas coisas; documentado aqui como
dívida técnica conhecida, não uma segunda fonte de verdade inventada.
Calculado em **uma única query agregada** (`GROUP BY project_id, item_id`
com `CASE`, portável SQLite/PostgreSQL), nunca uma chamada a
`reserved_for_project` por (item, projeto) num ciclo. `material_visible`
controla tudo: sem `inventory.view`, `has_material_on_site`/
`material_sku_count` ficam sempre `null` (nunca `false` — evita inferir
ausência de stock a partir de "sem permissão"), e material nunca torna um
pin amarelo para quem não o pode ver (testado).

**N+1 corrigido no mesmo endpoint (já existente antes desta sessão):**
`get_map_projects` fazia uma query de tarefas e uma de pendências **por
projeto**, e a rota chamava `compute_project_task_summary` (mais uma
query de tarefas) por projeto outra vez. Reescrito para 4 queries fixas,
independentes do número de projetos (projetos, tarefas de todos os
projetos visíveis, pendências agregadas por projeto, inventário agregado
por projeto) — `compute_project_task_summary` foi dividida numa função
pura (`compute_project_task_summary_from_tasks`, reaproveitada aqui) mais
o wrapper original inalterado para quem já a chama. Testado com
`test_map_data_query_count_does_not_grow_with_project_count`
(acrescenta 15 projetos com tarefa+movimento cada, confirma que o número
de queries não cresce proporcionalmente).

**`MapDataResponse.summary`** (novo) separa **`map_coverage_percent`**
(cobertura de coordenadas — problema de dados) de
**`operational_clean_percent`** (percentagem de projetos `green` — estado
operacional) sobre o mesmo denominador (`visible_active_projects`) — nunca
uma métrica de "limpeza" só que confunde as duas coisas (um projeto sem
coordenadas nunca é "sujo" por isso).

**Testes:** `tests/test_task_category.py` (9), `tests/test_map_attention.py`
(17, incluindo segurança de scope, as 9 regras de negócio de
red/yellow/green por categoria/estado pedidas, visibilidade de
inventário, 2 SKUs nunca se anulam, cobertura de coordenadas, resumo,
número de queries limitado, e os 5 cenários do seed abaixo) — 406 testes
de backend no total (+2 skipped), sem nenhuma regressão na suite
pré-existente. Frontend: inalterado nesta sessão (sem UI nova, por
decisão explícita de âmbito) — 85 testes Vitest continuam a passar,
`npm run build`/`npm run lint` sem erros (o payload só ganhou campos
novos, aditivos).

**Seed sintético (`app/migration/seed_dev.py:seed_sample_projects`)**
ganhou os 5 cenários do mapa operacional, sem projetos dedicados extra —
reaproveita projetos já existentes do seed de Fase 1.5, acrescentando só
duas tarefas operacionais novas: "Instalação Sintética F — PM Legado"
(green, nenhuma alteração — já não tinha tarefa field/material aberta),
"Instalação Sintética A — Início Próximo" (yellow — nova tarefa
`category=field`, `status=todo`, sem atraso), "Instalação Sintética B —
Atrasada" (red — nova tarefa `category=material`, aberta e atrasada;
distinta da tarefa de workflow já bloqueada nesse projeto, que nunca
conta), "Instalação Sintética de Demonstração" (yellow só por material
físico — reaproveita a reserva de cabo já existente em
`seed_map_and_inventory`, sem tarefa operacional nenhuma), "Instalação
Sintética Incompleta" (sem coordenadas — já assim, sem alteração).
Verificado manualmente contra o seed real (`python -m
app.migration.seed_dev` + `GET /api/map/data`) e testado em
`test_seed_covers_the_five_map_scenarios`. `seed_sample_projects`
continua idempotente (guarda existente `if db.query(Project).count() > 0:
return` — confirmado a correr o seed duas vezes sem duplicar).

**UI do mapa — implementada** (continuação desta sessão, depois de
confirmação explícita):
`frontend/src/pages/Map.tsx` colore os pins do Leaflet e o indicador na
lista funcional pelo `attention` devolvido pelo servidor
(`ATTENTION_COLORS`/`ATTENTION_TONES`/`ATTENTION_LABELS` — nunca
recalculado no frontend, `var(--success)`/`var(--warning)`/`var(--danger)`
já usadas no resto da app), mostra a barra `MapSummaryBar`
(`data.summary` — cobertura de coordenadas, estado operacional limpo,
projetos em atenção/críticos, mesmo padrão de `StatCard` já usado no
painel inicial), e o painel de detalhe (`Modal`) de cada instalação
mostra tarefas operacionais (com contagem de atrasadas/bloqueadas/
urgentes), a próxima ação determinística, e material — ou "sem permissão
para ver inventário" quando `material_visible=false` (nunca inventa um
"não há material" para quem não pode saber). `frontend/src/api/client.ts`
ganhou os tipos `MapAttention`/`MapNextOperationalTask`/`MapSummary` e os
campos novos em `MapProject`/`MapData`, espelhando exatamente o schema do
backend.

**Validado manualmente** contra o seed real (`/map`, utilizador Chefe):
os 5 cenários do seed (ver acima) aparecem corretamente — "Atenção"/
"Crítico"/"Sem pendências operacionais" na lista e no painel de detalhe,
resumo com 87.5% de cobertura / 62.5% limpo / 2 em atenção / 1 crítico
(números reais do seed sintético).

**Testes:** `tests/Map.test.tsx` ganhou fixtures completas para
`MapProject`/`MapData` (todos os campos novos) e um teste dedicado ao
resumo/attention — 86 testes Vitest no total (+1, era 85). `npm run
lint`/`npm run build` sem erros.

## D-059 — Mapa operacional: filtros por attention, pendências e material (UI-2)

Segunda fatia da UI do mapa (a seguir a D-058, que fechou o contrato do
backend e os pins/resumo por `attention`). Filtros novos em
`frontend/src/pages/Map.tsx`, feitos **no cliente** sobre o payload já
devolvido — sem endpoints novos, para os volumes atuais (~300 projetos):
**Atenção** (crítico/atenção/sem pendências operacionais), **Com
pendências** (pendências abertas OU tarefas operacionais abertas) e
**Material no local**.

A lógica vive em `frontend/src/utils/mapFilters.ts`
(`filterMapProjects`, função pura, testada sem Leaflet/jsdom em
`mapFilters.test.ts`) e nunca recalcula `attention` — só filtra pelo valor
que o servidor devolveu. O filtro "Material no local" só é oferecido
quando algum projeto tem `material_visible=true`; um `has_material_on_site`
`null` (sem `inventory.view`) nunca conta como "sem material" nem como
"com material".

Fora desta fatia (mantém-se para depois): filtro por cliente dedicado,
"só críticos" como atalho, "sem coordenadas" como filtro (já existe a
lista própria), e clustering de pins (UI-3).

**Testes:** +7 em `mapFilters.test.ts`, +1 em `Map.test.tsx` — 94 testes
Vitest no total (era 86). `npm run lint`/`build` sem erros; validado
manualmente contra o seed real ("Atenção = Crítico" reduz a lista a 1
instalação).

## D-060 — Mapa operacional: clustering de pins (UI-3) e filtro por cliente

Terceira e última fatia planeada da UI do mapa (a seguir a D-058/D-059).

**Clustering:** `leaflet.markercluster@^1.5.3` (+ `@types/leaflet.markercluster`),
o único plugin adicionado — compatível com Leaflet 1.9.4 e React 18.3, sem
qualquer atualização de major. Só as **instalações** são agrupadas; fornecedores,
recolhas e pendências ficam soltos (significados diferentes, poucos pontos).
O ícone do cluster usa a **pior `attention` dos pins agrupados**
(`clusterIcon` em `Map.tsx`, `var(--success|--warning|--danger)`), nunca as
cores por omissão do plugin, que se confundiriam com o semáforo. Cada pin
continua a abrir o mesmo painel de detalhe ao clicar.

**Filtro por cliente** (`MapFilters.client`, correspondência exata, opções
derivadas do payload). O atalho "só críticos" do plano não foi adicionado:
**Atenção → Crítico** já faz exatamente isso.

**Testes:** +1 em `mapFilters.test.ts` — 95 Vitest no total. O Leaflet não é
testado em jsdom (decisão do plano); o clustering foi validado manualmente
no browser com `MAP_PROVIDER_ENABLED=true` contra o seed real (cluster "2"
cor de atenção; pins individuais nas cores do semáforo).

Fora do MVP, por decisão do plano original (Fase F), mantém-se: criar
tarefas a partir do mapa, movimentos de stock, visitas, otimização de rotas.

## D-061 — Mapa operacional, Fase F (1/n): criar tarefa a partir da instalação selecionada

Primeira funcionalidade da Fase F do plano original, que só podia começar
depois de o mapa read-only e o contrato do backend estarem estáveis
(D-058 a D-060, todos integrados em `main`). A Fase F é feita **uma
funcionalidade por PR**, da de menor risco para a de maior.

**O que é:** o painel de detalhe de uma instalação (`Map.tsx`) ganha o botão
**Criar tarefa** (só visível com `task.edit_all` ou `task.edit_own`), que abre
`CreateTaskModal` (título, categoria — omissão `field` —, prioridade, prazo).
Depois de criar, o mapa é recarregado, porque o `attention` do projeto pode ter
mudado.

**Sem backend novo:** reaproveita `POST /api/tasks`. O servidor continua a ser a
única autoridade — um PM só cria no seu projeto e só atribuída a si (D-052),
categoria e prioridade são validadas contra `TASK_CATEGORIES`/`TASK_PRIORITIES`;
o botão escondido na UI é conveniência, nunca segurança. Um erro do servidor
(403/400) aparece no modal.

`frontend/src/api/client.ts` ganhou `TaskCategory`/`TASK_CATEGORY_LABELS` e o
campo `category` em `Task`/`TaskCreatePayload` (o backend já o devolvia desde
D-058, mas o tipo do frontend ainda não o conhecia).

**Testes:** +3 em `Map.test.tsx` (botão escondido sem permissão; criação com o
`project_id`/categoria/prioridade certos e recarga do mapa; título obrigatório)
— 98 Vitest no total. Validado no browser contra o seed real: uma tarefa
`material` urgente criada em "F — PM Legado" fez o projeto passar de verde a
"Crítico" e o resumo de 62.5% para 50% limpo / 1 para 2 críticos.

**Fica para as fatias seguintes da Fase F** (cada uma exige decisões próprias,
sobretudo as que mexem em stock): registar entrega/recolha de material (o ledger
físico ainda não distingue "reservado" de "entregue no local" — dívida de D-058),
visitas futuras, fornecedores no mapa com pedido, combinar vários trabalhos numa
deslocação e otimização de rota. Gamificação fica fora.
## D-062 — Mapa operacional, Fase F (2/n): visitas futuras

Segunda funcionalidade da Fase F (a seguir a D-061), escolhida por reaproveitar
o calendário já existente (D-055) e não mexer em stock.

**Backend (`GET /api/map/data`):** cada projeto ganha `next_visit`
(`{id, title, starts_at, ends_at, assigned_to_display_name}`),
`upcoming_visits_count` e `visits_visible`. "Visita futura" = `CalendarEvent` do
projeto, **não cancelado** e com início **no futuro**. Só a quem tem
`calendar.view`; sem essa permissão os dois campos ficam `null` (nunca "0
visitas" — mesma regra do material, D-058) e `visits_visible=false`. Não
alteram `attention`: uma visita agendada não é dívida operacional.

**Sem N+1:** +2 queries fixas, independentes do número de projetos (eventos de
todos os projetos visíveis; nomes dos responsáveis das próximas visitas). O SQL só
pré-filtra com 1 dia de margem e o corte exato "no futuro" faz-se em Python
(`_as_aware`, assume UTC para datetimes sem tzinfo), porque o SQLite compara
datetimes com e sem fuso de forma diferente do PostgreSQL. A próxima visita é
determinística (início mais próximo; desempate por id). O scope continua a ser
`visible_projects_query` — visitas de projetos fora dele nunca aparecem.

**Frontend:** a lista mostra "próxima visita" por instalação; o detalhe mostra a
próxima visita (com responsável) e o total agendado, ou "Sem permissão para ver o
calendário". O botão **Agendar visita** (só com `calendar.manage`) abre
`ScheduleVisitModal`, que cria um `CalendarEvent` via o `POST
/api/planning/events` existente — o servidor valida permissão e âmbito. A visita
fica como **rascunho local** (sem Outlook/Graph, D-010 mantém-se).

**Fusos horários:** o formulário usa `datetime-local` (hora de parede de Lisboa) e
converte com o novo `lisbonWallClockToIso` (`utils/dates.ts`) para um instante
com offset, correto no horário de Verão/Inverno e nas mudanças de hora. Não
repete o padrão de `Planning.tsx` (anexar `:00` a uma string sem offset, que o JS
interpreta na hora local de quem executa — a causa da falha de CI em D-058/CI).
Corrigir o `Planning.tsx` fica fora desta fatia, para não misturar âmbitos.

**Testes:** +5 backend (`test_map_visits.py`: mais cedo + contagem exata;
passadas/canceladas ignoradas; sem `calendar.view` => `null`; não altera
`attention`; sem fuga de scope) — 411 no total (+2 skipped). +10 Vitest (5 do
`lisbonWallClockToIso`, incluindo a mudança de hora de 29/03, e 5 de UI) — 108 no
total. Validado no browser contra o seed real: agendar 15/07/2099 09:00 gravou
`08:00Z`, contagem 1 -> 2, `attention` inalterado.

**Fica para as fatias seguintes:** entrega/recolha de material (ledger ainda não
distingue "reservado" de "entregue"), fornecedores no mapa com pedido, combinar
trabalhos numa deslocação, otimização de rota.

## D-063 — Planeamento: horas de Lisboa enviadas como instantes com offset

Correção de um defeito pré-existente em `frontend/src/pages/Planning.tsx`
(PR #13), descoberto ao investigar a falha de CI de `Planning.test.tsx`
(D-058) e confirmado ao implementar as visitas futuras (D-062).

**Problema.** O formulário de Planeamento trabalha em **hora de Lisboa**
(`toDatetimeLocalValue` formata com `Europe/Lisbon`), mas enviava
`"…T09:00:00"` **sem offset**. Com PostgreSQL (colunas `timestamptz`) o
servidor lê uma string sem offset como UTC; no horário de Verão o evento
aparecia **1 hora mais tarde** do que o utilizador escolheu. O mesmo padrão
afetava dois outros pontos: a deteção de sobreposições (`findConflicts`
comparava um instante "hora local de quem executa" com instantes reais) e o
filtro do intervalo visível (`starts_from`/`starts_to` de
`listCalendarEvents`).

**Correção.** Os três pontos passam a usar `lisbonWallClockToIso`
(`utils/dates.ts`, introduzido em D-062): converte a hora de parede de Lisboa
(valor de um `<input type="datetime-local">`) no instante UTC correspondente,
em ISO com offset. Só usa `Date.UTC` e `Intl` com `timeZone` explícito, por
isso é independente do fuso do browser/runner e correto no Verão/Inverno e nas
mudanças de hora (testado com 29/03/2026).

**Relação com o CI.** A falha original de `Planning.test.tsx` era este mesmo
padrão nos *fixtures* (datas sem offset, lidas na hora local do runner UTC). Foi
resolvida só nos testes, fixando `TZ=Europe/Lisbon` em `vitest.config.ts`
(D-058). Este D-063 corrige a causa na aplicação; o `TZ` do Vitest mantém-se,
porque os fixtures continuam a usar datas sem offset.

**Limitação conhecida.** Em **SQLite** (só desenvolvimento/testes) o servidor
devolve datetimes **sem offset**, porque o SQLite descarta o fuso; a
apresentação continua ambígua nesse motor. Em **PostgreSQL** (staging/produção)
o servidor devolve offset e fica correta. Não foi validado contra um
PostgreSQL real, só pela suite de frontend; o job `backend-postgres` do CI
não exercita o frontend. Confirmar num ambiente com PostgreSQL antes de
depender disto em produção.

**Testes:** +3 em `Planning.test.tsx` (09:00 de Verão → `08:00Z`; 09:00 de
Inverno → `09:00Z`; intervalo visível com offset). Contagem atual: 111 Vitest e
411 de backend (+2 skipped).

## D-064 — Inventário: entrega e recolha de material (Fase F, 3/n)

Terceira funcionalidade da Fase F e a única que mexe no livro de stock. Fecha
a dívida registada em D-058: o "material no local" do mapa era o **saldo
reservado**, porque não existia nenhum movimento de entrega.

**Como foi decidido.** Desenho aditivo proposto e confirmado com o negócio
antes de escrever código (mudava o significado de "material no local" no
mapa). A resposta sobre a recolha corrigiu uma premissa minha: a obra recebe
**mais do que o reservado** (excedente da transportadora, ou reforço
propositado como painéis de reserva), e esse excedente é o que se recolhe. O
desenho inicial limitava a entrega ao reservado e estaria errado.

**Modelo.** `MOVEMENT_ENTREGA`/`MOVEMENT_RECOLHA` e a coluna nova
`inventory_movements.from_site_quantity` (nullable, sem default — migração
`5cef0d14b6e6`, round-trip testado, sem backfill). `no_local = Σ entrega −
Σ recolha − Σ from_site_quantity(consumo)`. Detalhe e regras em
`docs/INVENTORY_RULES.md`.

**Porquê `from_site_quantity` e não um replay cronológico.** Abater o consumo
ao material no local exige saber a ordem entre entregas e consumos, mas
`created_at` usa `server_default=func.now()` (1 segundo em SQLite), pelo que
um replay seria não determinístico. Guardar no consumo quanto abateu torna o
saldo uma **soma independente da ordem**, calculável numa única query.

**O que NÃO mudou.** Reservar, libertar, consumir e devolver mantêm-se; o stock
físico central, o disponível e o reservado não são afetados por entregas/
recolhas (testado). O consumo continua a exigir reserva.

**Permissões** novas `inventory.deliver_project`/`inventory.collect_project`
para Administrador, Chefe de Operações e PM (PM só nos seus projetos, como
reservar/consumir); Comercial e Financeiro recebem 403.

**Mapa.** `has_material_on_site`/`material_sku_count` passam a vir de
`on_site_balances_by_project` (uma query agregada, sem N+1). Consequência
deliberada: material **reservado mas não entregue já não conta**; um projeto
**concluído com material ainda no local fica amarelo** (o exemplo do pedido
original). O seed ganhou uma entrega de 15 km ao projeto de demonstração para
o cenário "amarelo só por material" se manter.

**UI.** Separador Inventário do projeto: cartão **Material no local** (inclui
excedentes sem necessidade associada) e as ações **Entregar no local**/
**Recolher do local** no modal de movimentos.

**Limitação assumida.** Entrega/recolha não movem o stock central: material
que veio direto do fornecedor, ou que regressou ao armazém, é regularizado à
parte com `entrada`/`ajuste`. Não foi pedida nem decidida uma ligação
automática, para não inventar contabilidade de stock.

**Testes.** +25 backend (`test_inventory_on_site.py`: saldo, excedente acima da
reserva, recolha limitada, isolamento de stock/reserva, abate no consumo,
independência da ordem, movimentos antigos, idempotência, permissões, mapa,
projeto concluído) — 436 no total (+2 skipped); 3 testes do mapa atualizados
para a nova semântica. +6 Vitest (`ProjectDetail.inventory.test.tsx`) — 117.
Validado no browser contra o backend real: recolher 20 com 15 no local foi
recusado com a mensagem do servidor; recolher 5 e entregar 3 conectores
atualizaram o cartão; stock central (95/80/15) inalterado; o mapa passou a 2 SKUs.

**Por fazer na Fase F:** fornecedores no mapa com pedido de material, combinar
trabalhos numa deslocação, otimização de rota.

## D-065 — Mapa operacional, Fase F (4/n): otimização da ordem de paragens

Quarta funcionalidade da Fase F. Até aqui a rota era só um link externo pela
ordem de seleção, "sem otimização automática, por pedido explícito"
(`MAP_AND_PLANNING.md`); a otimização passou a ser pedida.

**Restrições já registadas e mantidas.** A otimização de rotas é sempre um
**cálculo determinístico do backend** (`ARCHITECTURE_PROPOSAL.md`, secção de
integrações) e o fornecedor de serviço de mapas/rotas continua por decidir
(`OPEN_QUESTIONS.md`). Por isso: **sem serviço externo de routing, sem
geocoding, sem chamadas de rede**.

**Distância em linha reta — uma aproximação assumida.** Usa-se a distância de
grande círculo (haversine). Serve para **comparar a ordem** das paragens, mas
não é a distância de condução: a API devolve `distance_model: "great_circle"`
e a UI diz "distâncias em linha reta (aproximação) — não são quilómetros de
condução". Estradas, portagens e tempos ficam fora; se forem precisos, é a
altura de decidir o serviço de routing.

**Algoritmo** (`app/services/route_optimization.py`). A primeira paragem é o
ponto de partida e fica sempre em primeiro. Com `round_trip` a rota fecha na
partida; sem ele, termina onde for mais curto.
- Até **12 paragens**: **ótimo garantido** (programação dinâmica sobre
  subconjuntos, Held-Karp).
- De 13 a **25** (máximo): vizinho mais próximo + 2-opt — boa, **não
  garantidamente ótima** (a resposta diz `method: "heuristic"` e a UI avisa).
- Determinístico: o mesmo pedido dá sempre a mesma rota (empates pelo menor
  índice). Pior caso medido: ~28 ms (12 exatas) e ~36 ms (25 heurísticas).

**API.** `POST /api/map/optimize-route` (`map.view`), só lê. O cliente envia só
`{kind, id}` de cada paragem (`project|supplier|pickup`) — **nunca coordenadas**
(o schema rejeita campos extra): o servidor resolve coordenadas e visibilidade,
com a mesma regra do mapa (`visible_projects_query`, só ativos). Uma paragem
inexistente, inativa ou fora do âmbito do utilizador dá **a mesma mensagem** (não
revela se existe nem o nome). Paragens repetidas e sem coordenadas são recusadas
(estas últimas nomeando-as). A resposta traz a ordem, a distância de cada
perna e acumulada, o total, a distância na ordem pedida e a poupança.

**UI.** No cartão "Rota externa": **Otimizar ordem**, opção **Voltar ao ponto de
partida**, lista ordenada com quilómetros e poupança. "Abrir rota" usa
**exatamente a ordem calculada pelo servidor**; o resultado é descartado se a
seleção ou a opção mudarem (deixa de valer).

**Testes.** +29 backend (`test_route_optimization.py`): o resultado exato é
comparado com **força bruta** sobre 180 conjuntos aleatórios de semente fixa
(2 a 7 paragens, aberto e com regresso); início fixo e cada paragem uma só vez;
determinismo; heurística vs ótimo (≤15% acima); limites; e o endpoint
(paragens mistas, coordenadas do cliente rejeitadas, mesma mensagem segura,
PM sem fuga de âmbito, sem escrita, 401) — 465 no total (+2 skipped). +7
Vitest — 124. Validado no browser contra o seed real: 5 paragens em ordem má
(1269 km) passaram a 704 km (ordem ótima), com a partida fixa.

**Por fazer na Fase F:** fornecedores no mapa com pedido de material (o pedido
de material ainda não existe como fluxo) e combinar vários trabalhos numa
deslocação.