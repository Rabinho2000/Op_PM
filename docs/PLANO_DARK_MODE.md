# Plano — modo escuro da plataforma de operações

> Estado: **aprovado** pelo o responsável do produto em 2026-10-07, com as recomendações por omissão de D-X1…D-X4. Implementação em curso por PR.
> Origem: W-0052 — pedido de modo escuro para a plataforma de operações.
> Plano baseado na leitura do Op_PM, HEAD `794e12f`.
> As decisões em aberto estão na secção 5, com recomendação por omissão.
> Conforme D-073, não incluir nomes reais de pessoas/clientes, screenshots com dados reais ou fixtures identificáveis.

## 0. Pedido e âmbito

Adicionar três opções de aparência: Claro, Escuro e Sistema.

Preservar a identidade visual, a legibilidade dos estados operacionais e o comportamento existente. O tema não altera métricas, permissões, estados, filtros, cálculos ou dados enviados ao servidor.

Âmbito inicial: frontend, sem API nova nem migração de base de dados. Preferência local ao navegador/dispositivo. Relatórios destinados a clientes e impressão mantêm apresentação clara.

Fora do âmbito:
- Redesenhar a plataforma ou introduzir uma biblioteca de componentes.
- Alterar autenticação, contratos de API ou regras de negócio.
- Trocar o fornecedor de mapas ou contratar tiles.
- Sincronizar preferências entre dispositivos.
- Alterar envio de relatórios ou contactar destinatários.

Ordem proposta: PR1 infraestrutura → PR2 superfícies → PR3 relatórios/impressão → PR4 visualizações operacionais. Cada PR depende dos anteriores e não promete cobertura total antes de concluir a sequência.

## 1. O que já existe → consequência

Todos os caminhos frontend seguintes são relativos a `frontend/`.

