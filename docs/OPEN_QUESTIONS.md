# Perguntas em aberto — Op_PM

> Cada pergunta bloqueante/importante indica: impacto, a decisão necessária,
> e uma recomendação por defeito (quando existe uma razoável) — mas nenhuma
> resposta foi assumida no código ou nos outros documentos sem confirmação.
> Várias perguntas de versões anteriores deste documento já ficaram
> resolvidas — ver "Resolvidas" no final.

## Bloqueantes

### 1. Tenant Microsoft 365 / Entra ID

**Impacto:** o backend já valida tokens Entra ID reais (`app/security/entra_auth.py`,
D-024, reforçado em D-029 — `oid` obrigatório, tenant/scp/`nbf`
validados, JIT linking configurável e auditado, validador cacheado) e o
frontend já tem o login MSAL real implementado e ligado (D-031 —
Authorization Code + PKCE, access token para a API, renovação silenciosa,
logout) — mas sem um tenant/app registration reais, ninguém consegue
emitir um token de verdade nem preencher `VITE_ENTRA_CLIENT_ID`/
`VITE_ENTRA_TENANT_ID`/`VITE_ENTRA_API_SCOPE` para testar isto
ponta-a-ponta, e a Fase 6 (Graph real — email/calendário, renumerada nesta revisão) também não pode
avançar. É a única peça que falta para fechar a autenticação real; nada
no código precisa de ser reescrito quando isto existir — só configurado.

**Decisão necessária:** confirmar que existe um tenant Microsoft 365
administrável, com alguém capaz de registar duas aplicações (app
registrations) — uma SPA pública para o frontend (MSAL.js, Authorization
Code + PKCE, sem client secret) e uma API para o backend expor o âmbito
`access_as_user` — conceder consentimento de administrador para os
âmbitos necessários no backend (Mail.Send, Calendars.ReadWrite,
Files.ReadWrite, etc., quando a Fase 6 avançar), e fornecer
`ENTRA_TENANT_ID`/`ENTRA_CLIENT_ID`/`ENTRA_REQUIRED_SCOPE` (backend) e
`VITE_ENTRA_CLIENT_ID`/`VITE_ENTRA_TENANT_ID`/`VITE_ENTRA_API_SCOPE`
(frontend — ver `frontend/.env.example`).

**Recomendação por defeito:** nenhuma — depende inteiramente de recursos
que só a organização tem.

### 2. Sistema Financial

**Impacto:** sem isto, a Fase 5 (custos reais/margens) fica limitada a
custo estimado; `CsvFinancialAdapter` já existe mas precisa de um CSV real
exportado manualmente enquanto não há decisão.

**Decisão necessária:** que sistema é, e que opções de integração existem —
API, exportação CSV/Excel, ou só relatório manual.

**Recomendação por defeito:** usar o modo CSV (`FINANCIAL_MODE=csv`) como
primeiro passo, independentemente da resposta final — é o caminho que
funciona com o menor compromisso técnico.

### 3. Regra oficial para os campos obrigatórios de um projeto

**Impacto:** sem isto, os endpoints de criação/edição de projeto da Fase 1
não sabem que validação aplicar; o modelo atual (`Project`) tem quase todos
os campos opcionais de propósito, para não bloquear a preservação dos
projetos incompletos (108–198 dos 295 projetos reais, conforme a análise do
repositório do código legado, não têm coordenadas/email/contacto).

**Decisão necessária:** o responsável operacional define quais campos são
realmente obrigatórios (e a partir de quando — na criação, ou só para
avançar de fase do workflow).

**Recomendação por defeito:** nenhum campo obrigatório à criação (preserva
o padrão atual dos dados reais); obrigatórios só para avançar certas
etapas do workflow (ex. não pode agendar comissionamento sem contacto).

### 4. Calendários e equipas a considerar no planeamento de visitas

**Impacto:** sem isto, `get_availability` (Fase 6) não sabe que calendários
consultar via Graph.

