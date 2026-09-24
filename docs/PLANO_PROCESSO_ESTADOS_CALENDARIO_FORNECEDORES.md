# Plano — tarefas fixas, estados de projeto, calendário de obras e fornecedores

> **Estado: proposta para aprovação.** Nada aqui está implementado. Foi escrito
> depois de ler o `solcor-gestao.html` legado, o export real
> (`Op_PM_export_projetos.json`, só agregados — nenhum dado de cliente é citado)
> e o código atual. **Atualizado com as respostas de D1, D2, D5, D7 e D8**; as
> restantes decisões estão na secção 6, cada uma com uma recomendação por omissão.

## 1. O que o código já tem (e não vamos refazer)

| Peça | Estado atual | Consequência |
|---|---|---|
| `Phase`, `WorkflowStage`, `WorkflowSubtask` | Existem (modelo + seed **genérico**). Têm exatamente os campos do legado: responsável (papel), dependência, offsets de início/fim em dias, ponto de contacto. **Sem endpoints nem UI.** | A feature 1 é a "Fase 3" do `PLAN.md`: falta o catálogo real, a API e a UI. |
| `ProjectSubtaskProgress`, `ProjectStageProgress` | Existem: uma linha por (projeto, subtarefa) e (projeto, etapa). Nunca são escritas. | O progresso por projeto tem onde viver; não é preciso criar 295 × 77 linhas. Linha em falta = por fazer. |
| `Task` com 5 tarefas padrão (visita técnica, preparação, instalação, comissionamento, fotos) | Só o seed sintético as cria. | São o modelo **operacional** (mapa, planeamento). Continuam como estão; **não** as crio nos 295 projetos. |
| `Project.status` (derivado) | `nao_iniciado / em_curso / concluido`, calculado das tarefas. | **Colisão de nome** com o estado novo — ver secção 6, D1. |
| `Project.clickup_status_mirror` | Já ingerido do export (`clickupStatus`). | Contém precisamente os 6 estados pedidos. |
| `ProjectInstallationData.installer` | Texto livre. O `subcontractor` do export **nunca foi ingerido**. | Falta ingerir e normalizar. |
| `Supplier` + `GET/POST/PATCH /api/suppliers` | Existe (usado pelo mapa e pelos pedidos de material): nome, `category`, `contact`, `email`, `address`, `lat/lon`. **Sem página própria** e a listagem exige `map.view`. | A feature 4 é sobretudo uma página nova + pequenos ajustes. |

## 2. Dados reais que condicionam o desenho

Do export dos 295 projetos:

- **Estado (`clickupStatus`):** 212 certificado final · 50 entregue ao cliente ·
  17 em preparação · 5 construído · 4 em construção · 5 on hold pelo cliente ·
  1 "vendido" · 1 vazio. As duas exceções (2 projetos) não cabem nos 6 estados e
  ficam em **On hold pelo cliente** (D2, decidido).
- **Instalador (`subcontractor`):** 9 nomes distintos; **56 projetos sem
  instalador** (55 vazios + 1 nulo). Três instaladores concentram a maioria.
- **Datas:** 294 de 295 têm `startDate`. **No legado `startDate` é o dia 1 do
  processo (handover), não o início da obra.** A obra em si é a fase "Obra",
  calculada como `startDate + offset da etapa` (dias 41 a 49 no modelo base),
  deslocada por `shift` (um objeto por projeto, 294 preenchidos). `workDays` vem
  sempre vazio. **Não existe data de fim de obra no Op_PM** (`Project` só tem
  `start_date`).
- **Progresso (`done`):** 245 projetos têm progresso, com chaves posicionais
  (`"2.0"`, `"2.1"`…). 33 têm `commissionedAt`.
- **Processo legado:** 6 fases, **18 etapas, 77 subtarefas**, 12 pontos de
  contacto. Responsáveis: Comercial, Sales Support, PM, Duarte, Bárbara,
  VM (subempreiteiro), CE (provavelmente chefe de equipa — ver D5).

