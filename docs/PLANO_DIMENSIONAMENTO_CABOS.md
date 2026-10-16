# Dimensionamento de cabos AC (estudos ligados ao projeto)

Estado: PR-1 (backend) em implementação, autorizado em 2026-10-16. Sem publicação nem merge sem OK.

## Decisões fechadas
- O motor de cálculo (JS) passa a viver no Op_PM, mas **sem preços nem catálogos comerciais**: esses dados ficam numa BD privada separada (PR-3), fora do Git, carregados por loader. Este PR-1 não toca em preços.
- Aprovação: quem pode editar o estudo pode aprová-lo (sem capability de aprovação separada). Fica registado quem e quando.
- Revisão aprovada é imutável. «Em obra/concluído» é o `lifecycle_status` do projeto, não do estudo.
- Sem nomes de pessoas/clientes/fornecedores no Git (D-073).

## Modelo (migração `a1c3e5f7b9d0`, `down_revision = "f3b5d7e9a1c2"`)
`cable_designs`: id (GUID), project_id (FK projects, NOT NULL, index), title (String 256), status (`rascunho|em_analise|aprovado`, default rascunho), current_revision (String 8, default "A"), version (Integer, default 1, para `expected_version`), is_active (Boolean, default true), created_by_person_id, created_at/updated_at (TimestampMixin).
`cable_design_revisions` (append-only de conteúdo; só a linha da revisão corrente em rascunho é atualizada): id, design_id (FK), rev (String 8), input_json (Text), result_json (Text), engine_version (String 64), content_sha256 (String 64, sobre input_json+result_json canónicos), unresolved_circuits (Integer, default 0: nº de circuitos «a rever» no resultado), status (`rascunho|aprovada`), approved_by_person_id, approved_at, created_by_person_id, timestamps. UniqueConstraint(design_id, rev).
`cable_design_history` (append-only): id, design_id, action (`created|saved|submitted|approved|new_revision|deactivated`), actor_person_id, rev, old_value/new_value (Text, JSON curto, sem o input/result completos), created_at. Escrito na MESMA transação da alteração.

## Permissões
Novas em `app/security/catalog.py` e provisionadas por migração própria (padrão de tracking da `8a1d3f4c6b90`; downgrade remove só o que criou; no-op em base vazia): `cable_design.view`, `cable_design.edit`. Papéis: administrador, chefe_operacoes e project_manager recebem view+edit; suporte_operacoes só view (âmbito delegado); comercial/financeiro/instalador_colaborador nada. Âmbito sempre por projeto: ver = `can_view_project`; editar/aprovar = `can_edit_project` do projeto E capability `cable_design.edit`. Verificação no serviço. Projeto inexistente/invisível → 404 (indistinguível); sem capability → 403 antes de qualquer lookup do projeto.

## API (prefixo `/api`)
- `GET /projects/{pid}/cable-designs` → lista (id,title,status,current_revision,version,updated_at,unresolved_circuits da revisão corrente), só ativos.
- `POST /projects/{pid}/cable-designs` `{title, input_json?, engine_version}` → 201 com revisão A em rascunho.
- `GET /cable-designs/{id}` → desenho + revisão corrente completa (input_json, result_json parseados como objetos JSON).
- `PUT /cable-designs/{id}/revisions/current` `{expected_version, title?, input, result, engine_version}` → grava na revisão corrente (só se rascunho/em_analise); recalcula `content_sha256` e `unresolved_circuits` (conta `result.circuits[]` com `review==true`, tolerante); versão obsoleta → 409; revisão aprovada → 423.
- `POST /cable-designs/{id}/approve` `{expected_version}` → recusa 409 se `unresolved_circuits>0`; marca revisão aprovada + status aprovado; 423 se já aprovada.
- `POST /cable-designs/{id}/new-revision` `{expected_version}` → só a partir de aprovado; cria rev seguinte (A→B…) copiando input/result, rascunho.
- `GET /cable-designs/{id}/revisions` e `GET /cable-designs/{id}/history`.
- `DELETE /cable-designs/{id}?expected_version=N` → remoção lógica (`is_active=false`), 409 se aprovado sem permissão… (simplificar: permitido se can_edit; histórico mantém).
Limites: input_json e result_json ≤ 2 MiB cada (413/422 sanitizado); JSON válido e objeto; strings sem controlo; schema mínimo `{"format":1}` obrigatório em `input`. Respostas nunca ecoam erros internos. `lifecycle_status IS NULL` tratado como ativo.

## Fora deste PR
Frontend, preços/catálogos privados, BOM→inventário, anexos, acompanhamento em obra, importação do servidor Node.

## Critérios de aceitação (backend)
Testes: 403/404 por âmbito (PM próprio vs alheio, suporte só leitura, comercial sem acesso), lifecycle nulo, concorrência (dois PUT com a mesma versão → um 409), aprovação com circuitos a rever (409), imutabilidade (423), nova revisão e hash, histórico na mesma transação (falha de auditoria reverte), limites de tamanho, replay seguro. SQLite e PostgreSQL. Migração up/down/up e provisionamento. Entrada `D-100` em `docs/DECISIONS.md` com «Verificado». `validate_oppm.sh` verde.