**Decisão necessária:** confirmar se é o calendário individual de cada PM,
um calendário partilhado de operações, ou ambos.

**Recomendação por defeito:** calendário individual de cada PM + um
calendário partilhado de "visitas" para visibilidade cruzada.

### 5. Quem aprova o quê

**Impacto:** o modelo de permissões (`ARCHITECTURE_PROPOSAL.md` secção 5)
já distingue "criar rascunho" de "aprovar", mas a matriz exata de quem
aprova email/visita/pedido de material/adjudicação/custo por tipo de
projeto ainda não está confirmada.

**Decisão necessária:** confirmar a matriz de aprovação por perfil e, se
necessário, por valor/tipo de projeto (ex.: acima de X€ precisa de
aprovação adicional).

**Recomendação por defeito:** a matriz já implementada em
`app/security/catalog.py` (Chefe de Operações e Administrador aprovam
tudo; PM aprova só o seu próprio envio/evento) — a confirmar ou ajustar.

### 5-B. Allowlist de campos editáveis por PM: campos com impacto comercial

**Impacto:** `app/security/project_fields.py` (D-028, revisto em D-035)
distingue, no servidor, os campos de `Project` que um PM
(`project.edit_own_progress`) pode alterar no seu próprio projeto dos que
exigem `project.edit_all` (Chefe de Operações, Administrador). Ficaram
administrativos por omissão, nesta revisão de fecho de Fase 1,
`lat`/`lon` (coordenadas), `power_kwp`/`power_raw` (potência),
`start_date`/`upac_connection_date_raw`/`award_year_raw` (datas legadas) e
`commercial_assumptions` — nenhum tem uma regra de negócio confirmada
sobre se um PM pode corrigi-los sem aprovação, e todos têm potencial
impacto comercial ou contratual (potência/coordenadas afetam
dimensionamento e localização real da instalação; `commercial_assumptions`
é, pelo nome, um pressuposto comercial; as datas legadas podem ter valor
contratual). Enquanto ficam administrativos, uma correção legítima de um
PM (ex.: coordenadas erradas na migração) exige sempre um Chefe de
Operações/Administrador a aplicá-la — potencial atrito operacional se a
resposta acabar por ser "sim, o PM pode".

**Decisão necessária:** para cada um destes campos, o responsável
operacional confirma se um PM pode editá-lo no seu próprio projeto sem
aprovação adicional, ou se deve continuar administrativo (ou passar a
exigir um fluxo de aprovação específico, ainda não modelado).

**Recomendação por defeito (já aplicada como omissão técnica, a
confirmar como decisão de negócio):** manter todos administrativos até
resposta explícita — a opção mais restritiva, nunca assumida como
definitiva. Ver `app/security/project_fields.py` para a lista completa e
`docs/DECISIONS.md` D-035.

## Importantes

### 6. Uma visita pode envolver mais do que uma pessoa/equipa?

**Impacto:** afeta o modelo de `visits`/`calendar_events` (hoje 1
`created_by`/1 `approved_by`, sem lista de participantes internos além dos
`attendees` do evento).

**Recomendação por defeito:** assumir que pode haver múltiplos
participantes internos desde já no modelo de `calendar_events.attendees`
(já suportado), sem alteração de schema.

### 7. Horários, zonas geográficas, almoço, limites diários

**Impacto:** necessário para `propose_visit_dates`/`analyze_travel` (Fase 6
e o cálculo determinístico de deslocações).

**Recomendação por defeito:** nenhuma sem confirmação — este cálculo é
demasiado específico do negócio para assumir um valor por defeito seguro.

### 8. O cliente escolhe a data ou só recebe propostas?

**Impacto:** afeta se `email_drafts`/`visits` precisam de um mecanismo de
confirmação externa (ex. link para o cliente escolher).

**Recomendação por defeito:** só propostas por email nesta fase — evita
construir um portal externo sem necessidade confirmada.

