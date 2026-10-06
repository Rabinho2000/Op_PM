# Plano — aprovação de férias, papel de Suporte de Operações e localização das equipas dos instaladores

> **Estado: proposta, por aprovar.** Nada aqui está implementado. Origem: notas de uma
> reunião de operações (três pedidos). Escrito depois de ler o código atual
> (`absence`, `catalog`/`permissions`, `support_delegations`, `installer`/`works_calendar`).
> As decisões em aberto estão na secção 5, cada uma com uma recomendação por omissão.
>
> **Repositório público:** como em D-073, nenhum nome de pessoa nem de instalador entra no
> Git. As pessoas de Suporte e os PMs delegados são **dados** (`support_delegations`);
> o instalador com várias equipas é referido como "instalador VM".

## 0. Pedidos da reunião

1. **Férias com aprovação:** o Chefe de Operações aprova todas as férias; quando um PM
   marca férias, ficam **pendentes** até o Chefe aprovar.
2. **Papel "Suporte de Operações":** ajuda a fazer o projeto; **só tem tarefas nos projetos
   em que o PM é um dos PMs que delega nele** (hoje, dois PMs).
3. **Equipas dos instaladores:** o instalador VM tem várias equipas e é preciso saber **que
   equipa está onde** (e quando).

Ordem proposta: PR A (férias) → PR B (Suporte) → PR C (equipas). A é pequeno e fechado;
B reaproveita `support_delegations` (D-073); C depende de dados reais das equipas.

## 1. O que já existe (e não se refaz)

| Peça | Estado atual | Consequência |
|---|---|---|
| `Absence` (`absences`) | pessoa, datas, tipo (`ferias`/`baixa_medica`/`outro`), nota, estado `aprovada`/`cancelada`. **Criada = aprovada** (sem fluxo). | Falta o estado `pendente`/`rejeitada`, quem decidiu e quando. |
| Permissões de ausência | `absence.view_all`/`manage_all` (Admin, Chefe); `view_own`/`manage_own` (PM, Comercial, Financeiro). | Falta uma permissão de **aprovar**, separada de "gerir". |
| Painel e calendário de férias | Só contam ausências `aprovada` (`dashboard.py`, `Vacations.tsx`). | Uma pendente não conta como ausência — correto, mas tem de ser visível à parte. |
| `SupportDelegation` (`support_delegations`) | PM → pessoa de suporte; etapas com `responsible_rule="support_delegate"` resolvem-se para essa pessoa (D-073). Carregada de ficheiro local. | É **exatamente** a regra "só tem tarefas se o PM for X ou Y". Não se cria outra. |
| Âmbito de projeto | `can_view_project`/`visible_projects_query`: `view_all` ou "os próprios como PM". | Falta um terceiro âmbito: **projetos delegados** (em que sou o suporte do PM). |
| `Installer` / `InstallerTeam` / plano de obra | Obra → instalador + equipa (FK composta) + janela `work_start_date`–`work_end_date` (D-071). | Já responde a "que equipa faz que obra e quando" — **uma equipa por obra, uma janela**. |
| Calendário de obras `/works` | Linhas por instalador → equipa, conflitos de equipa (D-072). | Já mostra "quando"; falta "**onde**" (morada/mapa) e "**hoje/esta semana**". |
| Mapa operacional | Projetos com lat/lon, filtros (D-058…D-067). | Pode ganhar uma camada/filtro por equipa sem backend novo pesado. |

## 2. PR A — Férias com aprovação do Chefe de Operações

**Modelo** (migração nova):
- `absences.status` passa a `pendente | aprovada | rejeitada | cancelada`.
- Colunas novas: `decided_by_person_id` (FK `people`, nulo), `decided_at` (timestamptz, nulo),
  `decision_note` (texto, vazio).
- Dados existentes: ficam `aprovada` (nada muda para trás); `decided_*` a nulo.

**Permissão nova:** `absence.approve` — Chefe de Operações e Administrador.

