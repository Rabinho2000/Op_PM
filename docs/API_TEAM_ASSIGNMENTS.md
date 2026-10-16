# Contrato API — afectação de equipas às obras

Âmbito desta fatia: backend, API, migração e testes. A implementação frontend e a
publicação/produção ficam fora deste contrato.

Todas as datas são `YYYY-MM-DD` e as janelas são inclusivas. Os identificadores
são UUID. O backend continua a aplicar a autenticação e o âmbito de projetos já
existentes; não foi criado nenhum papel novo.

## Afectações de uma obra

### Endpoints

- `GET /api/projects/{project_id}/team-assignments`
- `POST /api/projects/{project_id}/team-assignments`
- `PATCH /api/projects/{project_id}/team-assignments/{assignment_id}`
- `DELETE /api/projects/{project_id}/team-assignments/{assignment_id}`

Uma resposta de afectação tem a forma:

```json
{
  "id": "uuid",
  "project_id": "uuid",
  "installer_id": "uuid",
  "team_id": "uuid",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "note": "texto",
  "created_by_person_id": "uuid ou null",
  "team_name": "texto ou null",
  "installer_name": "texto ou null",
  "team_leader_name": "texto ou null",
  "team_leader_phone": "texto ou null",
  "warning": "texto ou null"
}
```

`warning` é apenas um diagnóstico operacional. Fica preenchido quando a janela
da afectação sai da janela legada da obra ou quando esta ainda não está
preenchida; a afectação não é rejeitada por esse motivo.

### Criação

`POST` recebe:

```json
{
  "team_id": "uuid",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "note": "texto opcional, no máximo 4000 caracteres"
}
```

Responde `201` com a afectação. Requer a capacidade existente de planear a obra
(`project.plan_work`) e o projeto tem de estar no âmbito do utilizador. Uma obra
fora do âmbito responde `404`; uma operação sem capacidade responde `403`.

Regras de negócio que respondem `400`:

- o fim não pode ser anterior ao início;
- a equipa tem de existir e pertencer ao instalador da obra;
- a equipa tem de estar activa numa nova afectação;
- a mesma equipa não pode ter duas janelas sobrepostas na mesma obra.

A primeira afectação de um projeto sem equipa principal preenche
`projects.installer_team_id` para compatibilidade. As datas legadas da obra não
são alteradas.

### Leitura

`GET` requer apenas que o projeto seja visível (`project.view`). Responde `200`
com uma lista ordenada por `start_date` e `created_at`. Fora do âmbito responde
`404`, sem revelar a existência do projeto.

### Alteração

`PATCH` aceita qualquer subconjunto não vazio de:

```json
{
  "team_id": "uuid",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "note": "texto ou null"
}
```

Os campos `team_id`, `start_date` e `end_date` não aceitam `null`; um `PATCH`
com esses valores, com corpo vazio ou com campos extra responde `422`. Enviar
`note: null` limpa a nota e grava `""`. A validação de sobreposição e de
pertença/actividade da equipa aplica-se novamente; ao manter uma afectação
histórica ligada a uma equipa que entretanto ficou inactiva, essa equipa pode
ser mantida, mas não pode ser escolhida como nova equipa.

Responde `200` com a afectação actualizada. A autorização e os códigos de erro
de âmbito são os mesmos da criação. Cada campo alterado gera histórico
append-only em `project_history`.

### Remoção

`DELETE` requer `project.plan_work` e responde `204` sem corpo. A remoção é
explícita e auditada. Se a afectação removida era a equipa principal, a
compatibilidade passa para a afectação restante mais antiga, ou fica nula se
não restar nenhuma. Enquanto existirem afectações, o endpoint legado
`PATCH /api/projects/{project_id}/work-plan` não permite mudar/remover o
instalador nem trocar a equipa principal; primeiro é necessário alterar/remover
as afectações no recurso próprio.

## Calendário de obras

`GET /api/works/calendar?from=YYYY-MM-DD&to=YYYY-MM-DD` mantém os filtros
existentes (`pm_person_id`, `lifecycle_status`, `installer_id`, `team_id`) e a
autorização existente do calendário. Em cada item de `works` mantém todos os
campos anteriores e acrescenta:

- `assignment_id` — UUID da afectação, ou `null`;
- `assignment_start_date` e `assignment_end_date`;
- `assignment_start` e `assignment_end` — aliases equivalentes;
- `team_id`, `team_name` e `team_leader_name`.

Uma obra com afectações produz uma linha por afectação que intersecte a janela
pedida. Nessa linha, `work_start_date`/`work_end_date` são as datas da
afectação. Uma obra antiga sem afectações, mas com instalador e datas legadas,
produz uma linha de compatibilidade sem equipa (`assignment_id` e campos de
team nulos), usando a janela da obra.

`conflict` é calculado antes dos filtros da resposta, mas apenas sobre projetos
visíveis ao utilizador: duas afectações da mesma equipa, em obras diferentes,
com sobreposição inclusiva, quando ambas as obras estão em `preparacao` ou
`construcao`. Duas equipas da mesma obra não entram em conflito. Uma linha fora
da janela pedida não é devolvida nem participa nesse cálculo.

## Vista operacional de equipas

`GET /api/works/teams?date=YYYY-MM-DD&days=N&installer_id=uuid`

- `date` é opcional e, por omissão, é a data actual do servidor;
- `days` é inclusivo e aceita `1` a `62`;
- `installer_id` é opcional e limita o catálogo devolvido.

A rota usa a autorização existente para ver o catálogo/calendário de
instaladores. Responde `403` quando essa autorização falta e `422` quando um
parâmetro não respeita o formato/limite.

Resposta:

```json
{
  "date": "YYYY-MM-DD",
  "days": 3,
  "installers": [
    {
      "id": "uuid",
      "name": "texto",
      "teams": [
        {
          "id": "uuid",
          "installer_id": "uuid",
          "name": "texto",
          "status": "livre | ocupada | ocupada_noutra_obra",
          "free": false,
          "assignments": [
            {
              "id": "uuid",
              "project_id": "uuid",
              "project_name": "texto",
              "address": "texto ou null",
              "lat": 0.0,
              "lon": 0.0,
              "pm_person_id": "uuid ou null",
              "pm_display_name": "texto ou null",
              "lifecycle_status": "texto ou null",
              "start_date": "YYYY-MM-DD",
              "end_date": "YYYY-MM-DD",
              "note": "texto",
              "conflict": false
            }
          ]
        }
      ]
    }
  ]
}
```

Só são listados instaladores/equipas activos. A ocupação considera atribuições
que intersectem o período em projetos activos com estado `preparacao`,
`construcao` ou `null`; `on_hold` e estados finais não ocupam. A ocupação é
calculada também para projetos fora do âmbito do utilizador, mas nesses casos
não é devolvida qualquer identidade da obra: a equipa fica com
`status: "ocupada_noutra_obra"`, `free: false` e `assignments: []`. Isto evita
que uma equipa indisponível apareça como livre sem revelar dados de outro
projeto.

Os conflitos da lista mantêm a regra do calendário e só usam
`preparacao`/`construcao`; um projeto com estado `null` ocupa a equipa, mas não
cria por si só uma marca de conflito.

## Migração e compatibilidade

A revisão `e8b2c4d6f0a1` é encadeada sobre a revisão de fornecedores
`d7a2c5e9b3f1` (`down_revision` e docstring `Revises`), formando um único head.

No `upgrade`, a tabela `project_team_assignments` é criada com a relação
composta equipa/instalador, datas não nulas, `end_date >= start_date`, nota e
autor opcional. Para cada projeto legado que já tenha instalador, equipa e as
duas datas, é criada uma afectação equivalente, sem apagar nem alterar os
campos legados. Uma base vazia é um caso válido. O `downgrade` remove apenas a
tabela criada por esta revisão; os campos legados permanecem intactos.

A próxima fatia pode consumir este contrato para a UI de detalhe, calendário e
vista de equipas. Esta fatia não inclui componentes frontend, build, deploy,
produção ou dados reais.