### 9. Fornecedores a suportar na primeira versão

**Impacto:** afeta o catálogo inicial de `suppliers` na Fase 5.

**Recomendação por defeito:** nenhum pré-carregado — criar conforme
necessidade real, sem inventar uma lista.

### 10. Como são recebidos e aprovados os orçamentos de fornecedores

**Impacto:** afeta o fluxo de `material_requests` (estado
`orcamento_recebido` → `aprovado`).

**Recomendação por defeito:** anexo de documento (via biblioteca
documental, Fase 9) + aprovação manual no estado do pedido — sem
integração automática de parsing de orçamento nesta fase.

### 11. Estrutura atual da Drive e permissões por documento

**Impacto:** afeta o desenho da Fase 9 (biblioteca documental).

**Recomendação por defeito:** nenhuma sem confirmação — herdar a estrutura
e permissões do SharePoint existente é mais seguro do que assumir uma nova.

### 12. Quantos anos de histórico devem ser migrados

**Impacto:** afeta o volume e o esforço da Fase 4 (migração real).

**Recomendação por defeito:** migrar tudo o que existir no export legado —
o mecanismo de staging já preserva campos incompletos sem custo adicional
por migrar mais dados.

### 13. Fecho de visita/comissionamento: bloqueio rígido ou aviso?

**Impacto:** afeta `form_responses.status` (`bloqueado_fotos` como estado
rígido vs. apenas um aviso ignorável).

**Recomendação por defeito:** bloqueio rígido, com possibilidade de
override explícito por um Administrador/Chefe de Operações (nunca
silencioso).

### 14. Orçamento/limite de uso da API Claude

**Impacto:** afeta a Fase 7 — sem limite definido, o custo pode escalar sem
controlo.

**Recomendação por defeito:** definir um teto mensal antes de
`CLAUDE_ENABLED=true` alguma vez ser verdadeiro fora de desenvolvimento.

### 15. Retenção de dados (backups, logs, exports antigos)

**Impacto:** afeta o plano de backups/segurança (`docs/PLAN.md`).

**Recomendação por defeito:** nenhuma sem confirmação — é uma decisão de
compliance/privacidade que não deve ser assumida tecnicamente.

### 16. `upacRegisto`/`m2mCard`: há um sistema externo que devia ser a fonte de verdade?

**Impacto:** a revisão de hardening da Fase 0 deu a estes dois campos
legados (registo UPAC, cartão M2M) um lugar explícito no `Project`
(`upac_registration`, `m2m_card` — ver `ARCHITECTURE_PROPOSAL.md` secção
5), mas como cópia simples do export legado, com Op_PM como fonte de
verdade por omissão. Se existir um sistema de licenciamento/DGEG ou do
operador de rede que devesse ser a fonte de verdade real destes valores, a
uma fase de integração futura (Fase 8 — ClickUp, ou outra ainda não
planeada) precisa de o saber.

**Decisão necessária:** confirmar se estes valores vêm só do processo
manual da equipa (e por isso Op_PM é mesmo a fonte de verdade) ou de um
sistema externo ainda não mapeado.

**Recomendação por defeito:** manter Op_PM como fonte de verdade até haver
evidência de um sistema externo — não inventar uma integração que pode não
existir.

### 17. Quem resolve a fila de reconciliação de PM na migração real?

**Impacto:** a Fase 4 (migração real) depende de alguém decidir, para cada
nome de PM desconhecido/ambíguo do export legado, se corresponde a uma
pessoa já em `people`, se deve criar uma pessoa nova (histórica, sem
login), ou se deve ficar sem PM associado (`app.migration.people_reconciliation`,
D-023). Os 8 PMs históricos do legado provavelmente geram vários destes
itens logo na primeira ingestão real.

**Decisão necessária:** quem (Chefe de Operações? Administrador?) tem
autoridade para tomar estas decisões, e se há casos que precisam de
confirmação do próprio PM (ex.: confirmar que "Gonçalo Palacino" e
"Gonçalo P." no legado são a mesma pessoa).

