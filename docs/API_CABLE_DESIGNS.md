# API de dimensionamento de cabos

O módulo guarda estudos AC ligados a um projeto. O motor de cálculo envia apenas
JSON de entrada/resultado; preços e catálogos comerciais pertencem a uma BD
privada de uma fase posterior.

## Âmbito e permissões

- `cable_design.view` permite ler estudos dentro de `can_view_project`.
- `cable_design.edit` permite criar, guardar, aprovar, criar revisões e
  desativar dentro de `can_edit_project`.
- `administrador`, `chefe_operacoes` e `project_manager` recebem ambas as
  capabilities; `suporte_operacoes` recebe apenas `view`. Comercial,
  financeiro e colaborador de instalador não recebem acesso.
- Capability em falta devolve `403` antes de consultar o projeto. Projeto ou
  estudo inexistente/fora do âmbito devolve `404` indistinguível.

## Endpoints

### `GET /api/projects/{project_id}/cable-designs`

Lista estudos ativos do projeto:

```json
[
  {
    "id": "uuid",
    "project_id": "uuid",
    "title": "Estudo A",
    "status": "rascunho",
    "current_revision": "A",
    "version": 1,
    "updated_at": "2026-01-01T00:00:00",
    "unresolved_circuits": 0
  }
]
```

### `POST /api/projects/{project_id}/cable-designs`

Cria a revisão `A` em rascunho. `input_json` é opcional; quando omitido usa
`{"format": 1}`. Se for enviado, tem de ser um objeto JSON com `format: 1`.
`engine_version` é obrigatório.

### `GET /api/cable-designs/{id}`

Devolve o estudo e a revisão corrente completa. `input_json` e `result_json`
são objetos JSON, não texto serializado.

### `PUT /api/cable-designs/{id}/revisions/current`

Guarda a revisão corrente enquanto ela não está aprovada:

```json
{
  "expected_version": 1,
  "title": "Estudo A",
  "input": {"format": 1},
  "result": {"format": 1, "circuits": []},
  "engine_version": "engine-1"
}
```

A versão é otimista: uma versão obsoleta dá `409`. Uma revisão aprovada dá
`423`. O hash é SHA-256 de `canonical(input_json) + canonical(result_json)`;
`canonical` usa UTF-8, chaves ordenadas e separadores compactos. Cada objeto tem
limite de 2 MiB. `unresolved_circuits` conta entradas de `result.circuits` com
`review == true`; resultados sem essa lista são aceites com contagem zero.

### `POST /api/cable-designs/{id}/approve`

Recebe `{ "expected_version": N }`. Rejeita com `409` quando há circuitos a
rever; caso contrário marca a revisão como `aprovada`, o estudo como
`aprovado`, e regista ator/data. A revisão aprovada nunca é atualizada.

### `POST /api/cable-designs/{id}/new-revision`

Recebe `{ "expected_version": N }`. Só funciona num estudo aprovado. Cria a
revisão seguinte (`A` → `B` → …), copiando input/resultado/hash para um novo
rascunho e incrementando a versão do estudo.

### `GET /api/cable-designs/{id}/revisions`

Lista todas as revisões, incluindo conteúdo parseado. As revisões aprovadas são
append-only.

### `GET /api/cable-designs/{id}/history`

Lista o histórico append-only (`created`, `saved`, `submitted`, `approved`,
`new_revision`, `deactivated`). `old_value`/`new_value` contêm apenas estado
curto (versão, título, estado, revisão, hash e contagem), nunca input/resultado.

### `DELETE /api/cable-designs/{id}?expected_version=N`

Desativa logicamente o estudo (`is_active=false`) e mantém revisões/histórico.
A remoção exige capability e âmbito de edição; versão obsoleta dá `409`.

Corpos inválidos, objetos não JSON, `null`, arrays, escalares, campos extra e
strings de controlo devolvem `422` (ou `413` quando o limite é aplicado no
serviço), nunca um erro interno.
