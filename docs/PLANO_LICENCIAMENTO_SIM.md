# Licenciamento e comunicações — contrato da API (backend)

Decisão de arquitetura: `docs/DECISIONS.md` D-105. Este ficheiro é o contrato para o
frontend. Todas as rotas exigem autenticação (cabeçalho `Authorization` em produção;
`X-Dev-User-Email` só em desenvolvimento com `AUTH_ENABLED=false`).

Convenções comuns:
- Projeto inexistente **ou** sem visibilidade para o utilizador → `404`
  (`"Projeto não encontrado ou sem permissão para o ver."`). Nunca se distingue os dois casos.
- Permissão insuficiente sobre um projeto visível → `403`.
- Validação de corpo inválido em **todas** as rotas abaixo → `422` com corpo fixo
  `{"detail": "Corpo inválido."}`. O corpo recebido **não é ecoado** (importante para passwords).
- Chave de cifra não configurada/inválida (só credenciais) → `503`.
- Datas em `YYYY-MM-DD`. Campos não enviados num PATCH mantêm-se; `null` limpa.

---

## 1. Licenciamento

### `GET /api/projects/{project_id}/licensing-data`
Permissão: `project.view_licensing_data` + visibilidade do projeto.
Sem registo ainda → 200 com campos a `null` e `licensing_state = "sem_registo"`.

Resposta `ProjectLicensingDataRead`:
```json
{
  "project_id": "uuid",
  "upac_number": "string|null",
  "dgeg_number": "string|null",
  "cadastro_number": "string|null",
  "licensing_status": "string|null",
  "registration_date": "date|null",
  "certification_request_date": "date|null",
  "inspecting_entity": "string|null",
  "inspection_date": "date|null",
  "provisional_certificate_date": "date|null",
  "certificate_date": "date|null",
  "installer": "string|null",
  "commercializer": "string|null",
  "annual_production_kwh": "number|null",
  "comments": "string",
  "licensing_state": "sem_registo|cadastrado|certificacao_pedida|inspecionado|certificado_provisorio|certificado_definitivo",
  "updated_at": "datetime|null"
}
```

### `PATCH /api/projects/{project_id}/licensing-data`
Permissão: `project.edit_licensing_data` + `can_edit_project`. Corpo: qualquer subconjunto
dos campos editáveis (todos os campos acima exceto `project_id`, `licensing_state`,
`updated_at`). Resposta: o mesmo `ProjectLicensingDataRead`. Cada alteração gera linha em
`data-history` (`entity_type=licensing`).

### `licensing_state` (derivado, não guardado)
É a etapa mais avançada com data preenchida, por esta ordem:
`registration_date` → `cadastrado`; `certification_request_date` → `certificacao_pedida`;
`inspection_date` → `inspecionado`; `provisional_certificate_date` → `certificado_provisorio`;
`certificate_date` → `certificado_definitivo`. Sem nenhuma → `sem_registo`.
Não depende da ordem em que as datas foram preenchidas.

---

## 2. Comunicações (SIM / M2M)

### `GET /api/projects/{project_id}/communication-data`
Permissão: `project.view_communication_data` + visibilidade. Comercial e Financeiro não têm.

Resposta `ProjectCommunicationDataRead`:
```json
{
  "project_id": "uuid",
  "operator": "string|null",
  "gsm_m2m_number": "string|null",
  "card_identifier": "string|null",
  "communication_status": "string|null",
  "whereversim_login": "string|null",
  "operator_verified": "boolean|null",
  "operator_verified_date": "date|null",
  "notes": "string",
  "updated_at": "datetime|null"
}
```
`whereversim_login` é um identificador de utilizador, não um segredo. Não há campos de
PIN/PUK/password/token nesta resposta.

### `PATCH /api/projects/{project_id}/communication-data`
Permissão: `project.edit_communication_data` + `can_edit_project`. Corpo: subconjunto de
`operator`, `gsm_m2m_number`, `card_identifier`, `communication_status`, `whereversim_login`,
`operator_verified`, `operator_verified_date`, `notes` (`null` em `notes` → `""`).