**Recomendação por defeito (já implementada como omissão técnica, a
confirmar como decisão de negócio):** a Fase 1 já restringiu as
permissões `migration.view`/`migration.resolve` a Administrador e Chefe
de Operações (`app/security/catalog.py`) — falta só confirmar que é
mesmo esta a intenção de negócio antes da Fase 4, e resolver quem faz o
trabalho concreto de revisão (pode ser uma pessoa diferente de quem tem a
permissão técnica, ex. um PM a confirmar a identidade de um antigo colega,
com o Chefe de Operações só a "carimbar" a decisão final na fila).

### 18. Dashboard inicial: métricas semanais, separação operacional/comercial, férias e aniversários

**Impacto:** `docs/PLAN.md` Fase 2 (Dashboard inicial) só define o roadmap
de alto nível nesta revisão — nenhuma métrica, campo obrigatório, ou
fonte de dados foi assumida, de propósito.

**Decisão necessária:**
- Que estatísticas semanais exatamente (projetos que avançaram de fase?
  pedidos de material novos? algo mais?) e como se calculam.
- O que distingue a "visão operacional" da "visão comercial" — que
  métricas pertencem a cada uma, e se são páginas separadas ou a mesma
  página filtrada por papel.
- **Férias e aniversários não têm modelo de dados hoje** — `Person` não
  tem data de nascimento nem qualquer registo de ausências/férias. É
  preciso confirmar a fonte (mantida dentro do Op_PM? importada de um
  sistema de RH? do perfil Microsoft 365, via Graph — Fase 6?) antes de
  desenhar o schema.

**Recomendação por defeito:** nenhuma — implementar um dashboard sem
estas respostas arrisca construir a métrica errada; ver
`docs/PLAN.md` Fase 2 para o detalhe de cada pendência.

### 19. Workflow de projetos: processo oficial real e requisitos para avançar de fase

**Impacto:** `docs/PLAN.md` Fase 3 (Workflow de projetos) tem o modelo de
dados já pronto desde a Fase 0 (`phases`/`workflow_stages`/
`workflow_subtasks`/`project_stage_progress`/`project_subtask_progress`),
mas semeado só com um processo genérico de exemplo
(`GENERIC_WORKFLOW` em `app/migration/seed_dev.py`), nunca o processo
real de 6 fases da Solcor.

**Decisão necessária:**
- Carregar as fases/etapas/subtarefas oficiais reais (substituindo o seed
  genérico) — quem confirma esta lista e o texto exato de cada item.
- Que combinação de etapas/subtarefas concluídas é exigida para uma fase
  poder ser considerada fechada/avançada — hoje nada bloqueia isto.
- Se o responsável por etapa é sempre o PM do projeto, ou varia.

**Recomendação por defeito:** nenhuma — carregar o processo real errado
(ou inventar requisitos de avanço de fase) pode travar trabalho real por
engano; ver `docs/PLAN.md` Fase 3 para o detalhe de cada pendência.

### 20. Férias/ausências: registo direto ou fluxo de pedido → aprovação?

**Impacto:** `Absence` (Fase 1.5 — MVP dashboard/workflow) marca qualquer
ausência criada como `aprovada` de imediato, sem nenhum passo de
aprovação por outra pessoa — ver `docs/DECISIONS.md` D-042.

**Decisão necessária:** o negócio quer mesmo registo direto (cada pessoa
regista as suas próprias férias, o Chefe de Operações regista as de
qualquer pessoa, sem aprovação intermédia), ou precisa de um fluxo real
de pedido → aprovação (ex. PM pede, Chefe aprova antes de contar como
confirmada)?

**Recomendação por defeito (já implementada):** registo direto — mais
simples, e nada impede adicionar um estado `pendente` + uma ação de
aprovação mais tarde de forma aditiva, sem alterar o que já existe.