> **Confidencialidade.** Este repositório é público e o texto das 18 etapas e 77
> subtarefas é o processo interno da Solcor. O `seed_dev` usa deliberadamente um
> processo **genérico**. Por isso o catálogo real **não entra no git**: um script
> commitado extrai-o do teu `solcor-gestao.html` para um JSON local (fora do
> repositório), e um comando administrativo carrega-o na base de dados (mesmo
> desenho do `provision_staging`). O código e os testes usam sempre o genérico.

## 3. Feature 1 — Tarefas fixas por projeto

**Objetivo:** cada projeto mostra o processo completo (6 fases → 18 etapas → 77
subtarefas), com progresso, responsável e prazos.

**Desenho**
- **Catálogo real** carregado por CLI a partir do JSON local (idempotente, por
  `code`): fases, etapas (responsável, dependência, offsets, contacto, nota) e
  subtarefas. Os responsáveis do legado que são nomes de pessoas (Duarte,
  Bárbara) ou externos (VM, CE) têm o tratamento definido em D5: Duarte é o
  Duarte Batista (chefe do departamento); Bárbara é a Bárbara Ferreira; VM é o
  subempreiteiro Verde Milenar; CE = chefe de equipa (a confirmar).
- **API** (leitura + escrita, sempre no âmbito do projeto — 404 fora dele):
  `GET /api/projects/{id}/workflow` (fases → etapas → subtarefas com o estado de
  cada uma, datas planeadas, atraso) e
  `PATCH …/workflow/subtasks/{id}` / `…/stages/{id}/contact` (marcar feito, com
  quem/quando). Nova permissão `workflow.update_progress`; auditoria em
  `ProjectHistory`.
- **Datas planeadas** = `start_date` do projeto + offsets da etapa (+ `shift` se
  existir). Em atraso = fim planeado passou e etapa não concluída.
- **UI:** novo separador "Processo" em `ProjectDetail` (timeline por fase,
  checklist, ponto de contacto, barra de progresso) e `workflow_progress_percent`
  passa a ler daqui.
- **Fase 2 desta feature (opcional):** o painel passa a mostrar "tarefas em
  atraso" e "a fazer agora" calculadas do processo, como o legado.

**Migração do progresso:** converter as chaves `"12.3"` do `done` para
`ProjectSubtaskProgress`. A semântica exata do sufixo `.0` (marcador da etapa?)
e da numeração das subtarefas **tem de ser verificada contra o código do legado
com um teste de equivalência** antes de migrar (é o risco principal desta
feature).

## 4. Feature 2 — Estados do projeto

**Estados** (códigos estáveis + rótulo): `on_hold_cliente` · `preparacao` ·
`construcao` · `construido` · `entregue_cliente` · `certificado_final`.

**Desenho**
- Coluna própria `Project.lifecycle_status` (nome distinto do `status` derivado,
  que passa a chamar-se "Progresso" na UI para não haver duas coisas com o mesmo
  nome). Constante única no backend, exposta à UI (nada de listas duplicadas).
- **Valor inicial** = mapeamento do `clickup_status_mirror` (tabela acima).
  "vendido" e o estado vazio mapeiam para `on_hold_cliente` (D2). Qualquer valor
  futuro desconhecido fica **sem estado** e aparece numa lista para decisão
  humana, nunca adivinhado.
- Alteração via `PATCH /api/projects/{id}/status`, permissão nova
  `project.change_status`, com `ProjectHistory` (quem, quando, de/para).
- Filtro por estado na lista de projetos, no mapa e no calendário; badge de
  estado na lista e no detalhe.
- O espelho do ClickUp **não é tocado**. Quando a Fase 8 (ClickUp real) chegar,
  decide-se quem manda (D1).

## 5. Feature 3 — Calendário de obras por instalador

**Pré-requisitos (PR próprio):**
1. **Instalador como entidade** (`installers`: nome, ativo) com
   `Project.installer_id`; ingestão do `subcontractor` e normalização dos nomes
   (D3). O texto livre atual mantém-se só como histórico.
