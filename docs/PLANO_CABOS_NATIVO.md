# Dimensionamento de cabos — UI nativa em React + motor como módulo (PR-3)

Estado: decisão do responsável do produto (19/10/2026): a versão com iframe (D-102) ficou «demasiado exterior». Passa a **UI reescrita em React nativo, sem iframe**, na **página própria** `/projects/:projectId/cables/:designId` (uma só barra; Revisões/Histórico numa gaveta). O **motor JS validado** passa a correr como módulo carregado do servidor (fora do Git). A versão iframe continua publicada e a funcionar até esta substituí-la; só se publica a nova quando estiver completa.

Mantém-se tudo o que já estava decidido em `PLANO_CABOS_FRONTEND.md` (capability `cable_design.view_costs`, preços privados, persistência por `/api/cable-designs` com `expected_version`, aprovação/nova revisão, sem importação `.json`, equipamentos só da base embutida, sem partilha/estado/«em obra» da ferramenta original).

> **Atualização (Fase 2, M2):** o motor deixou de correr na página (`<script src=blob:>` → `window.CabosEngine`). Corre agora num **iframe `sandbox="allow-scripts"` sem `allow-same-origin`** (`frontend/public/cable-engine-frame.html` + `.js`, servido pelo nginx com CSP própria: sem rede, `unsafe-eval` só ali), com origem opaca, sem acesso ao `sessionStorage`/tokens MSAL nem ao DOM da página, mas com DOM próprio: o motor real precisa de `Image`, `canvas` e `DOMParser` para exportar PDF/DOCX/PNG/DXF, o que um Web Worker não tem (testado). A UI usa uma fachada **assíncrona** (`engine.solve(...)` devolve `Promise`; dados estáticos — modelos, catálogos, `engine_version` — continuam síncronos) montada a partir da mensagem `ready`. Protocolo de mensagens (versão 1, validado nos dois lados, `event.source` do iframe verificado): `frontend/src/features/cables/engineWorker/protocol.ts`. Os ficheiros saem do iframe como `Blob` e é a página que os descarrega. A ponte iframe antiga (`cableBridge`) foi removida.

## Arquitetura

```
Op_PM (React)                                   Privado (fora do Git)
  CableDesignEditor (página)                     tool_src/ (repo privado) ──build──► engine/cabos-engine.js
   ├─ useCableEngine(): GET /api/cable-tool ───►  + manifest {engine_version, sha256}
   │    {engine_version, sha256, script}            (montado ro no backend: CABLE_TOOL_FILE)
   │    → executa o script (blob <script>) → window.CabosEngine
   ├─ store (reducer): State ──solve()──► Result   (puro, imutável)
   ├─ Separadores nativos: Cabos AC · Esquema unifilar · Quadros · Equipamentos
   └─ Guardar/Aprovar/Nova revisão/Desativar → /api/cable-designs (D-100)
```

- O motor corre no origin do Op_PM (é código nosso, sem input do utilizador a ser interpretado como código). Por isso o módulo **não pode** tocar no DOM da página hospedeira: só devolve dados/strings/Blobs; qualquer elemento auxiliar (canvas, `<a>`) é criado destacado e removido.
- Texto vindo do utilizador (nomes de quadros, projeto…) nos SVG gerados tem de estar escapado; o React insere o SVG do unifilar com sanitização (teste com `<script>`/`onerror`).
- Sem CDN: jsPDF/JSZip vão dentro do módulo (lazy: só inicializam ao exportar).

## API do módulo `window.CabosEngine` (versão 1)

Contrato **alvo**; a Fase M documenta a forma final exata em `ENGINE_API.md` + `engine.d.ts` (a copiar para `frontend/src/features/cables/engine.d.ts`). Tudo **puro e imutável**: recebe estado, devolve cópia nova; nunca guarda estado interno visível ao chamador.

