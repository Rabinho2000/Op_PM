# API Banco de Horas

Estado: backend local do snapshot `Op_PM-time-bank-20261015`; sem publicação,
commit, deploy ou escrita em dados reais.

Base path: `/api/time-bank`. Todos os endpoints exigem autenticação. O backend
usa capabilities calculadas a partir das roles efetivas; não aceita role/person
escolhida pelo cliente.

## Capabilities e âmbito

- `time_bank.view_own`: lê apenas o `Person` ligado ao utilizador autenticado.
- `time_bank.view_all`: lê pessoas, lançamentos, ajustes e saldos de todas as
  pessoas.
- `time_bank.manage_all`: cria, anula, ajusta e importa qualquer pessoa; os
  lotes de importação também exigem esta capability.
- A migração `c8f0a2b4d6e1` concede `view_all/manage_all` a
  `administrador`/`chefe_operacoes` (e ao alias `admin` se já existir) e
  `view_own` às restantes roles existentes. O provisionamento é registado em
  `time_bank_permission_provisioning`, não altera `user_roles` e o downgrade
  remove apenas linhas que a própria migração criou.

## DTOs de leitura

### `GET /people`

Resposta: `[{"id": UUID, "display_name": string, "is_active": boolean}]`.
Readers recebem apenas a própria pessoa; managers recebem o catálogo sem
emails.

### `GET /entries`

Query: `person_id?`, `from_date?`, `to_date?`, `limit` (1–100, default 100),
`offset` (default 0). Datas são inclusivas.

```json
{
  "items": [{
    "id": "UUID", "person_id": "UUID", "work_date": "YYYY-MM-DD",
    "start_minute": 540, "end_minute": 1110, "lunch_taken": true,
    "balance_seconds": 0, "calculated_seconds": 0,
    "calculation_mode": "standard|saturday|manual|imported",
    "reason": null, "needs_review": false, "review_flags": {},
    "provenance": {}, "source_key": null,
    "created_by_user_id": "UUID", "occurred_at": "datetime",
    "reversal_of_id": null
  }],
  "total": 0
}
```

### `GET /adjustments`

Tem os mesmos filtros/envelope de entries. Cada item contém
`effective_date`, `delta_seconds`, `kind` (`opening`, `correction` ou
`consumption`), `reason`, `provenance`, `source_key`, autor, data de ocorrência
e `reversal_of_id`.

### `GET /summary`

Query: `person_id?`, `year` (default 2026), `month?` (1–12). Resposta:

```json
{
  "people": [{
    "person_id": "UUID", "display_name": "string",
    "opening_seconds": 0, "credited_seconds": 0,
    "debited_seconds": 0, "balance_seconds": 0,
    "period_seconds": 0, "needs_review_count": 0,
    "warnings": [{"code": "daily_threshold", "message": "string"}]
  }]
}
```

O saldo soma o ledger até ao fim do período selecionado. `credited_seconds` e
`debited_seconds` excluem o par original+compensação para não contar uma
anulação como movimento novo; o saldo continua a somar todas as linhas. Os
avisos são não bloqueantes: 2 h/dia, 4 h/semana ISO, 175 h positivas no ano,
8 h de saldo acumulado e `needs_review`.

## Escrita e ledger

### `POST /entries`

Body estrito, sem campos desconhecidos:

```json
{
  "person_id": "UUID", "work_date": "YYYY-MM-DD",
  "start_minute": 540, "end_minute": 1110, "lunch_taken": true,
  "calculation_mode": "standard|saturday|manual",
  "manual_balance_seconds": null, "reason": null
}
```

Inteiros são segundos/minutos; booleanos não são aceites como inteiros.
Segunda–quinta usam `end-start-570 + (lunch_taken ? 0 : 60)` minutos; sexta usa
`end-start-300 + (lunch_taken ? 0 : 60)`; sábado usa tempo líquido × 1,5.
Domingo exige `manual`, com `manual_balance_seconds` e `reason`. Resultados
negativos são válidos. Horários são locais/date-only; saída anterior ou igual à
entrada é recusada.

### `POST /entries/{id}/reverse`

Body `{ "reason": "..." }`. Cria exatamente uma linha compensatória com sinal
oposto; o original não é editado. Reanular uma compensação ou uma linha já
compensada devolve `409`.

### `POST /adjustments`

Body estrito: `person_id`, `effective_date`, `delta_seconds` assinado,
`kind=correction|consumption` e `reason`. `consumption` tem de ser negativo;
`opening` só é criado pelo importador.

### `POST /adjustments/{id}/reverse`