| Peça | Estado atual e evidência | Consequência |
|---|---|---|
| Tokens CSS | `src/styles/app.css:8–53`: `:root` com fundos, superfícies, texto, bordas, marca, sidebar, tons semânticos, sombras e foco. | Reutilizar o sistema existente; acrescentar valores escuros e tokens em falta, não substituir o design system. |
| Cores literais no CSS | Ficheiro com 2883 linhas. Pesquisa encontrou 67 linhas com hex, 21 com `rgb()/rgba()` e 10 com valores nomeados `white/black/transparent`. Inclui tokens, sombras e exceções; categorias podem sobrepor-se. | Não são 98 cores únicas nem 98 substituições. Separar definições legítimas de tokens de literais em componentes. |
| Literais TSX | Pesquisa encontrou 9 linhas: 6 em `Map.tsx`, 2 em `ImportNotes.tsx` e 1 numa fixture de `ProjectProcess.test.tsx`. | Principal trabalho fora do CSS concentra-se no mapa e na importação; a fixture não é uma cor de produção. |
| Estilos inline | Pesquisa encontrou 166 linhas com `style={{` em TSX. Muitas só definem dimensões/geometria. | Não migrar indiscriminadamente todos os estilos inline; corrigir os que definem aparência incompatível. |
| Importação | `src/pages/ImportNotes.tsx:205,210`: fallbacks hex em `--color-brand/--color-border`, fundo RGBA e transparente. Os tokens principais chamam-se `--brand/--border`. | Normalizar referências e remover fallbacks que escondem tokens inexistentes. |
| Ícones e logo | `Icon.tsx:65–66` usa `currentColor`. `SolcorLogo.tsx:7,15–22,30–36` usa imagem externa e fallback SVG com `currentColor`. | Ícones acompanham tokens. Validar imagem e fallback separadamente; não inverter indiscriminadamente a imagem. |
| Metas e indicadores | `Performance.tsx:23–35,440` usa tons e `ProgressBar`; `ui.tsx:120–137` renderiza progresso com classes CSS. Não foi identificada biblioteca de gráficos nesta página. | Adaptar barras, rótulos e legendas existentes; não criar uma integração de gráficos desnecessária. |
| Mapa | `Map.tsx:8–11` usa Leaflet e markercluster; `:63–66` tem cores hex de camadas; `:111,562` gera HTML com cores/bordas/sombras literais. `:73–76` já usa tokens para atenção. | Tematizar controles, popups, marcadores e clusters; não basta trocar `:root`. |
| Tiles | `Map.tsx:576` usa `config.tile_url/tile_attribution`. `backend/app/config.py:150–151` define `MAP_TILE_URL/MAP_TILE_ATTRIBUTION`; a API transmite-os em `api/routes_map.py:135–136`. | O provider efetivamente configurado não foi consultado. Não assumir suporte a tiles escuros nem alterar configuração nesta proposta. |
| Calendário de obras | `WorksTimeline.tsx:213–240` usa tons de lifecycle e classes; inline serve sobretudo geometria. `app.css:2364–2370` já usa tokens nas barras. | Preservar drag/resize, conflitos e datas estimadas; testar combinação de estados e contraste. |
| Cores vindas de dados | `ProjectProcess.tsx:129` aplica `phase.color` recebido dos dados. | Um inventário de literais TSX não cobre todas as cores. Preservar identificação de fase sem usar cor arbitrária como texto de baixo contraste. |
| Relatório de cliente | O componente é `components/ClientReport.tsx`, não uma página singular. `:398–402` apresenta `body_html` num iframe `srcDoc`, com `sandbox=""`. `app.css:699–705` dá fundo branco ao iframe. | O documento do iframe é independente: CSS do pai não garante cor do texto/fundo interno. Manter isolamento e sandbox. |
| HTML enviado | `backend/app/services/client_reports.py:312–358` monta HTML simples do relatório, sem paleta explícita no trecho examinado. | Não afirmar que o email já está protegido contra dark mode. Clientes de email podem transformar cores independentemente da plataforma. |
| PWA e arranque | `index.html:6` tem `theme-color` fixo; `:14` contém favicon SVG com cores de marca. `public/manifest.webmanifest:8–9` define fundo e tema estáticos. `main.tsx:20–29` espera inicialização de autenticação antes de renderizar. | Resolver tema antes do primeiro paint, não apenas num efeito React nem depois da autenticação. Separar tema da página de splash/ícones da PWA. |
| Preferência existente | `Tasks.tsx:101,125` já guarda uma preferência de vista em `localStorage`. Pesquisa em `backend/app` por `preferences/user_settings/user_preferences/theme` não encontrou correspondências; `models/identity.py:56–70` não tem campo de aparência. | Recomendar preferência local, sem backend novo. A ausência resulta da inspeção do código, não de uma auditoria da base de dados. |
| Impressão | Pesquisa de `@media print` em `app.css` não encontrou regras. | Acrescentar política explícita; não assumir que imprimir a interface escura já produz documento claro. |

## 2. Contrato de aparência e estados semânticos

Manter separados:
- Preferência: `light | dark | system`.
- Tema efetivo: `light | dark`.
- Semântica operacional: permanece definida pela aplicação/API.

Proposta:
- Chave local versionada: `op_pm_theme_v1`.
- Ausência de preferência ou valor inválido: Sistema.
- `data-theme="light|dark"` no elemento `html`.
- `color-scheme` acompanha o tema efetivo, incluindo controles nativos.
- Escutar mudanças do sistema apenas quando a preferência for Sistema.
- Sincronizar a preferência entre separadores pelo evento `storage`.
- Falha de armazenamento não impede arranque nem mudança de tema na sessão.
- Não guardar identidade, tokens de autenticação ou dados pessoais nesta chave.

Inventário semântico mínimo:

