# BD privada de preços de materiais (PR-3, pré-requisito do dimensionamento de cabos)

Estado: em implementação, autorizado em 2026-10-16. Sem publicação nem merge sem OK.

## Porquê agora
O motor de dimensionamento (AppDimcable) usa preços **na decisão** (disjuntor mais barato por calibre, alternativas «mais barato e cumpre», terminais, orçamento). O repositório Op_PM é público: preços de compra e catálogos comerciais não podem entrar no Git nem nas migrações. Decisão do responsável do produto: BD **a parte**, só de preços de materiais, que no futuro recebe também os preços dos artigos do inventário.

## Desenho
- **Base física separada** `material_prices` (SQLite WAL em `…/data/material_prices.db` por omissão, ao lado da BD principal; URL configurável por `PRICES_DATABASE_URL`, dialeto SQLite ou PostgreSQL). Engine e sessão próprios (`app/prices_db.py`), sem FK para a BD principal (referências por `sku`/`ref` textual e `item_sku` opcional). Esquema versionado por um mini-migrador próprio (tabela `schema_version`, passos idempotentes em código), nunca Alembic da BD principal.
- Tabelas v1 (sem dados reais no Git):
  - `price_sources` (id, code único, name, kind `compra|catalogo|orcamento`, created_at).
  - `material_prices` (id, domain `cabo|terminal|aparelho|quadro|inventario`, ref String(128) (referência do fabricante/SKU), description, unit, unit_price Numeric(14,4) EUR líquido, source_id, price_date Date NOT NULL, attrs_json Text (ex. material Cu/Al, forma, secção mm², calibre), estimated Boolean, is_active, created_at). Índice (domain, ref, price_date). Histórico: nunca se sobrescreve; um preço novo é uma linha nova; «preço corrente» = a linha ativa mais recente por (domain, ref).
  - `price_import_batches` (id, source_file_sha256, loaded_at, rows_inserted, rows_skipped, actor text) para idempotência: o mesmo ficheiro não duplica.
  - `catalog_datasets` (id, name `breakers|indus|hager`, version String, content_sha256, payload_json Text, loaded_at, is_current): conjuntos de dados completos que o motor consome tal como foram gerados (ex. `brk.json` do ABB, componentes INDUS), versionados e imutáveis; só um corrente por nome.
- **Loader CLI** `python -m app.cli.load_material_prices --dir <pasta privada> [--dry-run]`: lê `prices.json` (linhas `[material, forma, secção, €/m, data, referência, designação, fornecedor]` → domain `cabo` ou `terminal` conforme a forma `term`), `brk.json` e `hager.json` → `catalog_datasets`, e os preços de `rt-indus.js` (`INDUS={ref:[descrição, €, data]}`, extraído por parsing seguro, sem executar JS) → domain `aparelho`/`quadro`. Preview (`--dry-run`) mostra contagens e conflitos; apply idempotente por sha256; falha fechada em ficheiro em falta ou malformado; nunca imprime preços nem fornecedores no log. A pasta privada vive fora do repo: `~/.hermes/private/op_pm_real/cable_design/` (já preparada, 0600).
- **Permissões** (provisionadas por migração da BD principal, padrão tracking `8a1d3f4c6b90`): nova `price.view` (ver preços de materiais) e `price.manage` (carregar/importar). `price.view` para administrador, chefe_operacoes; `price.manage` só administrador. **O dimensionamento precisa dos preços no browser para decidir**, por isso `cable_design.edit` dá acesso ao *dataset de cálculo* (endpoint abaixo) mas não à consulta/gestão geral de preços; a UI só mostra valores monetários a quem tem `price.view` (decisão provisória, a confirmar com o responsável: risco aceite de um PM ver preços pela rede).
- **API** (`/api`): `GET /cable-design/engine-data` (capability `cable_design.edit`; devolve `{prices:[…linhas no formato do motor…], breakers:{…}, indus:{…}, versions:{…sha256…}}` com ETag/`If-None-Match` 304; `Cache-Control: private, no-store`); `GET /material-prices?domain=&ref=&current=true` (`price.view`); `POST /material-prices/import` fora do âmbito (só CLI nesta fase). Falha 503 sanitizado se a BD de preços indisponível; nunca 500 com detalhe.
- **Backups:** `~/.hermes/scripts/op_pm_backup.sh` passa a incluir `material_prices.db` pela API de backup do SQLite (`integrity_check`), ficheiro 0600, mesma retenção.
- Docker: o ficheiro vive no volume de dados já existente; sem alterar o compose versionado. `/health` não expõe nada desta BD.

## Fora deste PR
Frontend, importar o motor JS, preços de inventário reais, endpoint de escrita via UI.

## Critérios
Testes sintéticos (valores inventados, formato igual ao real): loader dry-run/apply/idempotência/malformado, preço corrente por data, dataset corrente único, permissões 401/403, 304 por ETag, indisponibilidade 503, parsing INDUS sem executar código, ausência de preços/nomes reais no Git (`check_no_personal_names.py`). SQLite e PostgreSQL. `validate_oppm.sh` verde. Entrada `D-101` com «Verificado».
