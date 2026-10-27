# Importação de dados — notas iniciais e Excel de licenciamento

> **Estado: implementado e testado.** Notas iniciais:
> `app/services/imports_notes.py` +
> `frontend/src/pages/ImportNotes.tsx` (`tests/test_imports_notes.py`,
> `frontend/src/pages/ImportNotes.test.tsx`). Licenciamento (Excel):
> `app/services/imports_licensing.py` +
> `app/cli/import_licensing.py` (`backend/tests/test_import_licensing_sim.py`,
> `backend/tests/test_import_licensing_cli.py`).
> Este documento continua a ser a referência de desenho — o texto abaixo
> já descreve o comportamento real, não uma proposta.

## Princípios (aplicam-se aos dois importadores)

1. **Nunca escrever direto em `Project`/dados satélite** — sempre staging
   → resolução de conflitos → confirmação explícita, mesmo princípio já
   comprovado em `app/migration/staging.py` (D-005/D-017) para a
   migração de projetos legados.
2. **Nunca executar conteúdo do ficheiro como código** — nem
   `eval`/`exec`, nem um motor de JavaScript. HTML é lido como texto e
   parseado com um parser HTML normal (`html.parser`/`BeautifulSoup`).
3. **Hash do ficheiro original, dedução de duplicados** por
   `source_file_hash` — reimportar o mesmo ficheiro nunca duplica.
4. **Payload e documento de staging sanitizados sempre**, mesmo quando a
   normalização de campos falha parcialmente: a estrutura/texto útil é
   preservada, mas data URLs, credenciais e campos sensíveis são omitidos.
5. **Nenhuma credencial é importada** — allowlist de colunas/campos
   aceites, com denylist genérica de labels sensíveis; um campo não
   reconhecido é ignorado e reportado, nunca guardado "por precaução".
6. **Toda a resolução gera auditoria** — quem confirmou, quando, valor
   anterior/novo (reaproveita o padrão `ProjectDataHistory`/
   `ProjectHistory`, `source` a identificar a origem do lote).

## Modelo de staging dedicado

`ImportBatch`/`StagingProjectRecord` (já existentes) são específicos da
migração de projetos legados inteiros — a forma de conflito aqui é
diferente (por campo, não por projeto inteiro). Desenho:

- `FieldImportBatch` — um por ficheiro: `source_type`
  (`notes_html`/`notes_json`/`licensing_excel`), `source_file_hash`,
  `started_by_person_id`, `started_at`, `status`.
- `FieldImportRecord` — um por entidade-alvo detetada (projeto existente
  ou candidato a novo), com o payload normalizado.
- `FieldImportConflict` — um por campo com valor divergente do já
  existente: `field_name`, `old_value`, `new_value`, `resolution`
  (`pending`/`use_new`/`keep_old`/`manual`), `resolved_by_person_id`.

## 1. Notas iniciais (`notas-iniciais-v11.html`)

- O formulário já gera (ou deve passar a gerar) um bloco
  `<script type="application/json" id="notas-iniciais-data">{...}</script>`
  — o importador extrai só esse bloco, nunca interpreta `<script>` como
  código. Aceita também JSON solto (`.json`) ou o par JSON+HTML separado.
- Versão lida do conteúdo (`payload.formVersion` ou campo equivalente),
  **nunca do nome do ficheiro** — apesar do nome "v11", o conteúdo pode já
  ser da versão 12; aceitar as versões compatíveis conhecidas, rejeitar
  com mensagem clara uma desconhecida.
- Fluxo:
  ```
  POST /api/imports/notes/preview   (multipart; valida tamanho/extensão,
                                      calcula hash, rejeita duplicado,
                                      extrai+valida JSON, procura projeto
                                      existente por email/telefone/morada
                                      normalizada — nunca por nome, D-004
                                      — devolve preview + conflitos, sem
                                      escrever nada)
  POST /api/imports/notes/apply     (grava em staging; nunca direto em
                                      Project/ProjectInstallationData)
  GET  /api/imports/{batch_id}
  GET  /api/imports/{batch_id}/conflicts
  POST /api/imports/{batch_id}/conflicts/{id}/resolve
  ```
- A urgência é contexto livre do pedido (não um enum curto): aceita até
  **10.000 caracteres**, o mesmo limite conservador de `observacoes`/outros
  textos livres, e é preservada integralmente nas notas sanitizadas de
  `ProjectInstallationData.notes` (`Text`). Campos curtos de enum/código
  continuam com os limites próprios (por exemplo, 128 caracteres); o limite
  global do upload mantém-se em 5 MB.
- Um HTML sem o bloco estruturado, e sem conseguir extrair um mínimo
  (cliente + um campo técnico), devolve preview vazio — nunca cria um
  projeto vazio.

## 2. Excel de licenciamento — layout legado (`Sheet1`/`Internal_reference`)

