# API e operação — preços de materiais

A BD de preços é privada e separada da BD operacional. O backend não cria
FK entre as duas bases; os artigos são ligados por `ref`/`sku` textual.

## Configuração

- `PRICES_DATABASE_URL`: URL SQLite ou PostgreSQL.
- Por omissão: `sqlite:///./data/material_prices.db`.
- SQLite usa WAL e `BEGIN IMMEDIATE` para escritas; pedidos GET usam uma
  transação normal de leitura.
- A BD privada tem um mini-migrador próprio (`schema_version`). Não usar
  Alembic para esta base.

## Loader CLI

```text
python -m app.cli.load_material_prices --dir <pasta-privada> --dry-run
python -m app.cli.load_material_prices --dir <pasta-privada>
```

A pasta tem de conter `prices.json`, `brk.json`, `hager.json` e `rt-indus.js`.
O loader valida todos os ficheiros antes de gravar. O mesmo SHA-256 não é
carregado duas vezes (`price_import_batches`). `--dry-run` não insere linhas.
O output contém apenas contagens por domínio/dataset e contagens de conflitos;
nunca mostra preços, referências comerciais ou fornecedores.

`rt-indus.js` é tratado como texto: o loader extrai a atribuição literal
`INDUS={...}` e valida-a com parsing seguro. Não importa nem executa JavaScript.

## Endpoints

### `GET /api/cable-design/engine-data`

Requer `cable_design.edit`. Devolve o snapshot usado pelo motor:

```json
{
  "prices": [],
  "breakers": {},
  "indus": {},
  "versions": {"breakers": "sha256", "indus": "sha256"}
}
```

A resposta tem `ETag` e `Cache-Control: private, no-store`. Um
`If-None-Match` correspondente devolve `304` sem corpo. A indisponibilidade da
BD privada devolve `503` com mensagem genérica.

### `GET /api/material-prices`

Requer `price.view` (administrador e chefe de operações). Filtros opcionais:

- `domain`: `cabo`, `terminal`, `aparelho`, `quadro` ou `inventario`;
- `ref`;
- `current=true|false` (por omissão, só o preço ativo mais recente por
  `(domain, ref)`).

A resposta não permite escrita. `POST /api/material-prices/import` não existe
nesta fase: a importação é exclusivamente via CLI e requer acesso ao host que
guarda a pasta privada.

O acesso aos dados do motor continua separado: `cable_design.edit` permite
carregar o snapshot necessário ao dimensionamento, sem conceder a consulta
normal de preços (`price.view`).

## Permissões e migração

A migração Alembic `b2d4f6a8c0e1` provisiona apenas `price.view` e
`price.manage`, com tracking para downgrade seguro. `price.view` é concedida a
administrador e chefe de operações; `price.manage` apenas a administrador.

## Backups

`~/.hermes/scripts/op_pm_backup.sh` copia a BD operacional e
`material_prices.db` separadamente, usando `sqlite.backup`, `integrity_check`,
ficheiros temporários e modo final `0600`. A alteração foi preservada antes
em `op_pm_backup.sh.bak`. O script não deve ser executado em produção durante
esta alteração sem a validação operacional habitual.
