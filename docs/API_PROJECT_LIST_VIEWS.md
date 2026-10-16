# API — preferências e vistas pessoais da lista de Projetos

## Âmbito

Estes endpoints guardam apenas o estado da apresentação da lista de Projetos
para a conta autenticada. Não alteram `projects`, não alteram permissões e não
substituem o endpoint scoped `GET /api/projects`. O `user_id` vem sempre da
identidade autenticada; nunca é aceite no body.

Um colaborador externo com apenas `project.view_assigned_installer` não pode
usar esta superfície. Uma conta com um papel adicional de âmbito amplo mantém a
semântica aditiva existente.

## Configuração

A configuração é completa e tem estes campos:

```json
{
  "columns": ["project", "pm", "lifecycle", "progress", "next_task", "overdue", "warnings"],
  "sort_by": "name",
  "sort_direction": "asc",
  "filters": {
    "search": "",
    "status": "",
    "lifecycle": ["on_hold_cliente", "preparacao", "construcao", "construido"],
    "pm": "",
    "active": "active",
    "startFrom": "",
    "startTo": ""
  }
}
```

- Colunas permitidas, nessa ordem de catálogo: `project`, `pm`, `lifecycle`,
  `progress`, `next_task`, `overdue`, `warnings`, `installer`, `start_date`,
  `power_kwp`.
- `project` é obrigatória e sempre a primeira. Não há valores repetidos nem
  campos extra.
- `sort_by` é `name`, `start_date`, `power_kwp` ou `created_at`; a direção é
  `asc` ou `desc`.
- `status` é vazio, `nao_iniciado`, `em_curso` ou `concluido`.
- `lifecycle` aceita códigos do catálogo do backend, sem repetições; `[]`
  significa todos.
- `active` é `active`, `inactive` ou `all`.
- `pm` é vazio ou um UUID de `Person`. Ao guardar, só são aceites PMs que
  pertencem a projetos visíveis para a conta (ou a própria pessoa PM dentro do
  seu âmbito). Ao ler, um PM que entretanto saiu do âmbito é devolvido como
  `""`; essa redação atua numa cópia e não altera o JSON persistido.
- `search` tem no máximo 200 caracteres; `columns` tem no máximo 10 itens e
  `lifecycle` no máximo 6.
- `startFrom`/`startTo` são vazios ou datas ISO `YYYY-MM-DD`, com intervalo
  crescente.
- Tipos estritos, `null`, UUIDs/datas inválidos, desconhecidos e campos extra
  dão `422`; a configuração anterior não é alterada.

## Preferência de abertura

### `GET /api/me/project-list-preferences`

Devolve `200` com `{ "config": Config }`. Quando ainda não há linha, devolve
os defaults acima sem criar uma linha na base de dados.

### `PUT /api/me/project-list-preferences`

Body obrigatório: `{ "config": Config }`.

Devolve `200` com a configuração guardada. É um upsert por conta; cada pedido
substitui integralmente a configuração anterior.

## Vistas guardadas

As vistas são linhas em `project_list_views`. O DELETE é lógico: marca
`is_active=false`, não apaga fisicamente a linha e não altera projetos. Nomes
são `trim`, têm 1–120 caracteres e são únicos entre vistas ativas da mesma
conta.

### `GET /api/me/project-list-views`

Devolve `200` com uma lista ordenada deterministicamente por nome (`id` como
desempate). Só inclui vistas ativas. Cada item é:

```json
{
  "id": "uuid",
  "name": "Vista operacional",
  "config": {
    "columns": ["project", "pm", "lifecycle", "progress", "next_task", "overdue", "warnings"],
    "sort_by": "name",
    "sort_direction": "asc",
    "filters": {
      "search": "",
      "status": "",
      "lifecycle": ["on_hold_cliente", "preparacao", "construcao", "construido"],
      "pm": "",
      "active": "active",
      "startFrom": "",
      "startTo": ""
    }
  },
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

### `POST /api/me/project-list-views`

Body: `{ "name": string, "config": Config }`.

Devolve `201` com o item criado. Nome ativo duplicado dá `409`; payload
inválido dá `422`.

### `PATCH /api/me/project-list-views/{id}`

Body com `name` e/ou `config`. Quando `config` está presente, substitui a
configuração completa; não é um merge parcial. A resposta é `200` com o item
atualizado. Vista inexistente, inativa ou pertencente a outra conta dá `404`
indistinguível.

### `DELETE /api/me/project-list-views/{id}`

Devolve `204` sem body. Vista inexistente, inativa ou pertencente a outra conta
dá `404`.

## Persistência e migração

As tabelas são próprias e separadas das tabelas de Works:

- `project_list_preferences`: uma configuração por `User`;
- `project_list_views`: vistas pessoais, `is_active` e índice de unicidade
  parcial por `(user_id, name)` para linhas ativas.

A migração `e2f4a6c8b0d1` sucede `d9e1f3a5b7c2`; o downgrade remove apenas estas
duas tabelas e o índice criado nesta fase.