Cria uma compensação append-only de delta oposto; mantém o ajuste original.

As mutações bloqueiam a pessoa canónica antes de ler/criar linhas; em
PostgreSQL usam `FOR UPDATE`, e em SQLite usam a transação de escrita
`BEGIN IMMEDIATE`/refresh. Auditoria (`time_bank_audit`) é gravada na mesma
transação. O serviço não faz `commit`/`rollback` da sessão do chamador.

## XLSX: preview → resolução → apply

### `POST /imports/preview`

Multipart `file`, máximo 5 MiB no `read`. O ZIP é validado antes do
`openpyxl`: limites de membros/tamanho descomprimido, sem relações externas,
sem avaliação de fórmulas. O parser reconhece apenas fórmulas seguras observadas
(`IF`, `WEEKDAY`, `SUM`, `SUMIF` e referências de tabela); usa caches numéricos,
preserva o valor histórico e marca diferenças/regras manuais em `needs_review`.
Cache ausente só é recalculado quando a fórmula standard é segura; fórmulas
indeterminadas sem cache bloqueiam o apply. O workbook, XML bruto, data URLs e
base64 nunca são persistidos.

Resposta `ImportRead`:

```json
{
  "id": "UUID", "status": "pending|applied", "sha256": "hex",
  "source_year": 2026,
  "counts": {"entries": 0, "openings": 0, "needs_review": 0,
              "source_rows": 0, "quarantined": 0},
  "people": [{
    "source_label": "string", "person_id": null,
    "candidates": [{"id": "UUID", "display_name": "string"}]
  }],
  "issues": [{"code": "string", "message": "string", "blocking": false,
               "sheet": null, "row": null}],
  "applied_counts": null
}
```

`source_label` é devolvido apenas na API protegida e guardado na staging
privada; não pertence a fixtures/documentação pública. Um nome próprio isolado
não é escolhido automaticamente. O candidato exacto, quando existe, continua
a exigir resolução humana explícita. `source_rows` reconcilia todas as linhas
com identidade de origem; `quarantined` conta linhas preservadas sem criar uma
data fictícia. Uma linha undated com zero fica em quarentena e pode prosseguir
sem entrada no ledger; uma linha undated não zero é bloqueante.

Comentários de células e valores fora das colunas A:G são preservados como
notas sanitizadas no staging/ledger. URLs, tokens, payloads `data:` e valores
com forma de segredo são substituídos por marcadores antes de persistir; o
texto bruto nunca entra no payload privado.

### `POST /imports/{id}/resolve`

Body `{ "person_mapping": {"source_label": "person-uuid"} }`. Só aceita
rótulos do lote e referências a pessoas existentes. O lote aplicado é imutável.
Todas as pessoas do lote têm de estar resolvidas antes do apply.

### `POST /imports/{id}/apply`

Sem body. Recusa `409` se houver anomalias bloqueantes ou pessoas por resolver.
Após validação, insere entries/openings e auditoria na mesma transação. A chave
`sha256 + parser_version` identifica o lote; `source_key` identifica cada linha.
Repetir preview devolve o mesmo lote; repetir apply de lote aplicado devolve o
mesmo resultado sem duplicar linhas.

As respostas de mutação são materializadas depois do `flush` e antes do
`commit`; não fazem `refresh`/SELECT depois de um commit bem-sucedido. Falhas
SQLAlchemy de flush, serviço ou leitura devolvem `503` sanitizado e só há
rollback enquanto o commit ainda não teve sucesso. `409` de integridade fica
reservado às colisões conhecidas de source/reversal/idempotência.

## Erros

- `401`: não autenticado;
- `403`: capability/âmbito insuficiente;
- `404`: pessoa ou lote/linha inexistente;
- `409`: lote aplicado/remapeamento, chave de origem divergente, compensação
  duplicada ou anomalia de apply;
- `422`: body/tipos/regras de cálculo inválidos;
- `503`: falha de armazenamento/SQLAlchemy sanitizada; não expõe detalhes de
  infraestrutura.

## Limitações deste snapshot

- Não há frontend neste pacote backend.
- A API não cria `Person`, `User`, `Role` ou `UserRole` durante importação.
- A validação real do XLSX foi feita em cópia/processamento local privado; o
  ficheiro real e nomes de origem não entram no repositório.
- O parser preserva anomalias para revisão, mas não oferece ainda uma edição
  de valores de origem: a fonte deve ser corrigida quando a anomalia é
  bloqueante.
- Produção, dados reais e PostgreSQL não foram alterados neste snapshot.