2. **Datas da obra** `work_start_date` / `work_end_date` em `Project`,
   editáveis. Preenchimento inicial: `startDate` + offset da etapa de início de
   obra até ao fim da última etapa da fase "Obra", com `shift` (D4). Projetos
   sem datas ficam fora do calendário e numa lista "por planear".

**Calendário**
- `GET /api/works/calendar?from&to&pm_person_id&status&installer_id` → obras
  (projeto, PM, estado, instalador, datas), filtradas por
  `visible_projects_query` (mesmo âmbito de permissões do resto da app), com
  número de queries limitado e testado.
- **Página `/works`:** linhas = instaladores (mais "Sem instalador"), eixo do
  tempo horizontal com zoom semana/mês/trimestre, barras coloridas por estado,
  linha de "hoje", sobreposição em faixas (várias obras do mesmo instalador em
  simultâneo não se escondem umas às outras). Clicar numa barra abre o projeto.
- **Filtros:** PM e estado (multi-seleção, como pedido) + instalador e janela de
  datas. Estado dos filtros no URL (partilhável).
- **Extra barato (proposto, não pedido):** marcar a vermelho quando o mesmo
  instalador tem duas obras sobrepostas.
- Sem biblioteca externa nova: o Gantt é simples (posicionamento por datas) e o
  projeto já evita dependências pesadas.

## 6. Decisões que preciso de ti

| # | Pergunta | Recomendação |
|---|---|---|
| **D1** | Quem manda no estado: o Op_PM ou o ClickUp? | **DECIDIDO: Op_PM.** Campo próprio; o ClickUp fica como espelho até a Fase 8 decidir a sincronização. |
| **D2** | Os 2 projetos que não cabem nos 6 estados ("vendido" e vazio). | **DECIDIDO:** ficam em **On hold pelo cliente**. |
| **D3** | Instalador: entidade própria ou texto livre normalizado? | **Entidade** (`installers`), inicializada com os 9 nomes do export. Evita "GPS Energia"/"gps energia" como instaladores diferentes. |
| **D4** | Datas da obra: derivadas do processo ou introduzidas à mão? | **Campos explícitos**, preenchidos por derivação no arranque e editáveis depois. Preciso de confirmar a fórmula com 2–3 projetos que conheças bem. |
| **D5** | Responsáveis do processo (Duarte, Bárbara, VM, CE). | **PARCIALMENTE DECIDIDO.** Duarte = Duarte Batista, chefe do departamento. Bárbara = Bárbara Ferreira: as etapas em que consta como responsável (registos de licenciamento, projeto eletrotécnico) ficam com ela, e os projetos antigos em que é PM continuam associados a ela. VM = Verde Milenar (subempreiteiro). CE: no legado é o responsável da etapa "Acompanhamento da obra" e "chefe de equipa" aparece nas mesmas etapas — **a confirmar que CE = chefe de equipa**. Falta: que papel tem hoje a Bárbara no Op_PM (ver nota abaixo). |
| **D6** | Transições de estado livres ou por ordem? | **Livres**, com histórico (o ClickUp de hoje é manual). Um aviso, não um bloqueio, se saltar etapas. |
| **D7** | Fornecedores: "contacto telefónico" é campo novo? Vários tipos de material? | **DECIDIDO:** `phone` novo (o `contact` passa a "pessoa de contacto") e **um fornecedor tem vários tipos de material** (tabela de tipos + associação, filtrável). |
| **D8** | Fornecedores: lista inicial? | **DECIDIDO:** lista criada a partir dos sites dos fornecedores que indicaste (16). Fica num ficheiro **local, fora do git**, e é carregada no PR 2. |
| **D9** | Quem pode ver/editar fornecedores? | Ver: quem já vê o inventário/pedidos; editar: `supplier.manage` (já existe). |
| **D10** | Que obras mostra o calendário por omissão? | Janela de −3 a +6 meses, **todos os estados**, com o filtro de estado à mão (212 obras já certificadas encheriam o ecrã). |

