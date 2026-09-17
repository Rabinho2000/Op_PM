# Importação de dados — notas iniciais e Excel de licenciamento

> **Estado: implementado e testado.** Notas iniciais:
> `app/services/imports_notes.py` +
> `frontend/src/pages/ImportNotes.tsx` (`tests/test_imports_notes.py`,
> `frontend/src/pages/ImportNotes.test.tsx`). Licenciamento (Excel):
> `app/services/imports_licensing.py` +
> `app/cli/import_licensing.py` (`tests/test_import_licensing_cli.py`).
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
4. **Payload original sempre preservado**, mesmo quando a normalização de
   campos falha parcialmente.
5. **Nenhuma credencial é importada** — allowlist de colunas/campos
   aceites (nunca denylist): uma coluna não reconhecida é ignorada e
   reportada, nunca guardada "por precaução".
6. **Toda a resolução gera auditoria** — quem confirmou, quando, valor
   anterior/novo (reaproveita o padrão `ProjectDataHistory`/
   `ProjectHistory`, `source` a identificar a origem do lote).

## Modelo de staging dedicado (novo, não implementado)

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
- Um HTML sem o bloco estruturado, e sem conseguir extrair um mínimo
  (cliente + um campo técnico), devolve preview vazio — nunca cria um
  projeto vazio.

## 2. Excel de licenciamento (`SIM card Numbers Projects.xlsx`)

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

## Testes previstos (não implementados)

Notas: JSON válido; HTML com JSON embutido; ficheiro inválido; duplicado;
versão desconhecida; campos em falta; projeto existente; conflito;
resolução; idempotência; auditoria; dados sensíveis nunca importados.

Excel: `Sheet1`; licenciamento; M2M; UPAC; datas; estados; duplicados;
`Internal_reference` vs. `Project_number` repetido; credenciais nunca
importadas; `--dry-run`; `--apply`; `--rollback`.
