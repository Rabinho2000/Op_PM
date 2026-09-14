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
migrar ainda os 295 projetos reais"). Quando a Fase 2 chegar, a ingestão
real continua a ser um comando/script operado deliberadamente, não um
botão da UI.

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

**Validado manualmente ponta-a-ponta** (backend + frontend a correr
localmente, sem tenant Entra real): ecrã de login sem erros de consola
com a configuração MSAL vazia (placeholder), botão "Entrar com Microsoft"
visivelmente desativado com a explicação, secção de desenvolvimento
separada por um divisor visual; login de desenvolvimento continua
funcional ponta-a-ponta (entrar, `NavBar` a mostrar a sessão, listagem de
projetos a carregar, logout a limpar a sessão e devolver a `/login`).