| Família | Correspondência atual a preservar | Evidência |
|---|---|---|
| Tons base | brand, success, warning, danger, info, violet, neutral | `components/ui.tsx:7`; `app.css:967–997` |
| Projeto | não iniciado → neutral; em curso → info; concluído → success | `utils/labels.ts:6–10` |
| Lifecycle | on hold → warning; preparação → info; construção → brand; construído → violet; entregue → success; certificado final → neutral | `utils/labels.ts:13–20` |
| Tarefa | por fazer/cancelada → neutral; em progresso → info; bloqueada → danger; concluída → success | `utils/labels.ts:22–28` |
| Prioridade | baixa → neutral; média → brand; alta → warning; urgente → danger | `utils/labels.ts:30–35` |
| Ritmo de metas | acima → success; no ritmo → brand; abaixo → danger; sem objetivo → neutral | `pages/Performance.tsx:23–35` |
| Atenção no mapa | sem pendências → success; atenção → warning; crítico → danger | `pages/Map.tsx:73–88` |
| Atraso/conflito/estimativa | atraso de tarefa; conflito de equipa; datas estimadas | `app.css:1449`; `WorksTimeline.tsx:218–219,254`; `app.css:2373–2379` |

Cada tom deve ter combinações de texto, fundo e borda adequadas aos dois temas. Não usar a mesma cor obrigatoriamente para texto de badge e fundo de botão: criar tokens de contraste quando necessário.

Rótulo, ícone, padrão ou texto devem acompanhar cor nos estados relevantes. Conflitos e atrasos não podem tornar-se indistinguíveis em escala de cinzentos.

## 3. PRs propostos

### PR1 — Tokens escuros, preferência e seletor sem flash

Ficheiros:
- `frontend/index.html`.
- `frontend/src/main.tsx`.
- `frontend/src/styles/app.css`.
- `frontend/src/components/Layout.tsx`.
- `frontend/src/pages/Login.tsx`.
- Novos módulos pequenos de tema/seletor e respetivos testes.
- Documentação da preferência.

Implementação proposta:
- Preservar valores claros existentes.
- Definir paleta escura para tokens existentes e tokens de foreground/bordas/foco em falta.
- Bootstrap síncrono mínimo no head, anterior à renderização, com validação e tratamento de exceções.
- Evitar divergência entre resolver usado no bootstrap e no React; testar ambos contra os mesmos casos.
- Se houver política CSP incompatível com script inline, usar solução local compatível sem relaxar CSP.
- Seletor acessível Claro/Escuro/Sistema no cabeçalho/menu mobile e disponível no login.
- Sem animação global de transição de cores.

Testes Vitest:
- Preferência ausente, válida e inválida; sistema claro/escuro.
- Exceções de `localStorage` e ausência/falha de `matchMedia`.
- Mudança do sistema só afeta Sistema.
- Eventos `storage`, cleanup de listeners e React StrictMode.
- Seletor por teclado e nome acessível.
- Contraste calculado dos pares de tokens com helper de teste.

Critério:
- Tema aplicado antes de React/autenticação.
- Shell, login e controles base utilizáveis nos dois temas.
- PR1 não declara todas as páginas concluídas.

### PR2 — Migrar superfícies e cores hardcoded

Ficheiros:
- `frontend/src/styles/app.css`.
- `frontend/src/pages/ImportNotes.tsx`.
- `frontend/src/components/ui.tsx`.
- Revisão dirigida de `Layout`, `Login`, `ProjectDetail`, `Planning`, `Tasks` e páginas com superfícies próprias.
- `SolcorLogo.tsx` apenas se a verificação justificar adaptação.

Implementação proposta:
- Migrar literais de cabeçalho translúcido, alertas, banners, tabelas, skeletons, hover, overlays, foco e bordas para tokens.
- Normalizar tokens da zona de importação.
- Manter dimensões inline que não interferem com tema.
- Preservar `currentColor` em SVG.
- Não usar filtros CSS globais de inversão.
- Exceção de contraste pré-existente a resolver neste PR: `--violet` sobre `--violet-soft` no tema claro mede 4,48:1. Os tokens claros são preservados no PR1; a verificação mantém allowlist exclusiva com piso de 4,4:1 até ao PR2.
- Exceções de marca/documento claro ficam identificadas, não escondidas em fallbacks.

