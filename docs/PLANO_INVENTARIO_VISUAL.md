# Inventário visual — contrato da API (backend)

Revisão Alembic: `d1f3b5c7e9a2` (anterior `b8d0f2a4c6e7`). Os ficheiros são guardados fora da BD em `INVENTORY_FILE_DIR` (predefinição `/app/data/inventory`): `item_photos/`, `item_documents/` e `category_images/`. Os nomes armazenados são UUIDs gerados no servidor; nenhum nome de artigo/cliente entra no caminho.

## Artigos e subsecções

`POST /api/inventory/items` e `PATCH /api/inventory/items/{item_id}` aceitam estes campos opcionais:

```json
{"manufacturer":"Marca Exemplo","model":"INV-5000","subcategory":"Híbrido","power_w":"5000.000","cross_section_mm2":"6.000"}
```

`manufacturer` e `model` têm máximo de 128 caracteres; `subcategory`, 100. Textos vazios são guardados como `null`. `power_w` e `cross_section_mm2` são decimais não negativos, com até 3 casas decimais. As respostas de leitura (`GET /api/inventory/items`, `/summary`, create e patch) incluem esses campos, `section_label` e `has_photo`, por exemplo:

```json
{"manufacturer":"Marca Exemplo","model":"INV-5000","subcategory":"Híbrido","power_w":"5000.000","cross_section_mm2":null,"section_label":"Marca Exemplo","has_photo":false}
```

`section_label` é calculado no servidor: Cabos DC/AC usam `cross_section_mm2` formatado `N mm²`, fallback `subcategory`, senão `Sem secção`; Inversores/Baterias usam `manufacturer`, fallback `subcategory`/`Sem marca`; Painéis usam marca e modelo separados por espaço, fallback `subcategory`/`Sem marca`; restantes usam `subcategory`/`Geral`. `has_photo` indica fotografia registada.

## Imagem de categoria

- `GET /api/inventory/categories` mantém o contrato antigo `string[]`.
- `GET /api/inventory/categories/details` devolve todos os nomes canónicos e estados:

```json
[{"name":"Painéis","has_custom_image":false,"image_version":null},{"name":"Inversores","has_custom_image":true,"image_version":"2026-10-22T12:00:00+00:00"}]
```

`image_version` é a data/hora ISO da substituição ou `null` (usar a ilustração predefinida).
- `POST /api/inventory/categories/{category}/image` — multipart `file`, JPEG/PNG/WebP, máximo 10 MiB; substitui a imagem e responde `200` com `{ "name":"Painéis", "has_custom_image":true, "image_version":"2026-10-22T12:00:00+00:00", "content_type":"image/png" }`.
- `GET /api/inventory/categories/{category}/image` — bytes e MIME detetado; `X-Content-Type-Options: nosniff`, `Cache-Control: private`. Sem imagem: `404`.
- `DELETE /api/inventory/categories/{category}/image` — remove a imagem e responde `204`; a categoria volta à ilustração predefinida. Categoria inválida: `422`.

## Fotografia do artigo

`POST /api/inventory/items/{item_id}/photo` recebe multipart `file`; aceita JPEG/PNG/WebP por magic bytes, até 10 MiB; substitui a fotografia anterior e responde `200` com `{ "has_photo":true, "content_type":"image/jpeg" }`. `GET` devolve os bytes com tipo detetado, `nosniff` e cache privada. `DELETE` limpa a foto e responde `204`. Sem foto: GET/DELETE `404`.

## Documentos do artigo

Tipos: `datasheet`, `manual`, `guia`, `outro`. Ficheiros PDF (`%PDF`), JPEG, PNG ou WebP (magic bytes), máximo 25 MiB.

- `POST /api/inventory/items/{item_id}/documents` — multipart `kind`, `title`, `file`; responde `201`:

```json
{"id":"4f0ad2b5-b7cd-4ab5-a994-d3f891ee8241","item_id":"cb59a686-6d5b-4a44-852e-4f019876c04d","kind":"datasheet","title":"Ficha técnica INV-5000","filename":"inversor.pdf","content_type":"application/pdf","size":245760,"created_by_person_id":"a42b3d7b-e5a3-4b3e-a76d-13d6f90ca640","created_at":"2026-10-22T12:00:00+00:00"}
```

- `GET /api/inventory/items/{item_id}/documents` — lista não removidos, recentes primeiro.
- `GET /api/inventory/items/{item_id}/documents/{document_id}/download` — `attachment` por omissão; `?inline=true` escolhe `inline`. Inclui `Content-Disposition` (fallback ASCII e `filename*` UTF-8/RFC 5987), nome sanitizado sem CR/LF/caminho, `nosniff` e cache privada.
- `DELETE /api/inventory/items/{item_id}/documents/{document_id}` — remoção lógica, `204`; oculta da lista e download passa a `404`; mantém conteúdo e metadados históricos.

A tabela guarda nome original (`filename`, só usado no cabeçalho sanitizado), nome interno UUID, MIME, tamanho, autor e timestamps.

## Resumo por categoria

`GET /api/inventory/categories/summary?owner=solcor` (ou `verde_milenar`, omissão `solcor`) devolve todas as categorias canónicas, inclusive vazias:

```json
[{"category":"Painéis","owner":"solcor","item_count":2,"stock_by_unit":[{"unit":"un","total_stock":"18.000"}],"low_stock_count":1},{"category":"Inversores","owner":"solcor","item_count":0,"stock_by_unit":[],"low_stock_count":0},{"category":"Cabos DC","owner":"solcor","item_count":2,"stock_by_unit":[{"unit":"m","total_stock":"4.000"},{"unit":"un","total_stock":"3.000"}],"low_stock_count":1}]
```

`stock_by_unit` agrega o stock físico por unidade (ordenado pelo nome da unidade); não existe total escalar, porque unidades diferentes não são somáveis. Categorias sem artigos ativos devolvem `[]`. Conta apenas artigos ativos; owners nunca se somam. `low_stock_count` continua a contar artigos cujo stock físico do proprietário selecionado está abaixo de `min_stock`.

## Permissões e erros

Leitura: `inventory.view`. Escrita de campos, fotos, documentos e imagens: `inventory.manage_catalog`. Sem sessão `401`; capability insuficiente `403`; artigo/ficheiro inexistente `404`; categoria/corpo/formulário inválido e números negativos `422`; magic bytes/formato inválido `400`; excesso de 10 MiB (imagem) ou 25 MiB (documento) `413`; falha ao persistir ficheiro `503`. Limites são aplicados lendo até limite+1 antes de guardar. Não são usados nomes do utilizador em caminhos de armazenamento.