### 21. Dashboard: férias/aniversários visíveis a toda a equipa, ou só aos próprios?

**Impacto:** um PM ou Comercial (sem `absence.view_all`) só vê as suas
próprias férias/ausências e o seu próprio aniversário no dashboard — nunca
os de colegas. Ver `docs/DECISIONS.md` D-044.

**Decisão necessária:** confirmar se esta é mesmo a política pretendida,
ou se (prática comum em equipas pequenas) todos devem ver as férias/
aniversários de toda a gente, para coordenação de equipa.

**Recomendação por defeito (já implementada):** o lado mais restritivo —
mudar para "toda a equipa vê tudo" é uma alteração pequena (dar
`absence.view_all` a mais perfis em `app/security/catalog.py`), mas o
inverso (restringir depois de já ter sido visto por todos) não desfaz a
exposição já acontecida.

### 22. Unificar `Task` com o sistema `Phase`/`WorkflowStage`/`WorkflowSubtask`?

**Impacto:** o MVP dashboard/workflow criou uma entidade `Task` genérica
(ver `docs/DECISIONS.md` D-039) que coexiste, sem qualquer ligação, com o
sistema de processo já modelado antes desta fase (`Phase`→
`WorkflowStage`→`WorkflowSubtask` + `ProjectStageProgress`/
`ProjectSubtaskProgress`) — este último semeado (`seed_workflow`) mas sem
endpoint nem UI ligados em nenhuma fase até agora.

**Decisão necessária:** vale a pena investir em unificar os dois (ex. cada
`WorkflowSubtask` do catálogo gerar automaticamente uma `Task` por
projeto, com o catálogo a continuar a definir a ordem/responsável por
omissão), ou os dois propósitos são suficientemente diferentes para
coexistirem indefinidamente (checklist de processo fixo vs. tarefas
livres com responsável/prazo/prioridade)?

**Recomendação por defeito:** nenhuma — depende de o negócio querer mesmo
usar o processo fixo por fases (`Phase`/`WorkflowStage`) nalguma fase
futura; se nunca vier a ser ligado a um endpoint/UI, mais vale remover
essa estrutura do que mantê-la morta.

### 23. A checklist padrão de 5 tarefas deve ser fixa ou configurável?

**Impacto:** `app/services/tasks.py:ensure_default_tasks_for_project` cria
sempre as mesmas 5 tarefas (visita técnica, preparação da instalação,
instalação, comissionamento, colocar fotos na Drive) para qualquer
projeto — não há noção de "tipo de projeto" com checklists diferentes.

**Decisão necessária:** todos os projetos (residencial, comercial,
industrial, manutenção...) seguem mesmo esta mesma checklist de 5 passos,
ou existem tipos de projeto que precisam de passos diferentes?

**Recomendação por defeito:** manter fixo enquanto só há um tipo de
projeto observado nos dados reais — tornar configurável por tipo de
projeto é um alargamento aditivo simples quando/se for preciso.

### 24. Unificar `Task` com o futuro formulário de visita técnica e comissionamento?

**Impacto:** este MVP mantém `Task` (ver D-039) como unidade operacional
e preserva, sem alteração nem ligação, os modelos antigos `Phase`/
`WorkflowStage` (pergunta 22 acima). O roadmap prevê um formulário
dedicado de visita técnica e comissionamento numa fase futura — se for
construído contra `Task` (ou contra um novo modelo próprio), duplica
esforço/dados com qualquer um dos dois sistemas já existentes se não for
decidido antes.

**Decisão necessária:** confirmar, antes de desenhar esse formulário,
qual das três entidades (`Task`, `Phase`/`WorkflowStage`, ou uma nova) é
a fonte de verdade única para o processo de execução de projeto — não
avançar com uma migração de dados arriscada agora só para unificar
precocemente.

**Recomendação por defeito:** nenhuma decisão de migração nesta fase —
documentar a pendência (feito aqui) e decidir no momento de desenhar o
formulário de visita técnica/comissionamento.