Testes Vitest:
- Badges, alertas, progresso completo/incompleto, erros, loading e disabled.
- Interação de upload/drag sem regressão.
- Logo com carregamento e erro simulados, sem pedido externo nos testes.
- Verificação de tokens e inventário de literais residuais com allowlist explícita.

Critério:
- Nenhuma superfície clara involuntária nem texto ilegível nas páginas auditadas.
- Modo claro mantém aparência e comportamento anteriores.
- Literais restantes justificados: tokens, marca ou documento claro.

### PR3 — Relatórios, impressão e acabamento PWA

Ficheiros:
- `frontend/src/components/ClientReport.tsx` e teste existente.
- `frontend/src/styles/app.css`.
- `frontend/index.html`.
- `frontend/public/manifest.webmanifest`.
- Módulo de tema do PR1.
- Alteração de HTML no backend apenas se uma revisão separada demonstrar necessidade; não incluir mudança de envio neste PR.

Implementação proposta:
- Interface de configuração/histórico acompanha tema; documento apresentado ao cliente fica claro.
- Garantir fundo, texto e `color-scheme: light` dentro do documento de preview, sem remover sandbox nem executar conteúdo.
- Não alterar o HTML enviado apenas para adaptar a preview.
- `@media print`: tokens claros, fundo branco, texto escuro, sem navegação e sem cortar conteúdo.
- Atualizar `theme-color` da página com o tema efetivo.
- Manter manifest/splash estáticos de marca por omissão; não prometer que acompanham `localStorage`.
- Favicon/ícones de marca não precisam de inversão.

Testes Vitest:
- Preview com tema escuro mantém documento claro e sandbox.
- Conteúdo do relatório não muda com o seletor.
- Meta `theme-color` acompanha mudanças.
- Contrato das regras de impressão; teste real em browser obrigatório para paginação.

Critério:
- Preview e impressão controladas pela plataforma permanecem claros.
- Nada é enviado durante testes.
- Transformações de cor feitas por clientes de email externos são documentadas como fora de controlo.

### PR4 — Mapa, timeline, planeamento e cores provenientes de dados

Ficheiros:
- `frontend/src/pages/Map.tsx` e testes.
- `frontend/src/components/WorksTimeline.tsx` e testes.
- `frontend/src/pages/Planning.tsx`.
- `frontend/src/pages/Performance.tsx`.
- `frontend/src/components/ProjectProcess.tsx` e testes.
- `frontend/src/styles/app.css`.

Implementação proposta:
- Substituir HTML inline de marcadores/clusters por classes e tokens, incluindo foreground sobre cada fundo.
- Tematizar popups, controles e clusters Leaflet; preservar attribution e pior nível de atenção.
- Manter tiles configurados. Sem filtro de inversão, mudança de fornecedor ou chamadas adicionais.
- Se necessário, regenerar ícones ao mudar tema sem recriar desnecessariamente o mapa nem perder viewport.
- Validar calendário: hoje, fins de semana, seleção, estimativas, conflitos, drag e resize.
- Performance: adaptar barras existentes e respetivos textos, sem biblioteca nova.
- `phase.color`: usar como sinal secundário com contorno/superfície contrastante; manter rótulo textual e fallback seguro.

Testes Vitest:
- Marcadores e clusters: categorias, contagem, prioridade de atenção e tema; Leaflet/tiles simulados, sem rede.
- Tema não altera filtros, viewport ou resultados operacionais.
- Timeline: tons, conflito+estimativa, arrastar/redimensionar e labels.
- Planeamento: seleção e estados.
- Fases com cores pouco contrastantes ou ausentes.
- Metas: progresso e ritmo mantêm os mesmos valores.

Critério:
- Visualizações operacionais legíveis nos dois temas.
- Nenhuma mudança de provider/configuração.
- Mapa sem tiles configurados continua funcional na alternativa existente.

