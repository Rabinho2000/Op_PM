# Dimensionamento de cabos — frontend no Op_PM (PR-2)

Estado: decisões fechadas pelo responsável do produto (19/10/2026). Base: `main` + WIP publicado de Pedidos/Banco de Horas (head Alembic `c6f8b0d2e4a5`). O backend de estudos (`/api/projects/{id}/cable-designs`, D-100) já está publicado; ver `docs/API_CABLE_DESIGNS.md` e `docs/PLANO_DIMENSIONAMENTO_CABOS.md`.

## Decisões fechadas

1. **Abordagem:** a ferramenta existente (página única com motor JS validado) é **embebida num iframe sandbox**; motor e UI ficam como no original (um só upstream). Só a persistência muda: um adaptador `postMessage` entre a ferramenta e o shell React, que faz as chamadas autenticadas a `/api/cable-designs`.
2. **Preços/catálogos comerciais:** ficam **fora do Git**. A ferramenta compilada (com preços, catálogo de aparelhagem e componentes de quadros) vive num ficheiro privado fora do repositório e é servida por um endpoint autenticado a quem tem a nova capability `cable_design.view_costs`. Risco aceite: os preços chegam ao browser desses utilizadores.
3. **Alocação ao projeto:** separador «Cabos» no detalhe do projeto (lista dos estudos do projeto, criar novo, abrir). O editor abre numa **página própria de ecrã inteiro** `/projects/:projectId/cables/:designId`.
4. **Pré-preenchimento:** novo estudo vem pré-preenchido com nome do projeto, cliente e morada. **Sem** importação de `.json` da ferramenta antiga.
5. **Âmbito da ferramenta:** cálculo + unifilar (SVG/PDF/DXF) + relatório (PDF/Word) + orçamento PDF + quadros. Equipamentos (inversores/painéis/gateways) só da base embutida, sem edição nem partilha pela equipa. **Saem** da versão embebida: separador Projetos, estado/«em obra»/acompanhamento, partilha de equipa, histórico/versões da ferramenta, importação de preços — o Op_PM já tem projeto, ciclo de vida, versões (409) e histórico.

## Arquitetura

```
Tailscale/nginx ──/api──► FastAPI
  React shell (ProjectDetail «Cabos», CableDesignEditor)
     │  fetch autenticado: GET /api/cable-tool  → {engine_version, sha256, html}
     │  PUT/POST /api/cable-designs/...         (expected_version, 409/423)
     ▼
  <iframe sandbox="allow-scripts allow-downloads" srcDoc={html}>   ← origem opaca (sem same-origin)
     ◄── postMessage ──►  adaptador embed (tool)
```

- O iframe **não tem** `allow-same-origin`: não acede a `localStorage`, cookies nem tokens MSAL. O shell valida `event.source === iframe.contentWindow` (a origem de um iframe sandbox sem same-origin é `"null"`).
- Sem CDN: jsPDF/JSZip vão inline no ficheiro compilado.
- Ficheiro privado: `cabos-embed.html` (pasta privada no servidor, fora do repositório) + `cabos-embed.manifest.json`; montado só-leitura no contentor do backend; caminho em `CABLE_TOOL_FILE`.

## Protocolo `postMessage` (versão 1)

Mensagens têm sempre `{source: "op-pm-cable", protocol: 1, type, ...}`.

Shell → ferramenta:
- `cable:init` `{state: object|null, readOnly: boolean, meta: {projectName, clientName, address, studyTitle, rev, status}}` — enviado depois de `cable:ready`. `state` é o conteúdo de `input_json.state` da revisão corrente (ou `null` num estudo novo: a ferramenta arranca com o seu modelo por omissão e pré-preenche nome/cliente/morada a partir de `meta`). `readOnly=true` quando a revisão está aprovada, o utilizador não tem `cable_design.edit` ou o estudo está inativo.
- `cable:snapshot-request` `{requestId}`.

Ferramenta → shell:
- `cable:ready` `{protocol: 1}` quando o motor carregou.
- `cable:dirty` `{dirty: boolean}` (debounce ~300 ms; `true` quando o estado difere do `init`/último snapshot confirmado).
- `cable:snapshot` `{requestId, input, result, engine_version}`: `input = {format: 1, state: S}`; `result = {format: 1, engine_version, circuits: [{code, name, review: boolean, note?}], totals: {circuits, review, inverters, kw_ac?}}`. **Sem custos no `result`** (a BD guarda-o e `suporte_operacoes` lê-o); preços ficam só dentro dos descarregáveis gerados no browser.
- `cable:error` `{message}`.