### 25. Alojamento de staging/produção (bloqueia parte do runbook)

**Impacto:** `docs/STAGING_RUNBOOK.md` secções 7 (arranque), 10 (logs) e
11 (backups) só têm comandos genéricos (Uvicorn/Gunicorn em primeiro
plano, `pg_dump` manual) porque não há decisão de alojamento (cloud vs.
on-premises, fornecedor concreto). Sem isto, staging pode ser levantado
manualmente uma vez, mas não de forma repetível/automatizada.

**Atualização (D-050):** `backend/Dockerfile`, `frontend/Dockerfile` e
`docker-compose.staging.example.yml` já existem — tornam o arranque
repetível independentemente do alojamento escolhido (o mesmo
`docker compose up` funciona em qualquer VM/serviço de containers). Isto
**não decide** o alojamento em si (onde esses containers correm, quem os
gere, backups do PostgreSQL) — só remove a dependência de decidir o
alojamento antes de ter um arranque repetível.

**Decisão necessária:** fornecedor/mecanismo concreto de alojamento do
backend, frontend, e do serviço PostgreSQL gerido de staging (o `db`
comentado em `docker-compose.staging.example.yml` é só para testar a
composição localmente, nunca staging real — ver
`docs/STAGING_RUNBOOK.md` secção 3).

**Recomendação por defeito:** nenhuma — ver `docs/PLAN.md` "Plano de
deployment" para a recomendação já registada (cloud pequeno alinhado com
o tenant Microsoft 365).

### 26. "Who can consent" no scope `access_as_user` da app registration da API

**Impacto:** `docs/STAGING_RUNBOOK.md` secção 2.1 pede esta decisão ao
criar o scope delegado — "Admins and users" facilita o primeiro login de
cada um dos 5 utilizadores (sem pedir a um admin para consentir por
cada um), mas "Admins only" é mais restritivo por omissão.

**Decisão necessária:** confirmar a política preferida da organização
para este tenant.

**Recomendação por defeito:** "Admins and users" — com só 5 utilizadores
conhecidos e "Grant admin consent" já aplicado ao nível da app
registration (secção 2.2 do runbook), o consentimento individual nunca
chega a ser pedido na prática; a diferença só importa se outro
utilizador tentar aceder sem ter sido provisionado.

### 27. Ativar `ENTRA_JIT_LINK_BY_EMAIL=true` em staging?

**Impacto:** por omissão, desligado em staging/produção (D-029) — cada
utilizador só fica ligado ao seu `entra_object_id` via
`app.cli.provision_entra_user` (`docs/STAGING_RUNBOOK.md` secção 9.2),
nunca automaticamente a partir de um token com email correspondente.

**Decisão necessária:** com só 5 utilizadores conhecidos de antemão, o
provisionamento manual é preferível (mais controlo, auditado
explicitamente) ou a ligação automática por email pouparia trabalho
suficiente para justificar o risco de ligar a pessoa errada por um email
duplicado/trocado?

**Recomendação por defeito:** manter desligado — 5 utilizadores é pouco
para o provisionamento manual ser um fardo, e a ligação automática
remove a barreira humana que confirma que o `entra_object_id` certo foi
associado à pessoa certa.

## MVP de Operações

Perguntas levantadas ao implementar inventário/dados de projeto/mapa/
calendário/metas (ver `docs/PLAN_OPERATIONS_MVP.md`). Nenhuma bloqueou o
desenvolvimento — todas resolvidas pela opção mais segura, reversível,
documentada aqui e no código.

### 28. PM deve ter `inventory.manage_central`? — **RESOLVIDA**