**Regras** (em `app/services/absences.py`, todas com testes):
- Criar férias para **si próprio** sem `absence.approve` → `pendente`.
- Criar férias por quem tem `absence.approve` (para si ou para outra pessoa) → `aprovada`
  diretamente, com `decided_by = criador` (ver D-A2 para o caso do próprio Chefe).
- `baixa_medica` e `outro`: ver D-A1 (recomendação: não passam por aprovação — são registo,
  não pedido).
- Transições: `pendente → aprovada | rejeitada` (só `absence.approve`; rejeitar exige nota);
  `pendente → cancelada` (o próprio ou quem gere); `aprovada → cancelada` (ver D-A3).
  Qualquer outra transição → 400. `rejeitada`/`cancelada` são finais.
- Datas/tipo continuam não editáveis depois de criada (regra atual de `AbsenceUpdate`):
  mudar datas = cancelar e pedir de novo, que volta a `pendente` (ver D-A3).
- O `PATCH` genérico deixa de aceitar `status`; as transições passam a endpoints explícitos:
  `POST /api/absences/{id}/approve`, `/reject` (`{note}`), `/cancel`. Isto impede que um PM
  se auto-aprove com um `PATCH {status: "aprovada"}` — hoje `update_absence` aceita qualquer
  estado válido de quem tenha `manage_own`.
- Sobreposição: aviso (não bloqueio) se a pessoa já tiver ausência aprovada/pendente que
  intersecta, e se o PM tiver **obras em `preparacao`/`construcao`** nessa janela — é a
  informação que o Chefe precisa para decidir.
- Auditoria: cada transição regista quem/quando (colunas + nota); sem tabela nova.

**API/leitura:** `AbsenceRead` ganha `decided_by_display_name`, `decided_at`, `decision_note`,
`can_approve`, `can_reject`, `can_cancel`. `GET /api/absences?status=pendente` já existe como
filtro. Painel: contador "Férias por aprovar" para quem tem `absence.approve`; as pendentes
**não** contam como ausentes no resumo semanal.

**Interface (`Vacations.tsx`):** separador/filtro "Por aprovar" para o Chefe, com Aprovar /
Rejeitar (nota obrigatória) e o aviso de obras na janela; o PM vê as suas com a etiqueta
"Pendente"/"Rejeitada — motivo". No calendário, pendentes a tracejado (não dependem só da cor).

**Notificação:** sem email nesta fase (o adaptador Graph ainda é fallback local). Só contador
no painel. Ver D-A4.

**Testes:** transições válidas/inválidas por papel; PM não se auto-aprova (nem por `PATCH`);
Chefe cria já aprovada; migração para cima/baixo com dados existentes intactos; painel não
conta pendentes; Vitest dos botões por `can_*`.

## 3. PR B — Papel "Suporte de Operações"

**Papel novo:** `suporte_operacoes` ("Suporte de Operações") em `catalog.py`, chegando à base
por `seed_catalog`/`provision_staging` como os outros.

**Âmbito — "projetos delegados":** um projeto é delegado ao utilizador se existe
`SupportDelegation(pm_person_id = project.pm_person_id, support_person_id = eu)`. Sem PM ou sem
delegação → não é delegado. Mudar o PM de um projeto muda o âmbito automaticamente (a regra é
calculada, não copiada).

- Permissão nova `project.view_delegated`; `visible_projects_query`/`can_view_project` ganham
  este terceiro ramo (subquery sobre `support_delegations`, sem N+1).
- Escrita: nova função `can_edit_delegated(ctx, project)`; aplica-se ao **processo**
  (`workflow.update_progress`) e a tarefas. Ver D-B2 para o alcance exato.

**"Só tem tarefas se…":**
- Processo: as etapas `support_delegate` desses projetos já se resolvem para a pessoa de
  Suporte (D-073). Nada a mudar no cálculo.