---

## 3. Credenciais de portais (0..n por projeto)

Portais aceites (`portal`): `dgeg_login_geral` | `mastervantagem` | `outro`.

**Regra central: a password nunca sai numa resposta de lista, detalhe ou edição.**
Só `POST .../reveal` a devolve, e só com permissão própria.

Requer `OPPM_SECRETS_KEY_FILE` apontando para um ficheiro com uma chave Fernet (uma linha).
Sem ela, criar/alterar/revelar uma password responde `503`. Credenciais sem password
(só utilizador) continuam a funcionar.

### `GET /api/projects/{project_id}/credentials`
Permissão: `project.view_communication_data` + visibilidade.
Resposta: `PortalCredentialRead[]` (só registos não removidos, por ordem de criação):
```json
{
  "id": "uuid",
  "project_id": "uuid",
  "portal": "dgeg_login_geral|mastervantagem|outro",
  "username": "string",
  "has_password": "boolean",
  "updated_at": "datetime|null"
}
```

### `POST /api/projects/{project_id}/credentials`
Permissão: `project.credentials.edit` + `can_edit_project`. Resposta **201** `PortalCredentialRead`.
Corpo (sem campos extra):
```json
{ "portal": "dgeg_login_geral", "username": "string 1..256", "password": "string ≤512 | omitido" }
```
Se `password` for enviada, é cifrada antes de tocar na BD. Sem chave → `503`, nada gravado.

### `PATCH /api/projects/{project_id}/credentials/{credential_id}`
Permissão: `project.credentials.edit` + `can_edit_project`. Resposta `PortalCredentialRead`.
Corpo (sem campos extra):
- `portal`, `username`: opcionais; `null` ignora.
- `password`: **omitido** = mantém a password; **string não vazia** = substitui;
  **`null` ou `""`** = remove a password (`has_password` passa a `false`).

Credencial inexistente ou removida → `404` (`"Credencial não encontrada."`).

### `DELETE /api/projects/{project_id}/credentials/{credential_id}`
Permissão: `project.credentials.edit` + `can_edit_project`. Resposta **204**.
Remoção lógica: fica `deleted_at` preenchido e a password cifrada é apagada no mesmo passo.

### `POST /api/projects/{project_id}/credentials/{credential_id}/reveal`
Permissão: `project.credentials.reveal` + `can_edit_project`. Sem permissão → `403`,
sem registo no histórico.
Resposta `200` `PortalCredentialReveal`:
```json
{ "id": "uuid", "portal": "string", "username": "string", "password": "string" }
```
- Credencial sem password → `409` (`"Esta credencial não tem password definida."`).
- Chave indisponível → `503`; token que não decifra → `500` (sem o valor em nenhum dos casos).
- A revelação **regista primeiro** no histórico (`field_name=password_revealed`,
  `changed_by_person_id`, `changed_at`, sem valor). Se o registo falhar, a password não é devolvida.

Permissões por papel: `project.credentials.edit` e `project.credentials.reveal` estão
concedidas a `administrador`, `chefe_operacoes` e `project_manager`. Comercial e Financeiro não as têm.

---

## 4. Contratos de venda de excedente (0..n por projeto)

Leitura: `project.view_licensing_data` + visibilidade. Escrita: `project.edit_licensing_data`
+ (`can_edit_project` ou delegação do projeto). Sem permissão de escrita → `403`.

### `GET /api/projects/{project_id}/surplus-contracts`
Resposta: `SurplusContractRead[]` (sem removidos, por ordem de criação):
```json
{
  "id": "uuid",
  "project_id": "uuid",
  "commercializer": "string|null",
  "contract_type": "string|null",
  "contract_sent_date": "date|null",
  "signed_received_date": "date|null",
  "sent_to_commercializer_date": "date|null",
  "status": "string|null",
  "duration_months": "integer|null",
  "start_date": "date|null",
  "end_date": "date|null",
  "notes": "string",
  "updated_at": "datetime|null"
}
```