- **Nunca commitado** — só fixtures sintéticas em `backend/fixtures/`.
- CLI controlado (mesmo padrão de `app.cli.ingest_staging`, D-037), nunca
  um endpoint casual:
  ```
  python -m app.cli.import_licensing --file <path> --dry-run
  python -m app.cli.import_licensing --file <path> --apply
  python -m app.cli.import_licensing --file <path> --rollback <batch_id>
  ```
- `Sheet1` → `Project`/`ProjectInstallationData`, chave `Internal_reference`
  (nunca `Project_number` sozinho — repete-se no legado).
- `Dados gerais` → `ProjectLicensingData`/`ProjectCommunicationData`,
  **allowlist explícita de colunas** — PIN/PUK/password/login/token
  nunca são sequer lidos, mesmo que a coluna exista na origem.
- `Venda do excedente` → `SurplusContract` (nova entidade, campos:
  projeto, comercializador, tipo de contrato, estado, envio, assinatura,
  duração, datas, observações) quando o vínculo ao projeto for
  inequívoco; senão, fila de conflitos.
- Normaliza datas, deteta duplicados, assinala encoding inválido e
  estados desconhecidos — nunca substitui um valor existente em silêncio.

## 2b. Excel de licenciamento — layout SIM (`sim_v1`)

O layout SIM é detetado pelo cabeçalho da linha 8 de `Dados gerais`. A folha
`Sheet1`, se existir, é ignorada; esta ligação é independente da chave
`Internal_reference` usada no layout legado.

- A coluna «Nº Projeto» da linha SIM é resolvida contra
  `ProjectExternalId.source_system = solcor_nomenclatura_xlsx`. Extrai-se o
  prefixo com `^\s*(\d+)_` de `external_id`; o número tem de corresponder por
  inteiro ao prefixo delimitado por `_` (por exemplo, `12` não casa com `123_…`).
- Só projetos ativos são candidatos. Registos de nomenclatura repetidos do mesmo
  `project_id` contam uma vez; o projeto único liga a linha, nenhum projeto ativo
  torna o número «não encontrado» e mais de um projeto ativo torna-o «ambíguo».
  Uma linha ambígua não grava SIM, credenciais, licenciamento nem histórico.
- O relatório `projetos_ambiguos` expõe apenas `{numero, quantidade}` por número,
  sem nomes de projetos. Números ambíguos não são contados como encontrados nem
  como não encontrados; um número repetido no ficheiro aparece uma só vez.
- `legacy_excel_licensing` é fallback por igualdade exata de `external_id`, e só
  quando não há qualquer correspondência numérica na origem de nomenclatura.
  Uma correspondência que só tenha projetos inativos também bloqueia o fallback;
  outras origens não participam na resolução.
- Os mapas de nomenclatura e fallback são carregados uma vez por execução e
  reutilizados no `dry-run`, no `apply` e na verificação prévia da chave de cifra.
  O layout legado não altera a sua regra de resolução.
- Utilização e validação continuam pelo CLI indicado na secção anterior. Os casos
  de prefixos, duplicados por projeto, inativos, ambiguidade, fallback e eficiência
  estão cobertos por `backend/tests/test_import_licensing_sim.py`.

## Testes existentes e validação pendente

Notas: JSON válido; HTML com JSON embutido; documento sanitizado
(reestrutura útil preservada, data URLs/credenciais omitidos); ficheiro inválido;
duplicado; versão desconhecida; campos em falta; projeto existente; conflito;
resolução; idempotência; auditoria; dados sensíveis nunca importados. Estes
casos estão cobertos por `backend/tests/test_imports_notes.py`.

Excel legado: `Sheet1`; licenciamento; M2M; UPAC; datas; estados; duplicados;
`Internal_reference` vs. `Project_number` repetido; credenciais nunca
importadas; `--dry-run`; `--apply`; `--rollback`. Layout SIM: prefixo da
nomenclatura Solcor; limites de prefixos numéricos; projetos inativos e
ambíguos; deduplicação por `project_id`; fallback legado condicionado; relatório
sem nomes de projetos e mapa carregado uma vez por execução. Estes casos estão
cobertos por `backend/tests/test_import_licensing_sim.py` e
`backend/tests/test_import_licensing_cli.py`.

O export real HTML fornecido para validação foi lido apenas fora do
repositório (`~/.hermes/private/op_pm_real/`); não é fixture nem é
versionado. A validação completa desse conteúdo deve continuar a ser feita
localmente, sem colocar nomes de clientes, sites ou contactos no Git.


## Pessoas de contacto (v11+)

O campo "Pessoas de contacto no local" (blocos `div.ct` com `<b>` nome, `span.fn` função e links `tel:`/`mailto:`) é extraído para `contactos` (máx. 50 pessoas, validadas como dados hostis). A **primeira** pessoa é o contacto principal (`contacto`, `funcao`, `telefone`, `email` → campos do projeto e `ProjectInstallationData`); as restantes ficam em `installation.notes` como "Contactos adicionais: …". Os links só são lidos como texto, nunca seguidos.
