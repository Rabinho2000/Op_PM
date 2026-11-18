# Ficha de segurança por projeto — contrato da API

A ficha de segurança é um recurso 1:1 do projeto. O `PUT` substitui o conteúdo
completo e exige a versão devolvida pelo `GET`; ao criar, enviar `expected_version: 0`.

## Endpoints

- `GET /api/projects/{project_id}/safety-sheet` — devolve a ficha atual. Se ainda
  não existir, devolve os campos vazios e `version: 0`.
- `PUT /api/projects/{project_id}/safety-sheet` — substitui os campos e cria
  uma nova versão. Resposta contém a ficha gravada e a nova versão.
- `GET /api/projects/{project_id}/safety-sheet/workers-prefill` — sugestão de
  trabalhadores a partir das equipas atribuídas e das pessoas ativas associadas
  aos instaladores. A resposta é apenas uma sugestão; o cliente pode editá-la.
- `GET /api/projects/{project_id}/safety-sheet/history` — snapshots por versão,
  mais recente primeiro.
- `GET /api/projects/{project_id}/safety-sheet/print` — HTML imprimível A4,
  adequado a «Imprimir / Guardar como PDF» no browser.

## Payload de escrita

```json
{
  "expected_version": 0,
  "roof_type": "telha_ceramica",
  "roof_other": null,
  "approximate_height_m": 6.5,
  "access_method": "escada",
  "access_other": null,
  "risks": ["queda_altura", "eletrico_dc_ac"],
  "risk_other": null,
  "safety_measures": ["linha_vida", "arnes", "capacete"],
  "measure_other": null,
  "workers": [
    {"person_id": "UUID-ou-null", "name": "Nome à data", "installer_id": null, "team_id": null}
  ],
  "safety_responsible": "Nome do responsável",
  "emergency_contacts": "112; hospital mais próximo",
  "observations": "Observações de obra",
  "work_start_date": "2026-11-02",
  "work_end_date": "2026-11-04"
}
```

Valores permitidos:

- `roof_type`: `telha_ceramica`, `chapa_sandwich`,
  `chapa_simples_fibrocimento`, `laje_terraco`, `solo`, `outro`.
- `access_method`: `escada`, `andaime`, `plataforma_elevatoria`, `outro`.
- `risks`: `queda_altura`, `eletrico_dc_ac`, `fragil_claraboias`,
  `condicoes_meteorologicas`, `outro`.
- `safety_measures`: `linha_vida`, `arnes`, `capacete`, `luvas_dieleticas`,
  `calcado`, `guarda_corpos`, `outro`.

Os campos `*_other` guardam o texto complementar da opção «Outro». Quando
`person_id` é indicado, o servidor confirma a pessoa e guarda o respetivo
`display_name` como nome snapshot; quando é `null`, `name` identifica um
trabalhador externo sem registo de pessoa.

Campos não enviados no `PUT` assumem o valor vazio (`null`, lista vazia ou
`workers: []`); datas devem estar ordenadas e as opções de checklist não podem
repetir-se. `expected_version` obsoleto responde HTTP 409 com
`detail.current_version`. Um projeto invisível responde 404; falta de capacidade
de escrita num projeto visível responde 403; pedido sem sessão responde 401.

## Permissões

A leitura, histórico, pré-preenchimento e impressão estão disponíveis a quem
pode ver o projeto. O `PUT` exige `can_edit_project` ou
`project.safety_sheet.edit`, sempre dentro da visibilidade atual do projeto.
Instalador externo que veja a obra tem acesso só de leitura.

## Histórico e impressão

Cada gravação incrementa `version` e cria um snapshot imutável, incluindo a
lista de trabalhadores e os nomes no momento da gravação. O HTML de impressão
inclui nome, morada, PM e potência (quando disponível), além dos campos da ficha;
valores fornecidos pelo utilizador são escapados antes de serem incluídos no HTML.
Não há dependência de biblioteca de PDF no servidor.