- Nova vista **"As minhas etapas"** (`GET /api/me/process-stages`): em bloco, as etapas por
  concluir cujo responsável resolvido sou eu (PM → `pm`; Suporte → `support_delegate` dos
  projetos delegados), com projeto, prazo e estado (`overdue`/`active`/`upcoming`). Serve
  também os PMs. Queries limitadas (catálogo + progresso dos projetos no âmbito).
- `Task`: o Suporte pode criar tarefas nos projetos delegados e editar as que criou/lhe estão
  atribuídas (espelha `task.edit_own`, mas com o âmbito delegado em vez de "sou o PM").

**Permissões por omissão do papel (proposta, D-B1):** `project.view_delegated`,
`workflow.update_progress`, `task.view_own`, `task.edit_own`, `document.view`,
`document.edit`, `project.view_installation_data`, `project.edit_installation_data`,
`project.view_licensing_data`, `project.edit_licensing_data`, `supplier.view`,
`calendar.view`, `absence.view_own`, `absence.manage_own`. **Sem** custos, inventário central,
migração, instaladores nem alteração de estado do projeto.

**Delegações:** continuam dados. Hoje só se carregam por ficheiro local (`load_process
--delegations`). Proposta: página simples em administração (`admin.manage_users`) para ver e
editar PM → Suporte, com histórico. Ver D-B3.

**Testes:** Suporte vê só projetos de PMs que delegam nele (e deixa de ver ao mudar o PM);
404 fora do âmbito; marca subtarefas das etapas permitidas e 403 nas outras; "As minhas
etapas" correta para PM com e sem delegação e para o Suporte; sem N+1.

## 4. PR C — Onde está cada equipa do instalador

**Leitura do pedido:** "saber que equipa deles está onde" = para cada equipa do instalador VM,
em que obra (morada/mapa) está hoje e nas próximas semanas, e quais estão livres.

**Fase C1 — com o modelo atual (sem migração):**
1. **Carregar as equipas reais** do instalador VM (nome, chefe, telefone) com
   `load_installers` — ficheiro local, fora do Git (D-071). Pré-requisito sem código.
2. **Vista "Equipas — hoje / esta semana"** (`GET /api/works/teams?date=…&installer_id=…`):
   por equipa ativa, a(s) obra(s) cuja janela contém o dia/semana, com morada, lat/lon, PM,
   estado, datas estimadas/confirmadas e conflito; equipas **sem obra** listadas como livres.
   Reaproveita `get_works_calendar` (mesmo âmbito de visibilidade e regra de conflito).
3. **Mapa:** filtro/camada "equipa em obra" — pins das obras em curso coloridos/etiquetados
   por equipa, com ligação ao projeto. Não depende só da cor (etiqueta com o nome da equipa).
4. **Calendário `/works`:** atalho "Hoje por equipa" e morada no tooltip das barras.

Limitação honesta: com uma equipa e uma janela por obra, **não** representa uma obra feita por
duas equipas, nem uma equipa que interrompe uma obra para ir a outra. E as datas atuais do
legado são estimadas (D-071): a vista só é fiável depois de os PMs confirmarem equipa e datas
das obras em curso.

**Fase C2 — só se C1 não chegar (D-C1):** tabela `team_assignments` (equipa, projeto,
`start_date`, `end_date`, nota), várias por obra; `projects.installer_team_id`/datas passam a
derivados ou "principal". Conflitos e vista passam a usar as atribuições. É uma mudança de
modelo com migração dos dados de C1 — não se faz sem confirmação.

Fora do âmbito: posição GPS em tempo real das equipas, login para chefes de equipa externos.

**Testes:** vista por dia/semana (limites inclusivos, equipas livres, conflitos, âmbito PM),
sem N+1; Vitest da vista e do filtro do mapa.

## 5. Decisões

### Fechadas (respostas de 2026-09-28)

- **D-A1 — fechada:** baixa médica e "outro" **não** precisam de aprovação (ficam `aprovada`
  ao criar). Só `ferias` passa por aprovação.