## 4. Verificação e critérios de aceitação

A aprovação final exige:
- Texto normal ≥ 4,5:1; texto grande ≥ 3:1.
- Controles e informação gráfica essencial ≥ 3:1 face à cor adjacente, quando aplicável a WCAG AA.
- Foco visível, distinguível e sem depender de sombra pouco contrastante.
- Estados compreensíveis sem depender exclusivamente da cor.
- Paletas medidas, incluindo transparências sobre o fundo efetivo; o comentário atual do CSS não é prova de conformidade da nova paleta.
- Sem flash do tema errado em reload, navegação direta, login e retorno da autenticação.
- Claro/Escuro/Sistema persistem conforme contrato e funcionam sem armazenamento.
- Relatórios/preview e impressão claros.
- Mobile: seletor acessível, sem overflow, alvos de interação adequados e sem regressões nas tabelas-cartão/menu.
- Verificação a 360 px, nos breakpoints relevantes e desktop; zoom a 200%.
- Respeito por `prefers-reduced-motion`.
- Sem dados pessoais em fixtures ou evidência publicada.

Comandos previstos, não executados neste planeamento, a partir de `frontend/`:
- `npm test`
- `npm run lint`
- `npm run build`

Vitest/jsdom não prova primeiro paint, contraste renderizado, tiles reais, impressão ou comportamento PWA. Complementar com revisão em browser, screenshots sintéticas e medição de contraste. Não substituir esta verificação por snapshots de classes.

## 5. Decisões em aberto

### D-X1 — Tema por omissão

Recomendação: Sistema; Claro e Escuro são escolhas explícitas. Sem migração de preferências antigas porque não foi identificada preferência de tema.

### D-X2 — Persistência e alcance

Recomendação: `localStorage`, por navegador/dispositivo, independente da conta e mantido no logout. Evita API/migração e permite resolver o tema antes da autenticação.

Sincronização por utilizador/dispositivo fica para pedido futuro; exige contrato de precedência entre conta, preferência local e sistema.

### D-X3 — Mapa e tiles

Recomendação: escurecer controles/overlays, mantendo tiles existentes. Tiles escuros só numa proposta posterior após confirmar suporte, licença, attribution e configuração do provider.

### D-X4 — Relatórios e impressão

Recomendação: preview de cliente e impressão sempre claros; configuração/histórico seguem o tema da plataforma. Não modificar envios ou prometer controlo sobre modo escuro de clientes de email.

Os identificadores D-X1…D-X4 são provisórios deste plano. Só promover decisões aprovadas para a numeração sequencial de `docs/DECISIONS.md`.

## 6. Riscos e desconhecidos

- O provider de tiles live e o seu suporte a tema escuro são UNKNOWN.
- Não foi medida a paleta atual nem proposta uma paleta escura final.
- Não foi inspecionada a política CSP efetivamente aplicada em produção.
- Preferência de conta não foi encontrada no código examinado; não se auditou a BD.
- Cores recebidas em dados, CSS de terceiros e imagens não são totalmente cobertas por pesquisa de hex em TSX.
- O maior risco funcional está em mapa/timeline; a mitigação é manter cálculos e interações fora da mudança de tema.
- O splash da PWA e clientes de email têm limites próprios; não confundir esses limites com falha do seletor.
- Nenhuma implementação, teste funcional, commit ou deploy faz parte deste plano.

## 7. Estimativa por PR

Estimativas de engenharia, não compromisso de calendário; incluem testes e revisão:

| PR | Esforço estimado |
|---|---|
| PR1 — tokens, preferência, seletor e bootstrap | 1–2 dias |
| PR2 — superfícies, literais e componentes base | 2–3 dias |
| PR3 — preview, impressão e PWA | 1–2 dias |
| PR4 — mapa, timeline, planeamento e dados de cor | 2–4 dias |

A confirmação do provider, eventual sincronização backend ou alteração de emails aumenta o âmbito e exige nova estimativa.