**Impacto:** o pedido original parecia contradizer-se entre a secção 2
("Podem alterar o inventário central: Administrador; Chefe de Operações;
Project Managers") e a secção de permissões ("PM: pode alterar stock
central e operar os seus próprios projetos") vs. o resto do pedido, que
trata o stock central como um recurso partilhado por toda a operação,
não por projeto.

**Resolvida — decisão de negócio confirmada explicitamente:**
Administrador, Chefe de Operações **e PM** podem todos gerir o
inventário central (entrada/ajuste), sem distinção. A leitura anterior
("opção mais segura" perante uma aparente contradição) estava errada.
`app/security/catalog.py` (`ROLE_PM` ganhou `inventory.manage_central`)
e `app/migration/seed_dev.py` (via `ROLE_PERMISSIONS`) já refletem isto;
testado em `tests/test_inventory_api.py::test_pm_can_do_every_inventory_operation_end_to_end`.
As restrições de projeto mantêm-se para reservar/consumir/libertar
(`allocate_project`/`consume_project`/`release_project`) — um PM continua
sem poder operar o inventário de um projeto que não gere.

### 29. Consumo de inventário sem reserva prévia

**Impacto:** o pedido não define o que acontece ao tentar consumir
material que não foi reservado antes.

**Decisão assumida:** `consume_from_project` exige reserva ativa
suficiente no projeto — rejeita com erro caso contrário. Reversível em
`app/services/inventory.py:consume_from_project` se o negócio preferir
permitir consumo direto (com ou sem criar a reserva implicitamente).

### 30. Devolução de material: reabre a reserva de origem?

**Decisão assumida:** não — `return_to_stock` aumenta o stock físico
central "livre para reservar de novo", nunca reabre automaticamente a
reserva do projeto que consumiu. Documentado em
`docs/INVENTORY_RULES.md`.

### 31. Distinção entre métricas de "Metas e indicadores"

**Impacto:** o pedido lista `installations`, `projects_completed`, `kwp`,
`power_installed` e `power_delivered` como métricas distintas, mas o
modelo de dados atual não tem dados para as distinguir de facto (ex.
produção real vs. potência nominal instalada).

**Decisão necessária:** confirmar se/quando estas métricas devem divergir
(ex. `power_delivered` vir de `ProjectLicensingData.annual_production_kwh`
em vez de `Project.power_kwp`).

**Decisão assumida:** todas usam hoje o mesmo cálculo (potência nominal
dos projetos com comissionamento concluído no período) — ver
`docs/PERFORMANCE_METRICS.md`. Revisível numa função isolada
(`app/services/performance.py:_realized_value`) quando confirmado.

### 32. UI do mapa, calendário, e das tabs de dados de projeto

**Impacto:** esta PR entrega backend completo e testado para o mapa
(`/api/map/data`), calendário (`/api/planning/*`), e os três modelos
satélite de projeto (`/api/projects/{id}/installation-data` etc.), mas
sem páginas/tabs novas no frontend — ver
`docs/PLAN_OPERATIONS_MVP.md` secção 10 para a razão de priorização
(o volume de frontend pedido — mapa interativo com camadas/filtros,
calendário semanal/mensal/lista — é maior, sozinho, que todo o resto da
Fatia 1 combinado).

**Decisão necessária:** confirmar prioridade desta UI face aos
importadores (secção 33) para a próxima fatia.

### 33. Importadores de notas iniciais e Excel de licenciamento

**Impacto:** desenho completo em `docs/DATA_IMPORTS.md`, não
implementado nesta PR — é a parte de maior risco de segurança/qualidade
de dados de todo o pedido (parsing de ficheiros de terceiros com dados
pessoais). Ver `docs/PLAN_OPERATIONS_MVP.md` secção 9.3 para a
justificação completa de a deixar para uma PR própria, mais pequena e
mais fácil de rever isoladamente.

**Decisão necessária:** nenhuma — é trabalho pendente, não uma decisão de
desenho por confirmar. Prioridade relativa à pergunta 32 fica ao critério
do negócio.

## Podem ser decididas mais tarde

- **Atualização major de `react-router-dom` (6→7) e `vitest`/
  `@vitest/mocker` (3→5).** Resolvido nesta integração (`mvp-ready`,
  D-048): `vite` já foi atualizado para `6.4.3` (sem precisar de ir a 8),
  o que eliminou a única vulnerabilidade **alta** (`GHSA-fx2h-pf6j-xcff`).
  Ficam por resolver 4 vulnerabilidades **moderadas** sem correção dentro
  do intervalo semver instalado — só resolvidas com um salto de versão
  maior de cada pacote (D-031, e D-033 que acrescentou `vitest` como
  primeira dependência de testes do frontend — já atualizado uma vez, de
  `vitest@2` para `vitest@3.2.7`, especificamente para eliminar uma
  vulnerabilidade **crítica** do servidor de UI do Vitest,
  `GHSA-5xrq-8626-4rwp`; a moderada remanescente de `@vitest/mocker`,
  `GHSA-82fw-gwwq-j7x9`, só se resolve saltando para `vitest@5`). Nenhuma
  destas é exploratória à distância no código deste repositório tal como
  está hoje (`vitest`/`@vitest/mocker` — dependências só de
  desenvolvimento/teste, nunca incluídas no bundle de produção
  (`vite build`); `react-router-dom` — open-redirect, relevante sobretudo
  com entrada de utilizador não confiável nas rotas, que esta app não tem
  ainda). Decidir quando fazer estas migrações (e testar as mudanças de
  API do `react-router-dom` v7 e do `vitest` v5) antes de um primeiro
  deployment público.
- Fornecedor do serviço de mapas/rotas.
- Modelo específico do Claude a usar em produção (a interface já é
  agnóstica ao modelo — `Settings.claude_model`).
- Aparência final do dashboard (Fase 1.5 entregou uma primeira versão
  funcional, estilo utilitário/tabelas — sem investimento de design ainda).
- Notificações por email, Teams, ou só dentro da aplicação (`notifications`
  já modelado, sem canal de entrega definido).
- Relatórios adicionais além do semanal.
- Exportações para Excel/PDF.
- Alojamento (cloud vs. on-premises) e orçamento — necessário antes do
  primeiro deployment de staging, não antes.
- Robustez do worker/scheduler (APScheduler vs. fila dedicada) — só
  relevante quando houver volume real a justificar revisão (D-013).

## Resolvidas nesta sessão

- **"Quem cria `Person`/`User`/`UserRole` reais em staging (não há seed
  dedicado)?"** — Resolvida: `python -m app.cli.provision_staging`
  (D-050) cria o catálogo de papéis/permissões e os `Person`/`User`/
  `UserRole` reais a partir de um ficheiro JSON externo ao repositório,
  de forma idempotente e auditada — ver `docs/STAGING_BOOTSTRAP.md`.
  `docs/STAGING_RUNBOOK.md` secção 9.1 já não descreve um procedimento
  manual Python/SQL.
- **"O repositório deve continuar público ou passar a privado?"** —
  Resolvida: mantém-se público, por instrução explícita do utilizador. Ver
  `docs/DECISIONS.md` D-015. A regra que passa a valer sempre: nunca dados
  reais, segredos, ou exports de produção neste repositório.
- **"Como conciliar 5 utilizadores ativos com o histórico de 8 PMs?"** —
  Resolvida arquiteturalmente: separação `Person`/`User` (D-003) — todos os
  PMs (ativos ou não) existem como `Person` para preservar o histórico;
  só até 5 têm `User` (conta de login) associada.
- **"Qual é o primeiro MVP: migração real dos 295 projetos, ou uma
  ferramenta operacional interna (dashboard/tarefas) com dados
  sintéticos?"** — Resolvida por instrução explícita do negócio: o MVP
  passou a ser Fase 0 + Fase 1 + Fase 1.5 (dashboard/workflow), **sem** a
  Fase 2 — ver "Primeiro MVP recomendado" em `docs/PLAN.md`. A migração
  real dos 295 projetos continua planeada como Fase 2, só que depois deste
  MVP, não antes.