```ts
interface CabosEngine {
  protocol: 1; engine_version: string;
  newState(templateId?: string): State;            // modelo por omissão (example()) ou modelo TPL
  templates: { id: string; label: string; description?: string }[];
  migrate(raw: unknown): State;                    // as regras do antigo load(); lança Error se não for um estado
  solve(state: State): { state: State; result: Result };   // state normalizado (temps por região, secções forçadas inválidas repostas…) + resultado do solveAll()
  summarize(result: Result): Summary;              // cartões do topo + contagem a rever
  catalogs: { inverters; panels; gateways; regions; installModes; materials; insulations; boardTypes; /* … o que a UI precise */ };
  actions: { /* funções puras (state,args)=>state para TODAS as mutações que o antigo rt-app.js fazia inline:
               adicionar/remover/duplicar inversor, escolher modelo (preenche potência/Smax), campos do inversor e do percurso,
               adicionar/remover percurso e gateway, criar quadro (popup «Novo quadro»), critérios, dados da obra, aplicar modelo, etc. */ };
  views: { sld(state,result): string /*SVG*/; boards(state,result): BoardsView; circuitRows(state,result): CircuitRow[]; reportRows… };
  exports: {                                       // todos devolvem { blob: Blob, filename: string }
    reportPdf; reportDocx; bomPdf; sldSvg; sldPng; sldDxf; copyTable(state,result): string };
  compare: { variants(state): Variant[]; apply(state, variantId): State };
}
```
Regras: sem preços nem custos no que o shell **guarda** (`result` persistido = só `circuits[]`, `totals`); o `Result` completo vive só em memória. O `engine_version` do manifesto fica guardado em cada revisão (backend já faz).

## Fases (cada uma termina com testes e relatório real)

- **M (motor)** — repo privado: `python build.py --engine` → `engine/cabos-engine.js` + manifesto (permissões `0755/0644` porque o contentor corre como uid 999). Paridade com o motor original em ≥ 8 estados (exemplo, modelos TPL, com/sem gateway, Al/Cu, B/B2 «sem secção», icu on, esteiras) por comparação profunda de `result`; XSS no SVG; módulo carrega em Node sem DOM para a parte pura; nenhum acesso a `document.getElementById` da página.
- **B (backend)** — `/api/cable-tool` passa a devolver `{engine_version, sha256, script}` (campo `script`; `CABLE_TOOL_FILE` aponta para o `.js`); mesma capability e limites.
- **U1 (fundação UI)** — `src/features/cables/`: tipos (`engine.d.ts`), `useCableEngine`, store/reducer com `solve` e dirty, página do editor (barra única; separadores nativos; gaveta Revisões/Histórico), Dados da obra e Critérios.
- **U2 (Cabos AC)** — inversores + percursos + resultados + avisos + estatísticas do topo.
- **U3 (Unifilar · Quadros · Equipamentos)** — SVG com zoom, exportações, quadros e envolventes, base de equipamentos só leitura.
- **U4 (diálogos e exportações)** — Comparar alternativas, Modelos/Novo projeto, Novo quadro, menu de exportações (PDF/Word/DXF/SVG/PNG/orçamento/copiar tabela).
- **V (verificação)** — suite completa, browser real (criar → editar → guardar → aprovar → nova revisão → exportar), paridade UI↔motor, remoção do iframe e de `cableBridge`, `D-103`, publicação (compose aponta para `engine/`; backup + `integrity_check`).

## Critérios de aceitação
- Resultado do motor idêntico ao original nos cenários de referência (testes de paridade).
- Nada de iframe: componentes, cores, fontes, claro/escuro e mobile do Op_PM; uma só barra de ações.
- Guardar/aprovar/nova revisão/409/423 como em D-102; suporte sem a capability não carrega o módulo (403).
- Exportações (PDF, Word, DXF, SVG, PNG, orçamento) descarregam e abrem.
- Sem preços/nomes de fornecedores no Git; o `result` persistido sem custos.