## 7. Feature 4 — Lista de fornecedores

**Campos pedidos → onde estão:** Nome (`name`) · Tipos de material (vários:
nova tabela de tipos + associação; o `category` atual fica como legado) ·
Contacto telefónico (**novo** `phone`) · Email (`email`) · Localização
(`address` + `lat/lon` opcionais, que o mapa já usa).

**Desenho**
- Migração: `Supplier.phone`; `contact` fica como pessoa de contacto.
- Permissão nova `supplier.view` (hoje ver fornecedores exige `map.view`, o que
  não faz sentido para uma página própria). `GET /api/suppliers` passa a aceitar
  `q` (nome/material/localização), `category` e `is_active`, com paginação.
- **Página `/suppliers`** no menu: tabela pesquisável e filtrável por tipo,
  ordenação, criar/editar/desativar (nunca apagar — há pedidos de material
  ligados), validação de email e telefone, e ligação ao mapa quando há
  coordenadas.
- Os fornecedores do seed continuam a funcionar sem alterações.
- **Lista inicial (16 fornecedores):** recolhida dos sites públicos e guardada
  num JSON **local fora do repositório** (é informação comercial da Solcor).
  Um comando administrativo carrega-a (idempotente por nome). Nem todos os sites
  expõem contactos: 4 ficaram sem alguns campos e 1 (Mauser) sem nenhum, a
  preencher à mão. Os dados foram lidos automaticamente das páginas e **têm de
  ser confirmados** antes de os usares (telefones, emails e moradas).
- **Vocabulário de tipos** proposto (editável): painéis fotovoltaicos,
  inversores, baterias, estruturas de fixação, carports, material elétrico,
  quadros elétricos, contadores e medição, carregadores VE, monitorização,
  betão e pré-fabricados, cabos e acessórios.

## 8. Ordem de entrega (um PR por linha, CI verde antes de cada merge)

| PR | Conteúdo | Depende de |
|---|---|---|
| **1** | Estados do projeto: coluna, mapeamento inicial, API, histórico, filtro e badge | — |
| **2** | Fornecedores: `phone`, `supplier.view`, listagem com filtros, página | — |
| **3** | Instalador (entidade + ingestão do `subcontractor`) e datas da obra | PR 1 (usa o estado) |
| **4** | Calendário de obras: endpoint, página, filtros PM/estado | PR 1 e 3 |
| **5** | Catálogo real (CLI local) + API + separador "Processo" | — |
| **6** | Migração do progresso legado (`done`) + atraso no painel | PR 5 e D4 |

**Nota sobre a Bárbara (D5):** por defeito, as etapas dela ficam atribuídas à
*pessoa* Bárbara Ferreira (responsável por defeito, editável), e não a um papel
genérico, porque o papel dela mudou. Se preferires um papel dedicado (por
exemplo "Licenciamento e projeto"), diz-mo.

Os PR 1 e 2 são independentes e pequenos; podem ir primeiro e em paralelo. O
PR 6 é o mais arriscado e fica no fim de propósito.

## 9. Verificação (em todos os PR)

- **Backend:** testes de permissões e âmbito (404 fora do âmbito, secções `null`
  sem permissão), migrações para cima e para baixo, limite de queries nas
  listagens, e testes de equivalência do mapeamento legado.
- **Frontend:** Vitest para cada página/filtro; `tsc` e build.
- **Dados reais:** cada PR é ensaiado contra a base local com os 295 projetos
  (`backend/data/real_local.db`, fora do git), com contagens conferidas contra o
  export (ex.: 212/50/17/5/4/5 por estado).
- **Documentação:** uma decisão `D-0xx` por PR e `OPEN_QUESTIONS.md` atualizado
  quando D1–D10 forem respondidas.

## 10. Fora do âmbito (de propósito)

Sincronização com o ClickUp, envio de emails do processo, edição do catálogo de
etapas pela UI, permissões por instalador (subempreiteiros com login próprio) e
cálculo de rotas de instaladores.
