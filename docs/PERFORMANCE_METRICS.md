# Metas e indicadores

> Ver `docs/PLAN_OPERATIONS_MVP.md` secção 8 para o desenho completo.

## Uma única página

O menu tem só **"Metas e indicadores"** (`/performance`) — nunca "Metas" e
"Dashboards" separados, por pedido explícito. A homepage (`/`) continua a
ser o painel operacional do dia a dia (Fase 1.5); esta página é sobre
objetivos e progresso ao longo do tempo.

## Regras de conclusão: metas, indicadores históricos e estado derivado

Há três regras complementares, consoante o indicador:

- **Metas de `installations`, `projects_completed`, `kwp`,
  `power_installed` e `power_delivered`:** o realizado é a união deduplicada
  por `Project.id` de (a) projetos com uma `Task` de comissionamento (`task_type
  == "comissionamento"`, `status == "done"`) cujo `completed_at` está dentro
  do período selecionado e (b) todos os projetos cujo `lifecycle_status` atual
  é `entregue_cliente` ou `certificado_final`. A fonte (b) conta em qualquer
  período, mesmo quando não existe tarefa datada no período, e é filtrada pelo
  `Project.pm_person_id` quando a meta é de um PM.
- **Indicadores anuais (`yearly`) de instalações e kWp:** uma instalação só
  conta como concluída quando existe uma `Task` de comissionamento concluída,
  na data em que `completed_at` ficou preenchido. `lifecycle_status` não cria
  nem substitui um evento histórico nesta série.
- **`projects_certified`:** conta exclusivamente
  `ProjectLicensingData.certificate_date` dentro do período; o estado final do
  ciclo de vida não substitui essa data.

A inclusão não temporal dos estados finais nas metas é deliberada: a base não
possui datas de conclusão fiáveis para todos esses projetos. Não se inventa
uma data nem se atribui o projeto a um período histórico; apenas se reflete o
estado atual nas metas. A deduplicação evita contar duas vezes um projeto que
tenha simultaneamente comissionamento datado no período e estado final.

- **Estado derivado do portefólio:** `compute_project_task_summary` também
  classifica como `concluido` um projeto cujo `lifecycle_status` seja
  `entregue_cliente` ou `certificado_final`, mesmo que a checklist de tarefas
  esteja incompleta, conforme D-085. Esta regra é independente das métricas
  acima.

A regra dos indicadores históricos é reaproveitada tal e qual do dashboard
(`app/services/dashboard.py`) — nunca uma segunda definição divergente. Se o
negócio confirmar uma fonte mais adequada (ex. `ProjectLicensingData.certificate_date`),
rever aqui e em `app/services/performance.py:_realized_value` ao mesmo tempo,
nunca só num dos dois sítios.

## Métricas suportadas (`GoalPeriod.metric`)

| Código | Cálculo |
|---|---|
| `installations` / `projects_completed` | Contagem da união de projetos com comissionamento concluído no período e projetos atualmente em estado final (`entregue_cliente`/`certificado_final`), deduplicada por projeto |
| `kwp` / `power_installed` / `power_delivered` | Soma de `Project.power_kwp` dessa mesma união de projetos (as três métricas produzem hoje o mesmo valor — ver nota) |
| `projects_certified` | Contagem de `ProjectLicensingData.certificate_date` dentro do período |

**Nota sobre métricas equivalentes:** o pedido original lista
`installations`, `projects_completed`, `kwp`, `power_installed` e
`power_delivered` como conceitos distintos, mas o modelo de dados atual
não distingue "potência instalada" de "potência entregue" (produção
real), nem "instalação concluída" de "obra concluída". Em vez de inventar
uma distinção sem dados para a sustentar, todas usam a mesma fonte de
verdade — documentado aqui explicitamente e em
`docs/OPEN_QUESTIONS.md`, revisível quando o negócio confirmar a
distinção real (ex. produção via `ProjectLicensingData.annual_production_kwh`).

## Progresso de uma meta (`GET /api/performance/goals`, `/summary`)

Tudo calculado no servidor (nunca no frontend a partir de listas
completas — D-041):

```
percent        = realizado / objetivo × 100
falta          = max(0, objetivo − realizado)
ritmo_esperado = objetivo × (dias_decorridos / dias_totais_do_periodo)
projeção       = realizado / dias_decorridos × dias_totais_do_periodo
```

`pace_status`: `ahead` (acima do ritmo esperado), `on_track` (exatamente
no ritmo), `behind` (abaixo), `no_target` (objetivo ≤ 0). Ritmo/projeção
são quantizados a 3 casas decimais — divisão de `Decimal` sem isto produz
dízimas com dezenas de casas, inúteis para apresentação.

## Indicadores históricos (`GET /api/performance/summary`)

- `portfolio` — projetos por estado (`nao_iniciado`/`em_curso`/`concluido`,
  reaproveitando `compute_project_task_summary` — nunca uma segunda
  definição de estado), mais kWp por estado, certificadas, e "entregues
  pendentes de certificação" (concluído mas sem `certificate_date`).
- `yearly` — instalações e kWp concluídos, últimos 5 anos.

## UI (`frontend/src/pages/Performance.tsx`)

- Filtros: ano, tipo de período (ano inteiro/semestre/trimestre/mês) com o
  seletor de semestre/trimestre/mês correspondente a aparecer só quando
  relevante, e PM (ou "todos os PM e empresa") — todos enviados ao
  servidor (`GET /api/performance/summary`), nunca filtrados no cliente a
  partir de uma lista completa.
- "Nova meta" e "Editar" (por meta) atrás de `performance.manage_goals` —
  editar altera `target_value`/`notes`; o progresso nunca é editável
  diretamente, é sempre recalculado a partir dos dados reais.

## Permissões

`performance.view_all` (Chefe/Admin/Comercial/Financeiro — leitura
apenas para os dois últimos), `performance.view_own` (PM — só as suas
metas + as da empresa), `performance.manage_goals` (Chefe/Admin, CRUD de
`GoalPeriod`).
