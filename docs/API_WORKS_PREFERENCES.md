# API — preferências do Calendário de obras

Contrato do backend para guardar, por utilizador autenticado, a escala e os
filtros da vista do Calendário de obras. A janela temporal (`from`/`to`) não é
persistida: continua a ser derivada e gerida pelo URL no cliente; um `from`
explícito no URL tem precedência.

## Acesso

`GET` e `PATCH` exigem utilizador autenticado e o mesmo âmbito de consulta que
`GET /api/works/calendar` (a permissão efetiva atual é `can_view_installers`,
baseada em `project.view_all` ou `project.view_own`). Não existe `user_id` no
URL nem no body: a conta autenticada é sempre a proprietária. Sem sessão →
`401`; sessão sem acesso ao Calendário de obras → `403`.

## Endpoints

### `GET /api/me/works-preferences`

Devolve os valores guardados para a conta. Se ainda não existir linha,
devolve os defaults sem criar uma linha:

```json
{
  "zoom": "month_days",
  "lifecycle_status": [],
  "pm_person_id": null,
  "installer_id": null,
  "team_id": null,
  "show_idle": false
}
```

Um erro de esquema/ligação da BD não é convertido em defaults: a resposta é
`503` com uma mensagem genérica.

### `PATCH /api/me/works-preferences`

Todos os campos são opcionais. Um campo omitido preserva o valor atual. `null`
é permitido apenas para `pm_person_id`, `installer_id` e `team_id`, limpando o
filtro correspondente. A validação de todo o estado final ocorre antes de
qualquer alteração; mudanças incompatíveis entre instalador/equipa são
rejeitadas atomicamente.

Campos:

| Campo | Tipo | Regra |
|---|---|---|
| `zoom` | `weeks \| months \| quarters \| month_days` | obrigatório no estado guardado; `null` inválido |
| `lifecycle_status` | `string[]` | códigos do catálogo de ciclo de vida; `[]` significa todos; duplicados são deduplicados pela ordem de chegada; `null` inválido |
| `pm_person_id` | UUID ou `null` | pessoa ativa e válida no âmbito do utilizador |
| `installer_id` | UUID ou `null` | instalador ativo existente |
| `team_id` | UUID ou `null` | equipa ativa existente; quando definido, `installer_id` também tem de estar definido e a equipa tem de lhe pertencer |
| `show_idle` | booleano estrito | nunca `null` |

Campos desconhecidos são recusados (`422`). UUIDs inexistentes, inativos ou
fora do âmbito não são distinguidos na mensagem de validação, para não
revelar a existência de referências não visíveis.

Exemplo:

```json
{
  "zoom": "weeks",
  "lifecycle_status": ["construcao", "preparacao"],
  "pm_person_id": "00000000-0000-0000-0000-000000000000",
  "installer_id": null,
  "team_id": null,
  "show_idle": true
}
```

A resposta `200` tem o mesmo DTO completo do `GET`.

## Persistência e migração

A tabela `works_calendar_preferences` tem uma linha por `users.id`, com FK
`ON DELETE CASCADE`, e colunas simples para escala, filtros JSON, IDs
opcionais e `show_idle`. A migração é posterior a
`f5a7c9d1e3b2` (preferências do Planeamento) e o downgrade remove apenas a
sua própria tabela. A preferência do Planeamento (`planning_preferences`) não é
lida nem escrita por este recurso.