### `POST /api/projects/{project_id}/surplus-contracts`
Resposta **201** `SurplusContractRead`. Corpo (sem campos extra): os campos editáveis acima
(sem `id`, `project_id`, `updated_at`). Limites: `commercializer` ≤256, `contract_type` ≤128,
`status` ≤64, `duration_months` entre 0 e 600, `notes` sem limite na API.

### `PATCH /api/projects/{project_id}/surplus-contracts/{contract_id}`
Resposta `SurplusContractRead`. Corpo: subconjunto dos mesmos campos; `notes: null` → `""`.
Contrato inexistente ou removido → `404` (`"Contrato de excedente não encontrado."`).

### `DELETE /api/projects/{project_id}/surplus-contracts/{contract_id}`
Resposta **204**. Remoção lógica (`deleted_at`), com histórico.

---

## 5. Histórico

### `GET /api/projects/{project_id}/data-history[?entity_type=...]`
`entity_type` aceite: `installation` | `licensing` | `communication` | `credential` | `surplus`.
Cada tipo exige a permissão de leitura da sua entidade (credenciais: a de lista;
excedente: `project.view_licensing_data`); sem ela → `403` no filtro explícito.
Sem filtro, só aparecem os tipos a que o utilizador tem acesso.

Resposta `ProjectDataHistoryRead[]`:
```json
{
  "id": "uuid",
  "project_id": "uuid",
  "entity_type": "string",
  "record_id": "uuid|null",
  "field_name": "string",
  "old_value": "string|null",
  "new_value": "string|null",
  "changed_by_person_id": "uuid|null",
  "changed_by_person_name": "string|null",
  "source": "string",
  "note": "string",
  "changed_at": "datetime"
}
```
Para credenciais, `record_id` identifica a credencial. Valores de password **nunca** aparecem:
- alteração de password → `field_name="password"`, `old_value`/`new_value` = `"[definida]"` ou `null`,
  `note` = `"password alterada"` / `"password removida"`;
- revelação → `field_name="password_revealed"`, `old_value`/`new_value` = `null`,
  `note` = `"password revelada"`.

Para contratos de excedente, `record_id` identifica o contrato; `field_name` é `created`,
`deleted`, ou o nome do campo alterado.

---

## 6. Configuração e operação

| Variável | Uso |
|---|---|
| `OPPM_SECRETS_KEY_FILE` | Caminho para o ficheiro com a chave Fernet (uma linha). Nunca um valor inline. |

Gerar a chave (fora do repositório, fora de dados reais):
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" > /caminho/seguro/oppm_secrets.key`
e restringir permissões (`chmod 600`).

Migração: `b2d4f6a8c0e1` (revises `e9b1d3f5a7c8`) — colunas novas, duas tabelas novas,
duas permissões e as suas concessões às três funções. `downgrade` remove só o que criou.

---

## 7. Importação do Excel SIM

O contrato desta API descreve os dados de licenciamento e comunicações; a resolução
do nº de projeto no importador `sim_v1` está documentada em
`docs/DATA_IMPORTS.md` (secção 2b) e decidida em `docs/DECISIONS.md` (D-105).
O importador liga pelo prefixo numérico da origem `solcor_nomenclatura_xlsx`,
considera apenas projetos ativos e não aplica linhas sem correspondência inequívoca.
Vários projetos ativos para o mesmo número são reportados como ambíguos sem nomes
de projetos; um número sem correspondência de nomenclatura só usa o fallback exato
`legacy_excel_licensing`. O layout legado não muda.

---

## 8. Pendências (fora deste contrato)
- Frontend (separadores de credenciais, excedente e estado derivado).
- Rotação da chave Fernet (re-cifrar credenciais com nova chave): não implementada.
- Nenhuma notificação automática de estado de licenciamento.