- **D-A2 — fechada:** as férias do Chefe de Operações **não precisam de aprovação de
  ninguém** — quem tem `absence.approve` cria-as já `aprovada`.
- **D-B1 — fechada:** o Suporte de Operações vê **só** os projetos dos PMs que delegam nele.
- **D-B2 — fechada:** nesses projetos marca **apenas as etapas que são dele**
  (`responsible_rule = support_delegate`); o resto do processo é só leitura.
- **D-C1 — fechada:** uma obra **pode ter mais do que uma equipa** → a fase **C2
  (`team_assignments`) é necessária** e passa a ser o desenho do PR C (a C1 sozinha não chega).

As restantes seguem a recomendação por omissão abaixo até indicação em contrário.

### Em aberto (recomendação por omissão)

**Férias**
- **D-A1** Baixa médica e "outro" também precisam de aprovação? → *Recomendo: não* (registo,
  não pedido); só `ferias` fica pendente.
- **D-A2** Quem aprova as férias do próprio Chefe de Operações? → *Recomendo: o Administrador;
  se o Chefe as marcar, ficam aprovadas com registo de que foi o próprio.*
- **D-A3** Cancelar ou alterar férias **já aprovadas**: livre ou volta a aprovação? →
  *Recomendo: cancelar é livre (fica registado); novas datas = novo pedido `pendente`.*
- **D-A4** Aviso ao Chefe: só contador no painel, ou também email/Teams? → *Recomendo:
  contador agora; email quando o Graph estiver ligado.*
- **D-A5** "Todas as férias" inclui Comercial e Financeiro, ou só PMs (e Suporte)? →
  *Recomendo: todos os que só têm `manage_own`.*

**Suporte de Operações**
- **D-B1** O Suporte vê **só** os projetos delegados, ou vê todos (leitura) e só escreve nos
  delegados? → *Recomendo: só os delegados* (mais simples e coerente com "só tem tarefas se…").
- **D-B2** Nos projetos delegados, o Suporte marca **só as etapas `support_delegate`** ou todo
  o processo? → *Recomendo: só as suas etapas*; o resto é do PM.
- **D-B3** Quem gere as delegações PM → Suporte? → *Recomendo: Administrador e Chefe, numa
  página de administração, com histórico.*
- **D-B4** Pode haver mais de uma pessoa de Suporte, ou um PM delegar em duas? → hoje
  `pm_person_id` é único (um Suporte por PM); *recomendo manter.*

**Equipas**
- **D-C1** Uma obra pode ter **mais de uma equipa**, ou uma equipa sair a meio de uma obra? Se
  sim com frequência → C2; se raro → C1 chega.
- **D-C2** Quem mantém a informação de equipa/datas: o PM no plano de obra (como hoje) ou o
  instalador envia um planeamento semanal que alguém carrega?
- **D-C3** "Onde" = morada/mapa da obra chega, ou é preciso saber também quando a equipa está
  em armazém/deslocação/livre?

## 6. Critérios de aceitação (resumo)

- PR A: um PM marca férias → `pendente`; não conta como ausente; o Chefe aprova/rejeita com
  nota; o PM não se consegue auto-aprovar por nenhum endpoint; dados antigos intactos.
- PR B: uma pessoa com `suporte_operacoes` vê e trabalha só nos projetos de PMs que delegam
  nela; "As minhas etapas" lista o que lhe cabe; mudar o PM muda o âmbito sem intervenção.
- PR C1: para uma data, cada equipa do instalador VM aparece com a obra/morada onde está (ou
  "livre"), coerente com o calendário de obras e respeitando o âmbito do utilizador.

Cada PR: testes de backend e Vitest novos, `tsc` e build, migração para cima e para baixo,
`scripts/check_no_personal_names.py` antes do PR, e uma entrada `D-0xx` em `docs/DECISIONS.md`.