Shell → ferramenta, depois de gravar com sucesso: `cable:snapshot-saved` `{requestId}` (a ferramenta passa a considerar esse snapshot como o estado limpo e emite `cable:dirty {dirty:false}`).

Regras: a ferramenta nunca grava; quem grava é o shell, por botões próprios (Guardar, Aprovar, Nova revisão, Desativar) numa barra acima do iframe. O shell pede `snapshot-request` → recebe `snapshot` → `PUT /cable-designs/{id}/revisions/current` com `expected_version`. Aprovar = guardar + `POST /approve` (recusa 409 se `unresolved_circuits>0` — o shell mostra a mensagem). `Nova revisão` só em estudos aprovados.

## Backend (esta fase)

- Capability `cable_design.view_costs` — «Abrir a ferramenta de dimensionamento (inclui preços e catálogos comerciais)». Concedida a `administrador`, `chefe_operacoes`, `project_manager` (quem já tem `cable_design.edit`). `suporte_operacoes` continua só com `cable_design.view`: vê lista, estado, revisões e histórico, **não** abre a ferramenta. Migração M3 `d7a9c1e3f5b6` (`down_revision = "c6f8b0d2e4a5"`) com provisionamento rastreado, no-op em base vazia, downgrade só remove o que criou.
- `GET /api/cable-tool` → `200 {engine_version, sha256, html}`; exige `cable_design.view_costs` (403 senão; 401 sem sessão); `Cache-Control: private, no-store`; 503 sanitizado se `CABLE_TOOL_FILE` não está definido/não existe; limite de 8 MiB; o `engine_version` vem do manifesto ao lado do ficheiro, ou `cabos-rt@<sha256[:12]>` se não houver manifesto.
- Config: `CABLE_TOOL_FILE` (caminho opcional) em `app/config.py`.

## Frontend (shell React)

- `src/api/cableDesigns.ts`: tipos exatos dos DTOs do backend (ver `app/schemas/cable_designs.py`) + `getCableTool()`.
- Separador «Cabos» em `ProjectDetail` (visível com `cable_design.view`): tabela (Título, Estado, Rev., Circuitos a rever, Atualizado), «Novo estudo» (título; `engine_version` do manifesto da ferramenta quando o utilizador tem `view_costs`), abrir, desativar (com «Tens a certeza?»). Utilizadores sem `cable_design.edit` não veem criar/desativar.
- Página `CableDesignEditor` com barra (título, estado, revisão, versão, Guardar/Aprovar/Nova revisão/Desativar, painéis Revisões e Histórico) e iframe de ecrã inteiro. Aviso de alterações por guardar ao sair. 409 → diálogo «Outra pessoa gravou este estudo» com recarregar (descarta) ou copiar o estado atual; 423 → modo só leitura. Estudo sem `view_costs`: sem iframe, resumo + revisões + histórico e mensagem clara.

## Ferramenta (repositório privado, fora do Git do Op_PM)

Modo `embed` no build (`python build.py --embed` → `cabos-embed.html` + manifesto): sem `localStorage`/`claude.use`/API própria; sem separador Projetos, estados, acompanhamento em obra, partilha de equipa, versões, importação de preços; bibliotecas inline; `readOnly` via mensagem; o resto igual. O build normal e os 28 testes de motor ficam intactos.

## Fases / aceitação

1. F1: ferramenta embed (privado) ‖ backend (endpoint + capability + M3).
2. F2: frontend shell.
3. Integração real no browser (iframe + bridge), validação, `D-102`, publicação (compose local ganha o volume `CABLE_TOOL_FILE`; backup e `integrity_check` antes).

Aceitação: abrir um estudo novo pré-preenchido, editar, guardar (versão sobe), recarregar e reencontrar o estado; aprovar só sem circuitos a rever; revisão aprovada só leitura; nova revisão B; 409 com dois separadores; `suporte_operacoes` vê lista/histórico mas não abre a ferramenta (403 no endpoint); descarregar relatório PDF/DXF funciona dentro do sandbox; resultados do motor iguais aos do original nos cenários de referência (testes do motor 28/28).
