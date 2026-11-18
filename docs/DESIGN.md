---
version: alpha
name: Op_PM Solcor Neutro
summary: Fundação visual C para Op_PM: temas neutros, identidade Solcor e controlos legíveis.
colors:
  primary: "#1e7a4b"
  secondary: "#125c37"
  tertiary: "#83cba4"
  neutral: "#f5f5f7"
  lightSurface: "#ffffff"
  lightRaised: "#ededf0"
  darkCanvas: "#1c1c1e"
  darkSurface: "#252527"
  darkRaised: "#303033"
  darkNav: "#212123"
  lightInk: "#1d1d1f"
  darkInk: "#e5e5e7"
  lightMuted: "#55555a"
  darkMuted: "#b7b7ba"
  linkDark: "#83cba4"
  focusLight: "#1e7a4b"
  focusDark: "#83cba4"
  onBrand: "#ffffff"
  onStatusFill: "#ffffff"
typography:
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, system-ui, sans-serif"
    fontSize: 15px
    fontWeight: 400
    lineHeight: 1.5
  body-emphasis:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, system-ui, sans-serif"
    fontSize: 15px
    fontWeight: 600
    lineHeight: 1.5
  control:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, system-ui, sans-serif"
    fontSize: 0.9rem
    fontWeight: 500
    lineHeight: 1.4
rounded:
  sm: 8px
  md: 10px
  lg: 12px
spacing:
  sm: 8px
  md: 16px
  lg: 24px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.onBrand}"
    rounded: "{rounded.sm}"
    height: 44px
  button-primary-hover:
    backgroundColor: "{colors.secondary}"
    textColor: "{colors.onBrand}"
    rounded: "{rounded.sm}"
    height: 44px
---

## Overview

A direção C é uma interface operacional de produto, não uma página promocional. Esta fundação aplica simplicidade, hierarquia e contenção inspiradas em software Apple, sem copiar ecrãs ou marca proprietária. A referência aprovada e durável é `(protótipo aprovado, fora do repositório)`. O protótipo orienta os tokens; o CSS existente continua a fonte de verdade da aplicação.

## Colors

- **Canvas claro:** `#f5f5f7`; superfície `#ffffff`; superfície elevada `#ededf0`.
- **Canvas escuro:** `#1c1c1e`; superfície `#252527`; superfície elevada `#303033`; navegação `#212123`.
- Neutros de canvas, superfícies, navegação, texto e contornos usam canais RGB iguais ou próximos: o modo escuro é grafite neutro, sem dominante verde.
- **Identidade Solcor:** `#1e7a4b`; preenchimento de marca `--brand-fill` e alias legado `--brand-identity` usam este verde nos dois temas, com `--on-brand: #ffffff` (5,33:1). Hover sólido usa `--brand-fill-strong: #125c37` (8,04:1 com branco). `--brand-text` e o alias legado textual `--brand-strong` são `#125c37` em claro e `#83cba4` em escuro; links usam `--link`/`--link-hover` com essas variantes legíveis. Não usar preenchimentos de texto claros com `--on-brand` branco.
- Texto primário: claro `#1d1d1f`, escuro `#e5e5e7`; secundário: claro `#55555a`, escuro `#b7b7ba`; subtil: claro `#68686d`, escuro `#9c9ca0`.
- Cores semânticas de sucesso, aviso, erro, informação e violet mantêm papéis distintos e fundos próprios. Verde não serve como decoração de grandes superfícies.

## Typography

Usar apenas fontes do sistema: `-apple-system`, `BlinkMacSystemFont`, `Segoe UI`, `system-ui`, sans-serif. Corpo base de 15px, pesos 400/500/600, line-height confortável e números tabulares (`tnum`, `lnum`). Evitar tracking agressivo, pesos decorativos e dependências de fontes externas.

## Layout

Shell operacional C: rail lateral de 68px por defeito e 248px quando expandido, com preferência guardada localmente por conta. No modo compacto, a marca mostra só o símbolo, os nomes permanecem acessíveis e visualmente ocultos, e a rolagem vertical usa uma barra fina por token sem overflow horizontal. Os grupos existentes, incluindo Administração e destinos condicionados por capability, permanecem iguais; badges de contagem só aparecem acima de zero. O cabeçalho apresenta o título da página, uma ação secundária discreta para Pedidos, o controlo de tema compacto (mantendo Claro/Escuro/Sistema e a persistência) e o utilizador. Até 760px, usar barra inferior com os destinos atuais de uso diário e “Mais” para abrir todos os destinos; a gaveta fecha com Escape e devolve o foco ao trigger. Manter alvos interativos com pelo menos 44px e espaçamento regular com base de 8px.

## Elevation & Depth

Preferir contraste tonal entre canvas, superfície e superfície elevada. Cartões comuns usam uma única borda discreta, sem sombra duplicada; reservar sombras moderadas para modais, popovers e feedback que realmente se eleva. Não usar blur, glow ou gradientes.

## Shapes

Controlos usam raio de 8px; cartões usam 10px; modais até 12px. Evitar cápsulas decorativas e arredondamento excessivo. Foco é um anel visível de 3px, com cor adaptada ao tema.

## Components

- Botões primários usam `--brand-fill`, texto `--on-brand`; hover usa `--brand-fill-strong`.
- Botões neutros, campos e selects usam superfície/texto/borda por tokens; inputs e selects normais têm altura mínima de 44px.
- Tabelas mantêm cabeçalhos legíveis, separadores contidos e rolagem horizontal quando necessária; dados numéricos são tabulares.
- Cartões, alertas, badges e modais usam superfícies e tokens semânticos existentes. Estados semânticos preservam cor e significado, sem reestilizar mapas ou calendários.
- Continuar a consumir os nomes de tokens existentes em `frontend/src/styles/app.css`; não introduzir hex dispersos em CSS de página.

### Painel principal — composição C

- Tratar o Painel como uma superfície **Monitor**: título e período primeiro, indicadores operacionais a seguir, depois mapa/obras e finalmente os restantes widgets. Sem hero, dados de exemplo ou métricas novas.
- Manter o cabeçalho e a ação «Atualizar» alinhados, com a janela temporal junto do título. Dar aos indicadores um cabeçalho simples e uma grelha compacta: cinco colunas em desktop, três em largura intermédia e duas em mobile.
- Reutilizar `StatCard`, os tons semânticos e os valores/links recebidos do servidor. Os indicadores podem ser visualmente mais compactos, sem remover ícones, alterar fórmulas, filtros, destinos ou gates.
- Manter o mapa e as listas «Obras a decorrer»/«Próximas obras» no mesmo bloco de visão de obras. Preservar `ProjectMapView`, provider fallback, camadas, marcadores, ligações e limites de projetos; não substituir nem redimensionar o mapa por conveniência estética.
- Manter todos os widgets de tarefas, projetos, férias e aniversários, com os respetivos links e estados. Reduzir espaçamento/bordas apenas com regras locais prefixadas ao Painel; não criar cartões dentro de cartões nem áreas verdes decorativas.
- A 390px, manter duas colunas compactas para indicadores, empilhar o bloco de obras/listas e não permitir overflow horizontal do documento. A navegação, permissões e alvos tácteis existentes continuam sob responsabilidade do shell partilhado.

### Inventário — composição C

- Tratar o inventário como superfície de exploração com ações operacionais: pesquisa e escolha de categoria primeiro; apenas “Registar movimento” recebe a ênfase primária.
- O proprietário Solcor/Verde Milenar é um único controlo segmentado com `aria-pressed`, persistência atual e alvos tácteis de pelo menos 44px em mobile.
- As âncoras Categorias, Localizações e Movimentos mantêm os seus IDs e apresentam seleção discreta com `aria-current`; não as transformar em pílulas grandes.
- Categorias usam cartões horizontais compactos com ilustração de 64–72px, nome, contagem, stock por unidade e ação de navegação; categorias vazias ficam atenuadas sem desaparecer por omissão.
- A pesquisa ocupa a largura disponível, mantém o atalho `/` e uma contagem discreta. A pesquisa tolerante e a sincronização de `categoria`/`q` com o histórico do browser são comportamento, não detalhe visual.
- Em ≥1100px, artigo selecionado abre uma ficha alinhada à direita da lista; em ecrãs menores mantém o modal/painel móvel. Ficha apresenta fotografia, metadados em `dl`, stock por localização e documentos autenticados; gestão continua condicionada à permissão existente.
- Usar apenas tokens para superfícies, texto, bordas e marca; não alterar o contrato da API, a persistência por proprietário, aliases legados, cálculos por unidade ou o livro append-only de movimentos.

### Projetos — lista operacional

- Tratar a lista de Projetos como uma superfície **Operate**: cabeçalho enxuto, uma ação primária conforme permissões e pesquisa/filtros alinhados antes dos controlos secundários da lista.
- Reutilizar as superfícies neutras, tipografia de sistema, botões e campos partilhados; reservar o verde Solcor para a ação principal e seleção/foco, mantendo cores semânticas dos estados existentes.
- Preservar pesquisa, filtros de tarefas/ciclo de vida/PM/datas/ativos, colunas, ordenação, vistas pessoais, preferências, grupos recolhíveis, paginação/URL/histórico, estado inline, remoção lógica/restauro e permissões sem alterar handlers ou contratos.
- A tabela mantém a leitura densa em desktop; entre 761–1100px, se necessário, a rolagem horizontal é local e sinalizada. Até 760px, respeitar a conversão global da tabela em cartões responsivos, sem largura mínima ou aviso de deslize; valores e ações permanecem legíveis sem overflow horizontal no documento.
- Estados de carregamento, erro e vazio permanecem explícitos; links, aviso de dados incompletos, progresso e controlos de estado não são removidos como simplificação visual.

### Obras — calendário operacional (composição C)

- Tratar Obras como superfície **Operate**: cabeçalho curto, controlos ordenados por vistas guardadas, escala/densidade/período, filtros e ações; apenas «Fixar vista» é primária, «Ver equipas» e restantes ações são neutras.
- Usar um único painel neutro para a toolbar, com separadores discretos entre grupos e sem cartões aninhados. Reutilizar tokens, selects e botões existentes; controlos tocáveis têm pelo menos 44px.
- No mobile e em ponteiros coarse, links autónomos de listas/cartões, títulos de célula e contactos/ações também têm alvo mínimo de 44px; não alargar links inline em parágrafos de prosa.
- Exceção de densidade: as barras de obra mantêm 38px; não as aumentar com a regra global de alvos tácteis.
- Manter o calendário como elemento dominante, com resumo do período e legenda junto à linha do tempo. Não reduzir largura dos dias nem trocar densidades Compacto/Normal/Grande para caber no viewport: o calendário continua largo e a rolagem horizontal fica dentro de `.works__scroll`.
- Tornar o deslocamento horizontal explícito por instrução visível e teclado no wrapper focável (setas esquerda/direita), sem substituir nem alterar `WorksTimeline`. Conservar arrasto/redimensionamento, cálculos, permissões, seleção, estado vazio, obras por planear e cores semânticas.
- Até 760px, empilhar os filtros em largura integral e reorganizar os segmentos sem corte; a 390px o documento não ganha overflow horizontal, mas o calendário continua deslocável localmente.
- Não alterar filtros, handlers, chaves ou valores do URL, preferências/persistência, modais, datas nem contratos. Tema claro/escuro usa superfícies neutras e acento Solcor através dos tokens existentes.

## Do's and Don'ts

- **Fazer:** reservar o verde para marca, ações, seleção discreta e estados positivos; verificar contraste textual normal ≥ 4.5:1 e foco/UI ≥ 3:1.
- **Fazer:** manter preferências `Sistema`, `localStorage`, autenticação e permissões fora da camada visual.
- **Não fazer:** transformar superfícies ou navegação em áreas verdes, adicionar gradientes/blur/glow, ou introduzir nova fonte/dependência.
- **Não fazer nesta fundação:** alterar estrutura da shell, inventário específico, APIs, autenticação, permissões ou cores semânticas de calendário/mapa.

### Detalhe do projeto — cabeçalho e navegação externa (C)

- Tratar a ficha como superfície **Command / Inspect**: objeto e estado primeiro, metadados legíveis, progresso e ações juntos, sem hero promocional nem novos blocos de resumo.
- O cabeçalho exterior usa a superfície neutra da página, uma separação tonal discreta e ações sem caixas redundantes. A ação permitida de edição é a primária; apagar mantém a apresentação de perigo e os guards existentes.
- A navegação horizontal conserva os onze separadores condicionados pelas permissões, os IDs/roles de tab, handlers e deep links `?tab=`. Em mobile, rola horizontalmente sem alargar o documento e mantém alvos tácteis de 44px.
- O resumo preserva estado, avisos, PM editável, cliente, data, potência, progresso e checklist; a ficha mantém intactos conteúdos, formulários, fotos/documentos, segurança e licenciamento.
- No PM da lista de Projetos, aplicar largura mínima de 180px apenas ao select direto na célula PM (`td.nowrap`), que pode mudar de ordem com a configuração de colunas; em mobile removê-la e manter o controlo fluido. Não estilizar todos os selects nem depender de `.select--compact`.
- Verificar o detalhe a 1440/390 em claro e escuro, além da lista PM a 1440/390, com dados sintéticos, deep link e retorno à lista.

### Tarefas — lista e quadro operacional (C)

- Tratar Tarefas como superfície **Operate**: título e contexto primeiro; alternância Lista/Kanban e a ação «Nova tarefa» ficam juntos no cabeçalho, com «Nova tarefa» como única ação primária e apenas quando o gate `can_manage_tasks` já a permite.
- Reunir filtros e opções da Lista num único painel neutro, sem cartões aninhados. Preservar os rótulos, valores, aliases/chaves de URL, ordenação, colunas reordenáveis, vistas pessoais e preferência de abertura exatamente como estão.
- A Lista mantém a tabela e as colunas existentes; em ecrãs pequenos, a sua largura pode ser percorrida dentro do wrapper, sem alargar o documento. Não converter a lista nem reestilizar as células neste marco.
- O Kanban conserva as cinco colunas por estado, contagens, paginação de cartões, drag-and-drop e seletor de estado condicionado por `can_edit`/transições permitidas. A grelha larga desloca-se localmente; o aviso horizontal só aparece quando a área disponível é menor que a largura mínima das colunas.
- Em 390px, organizar controlos em linhas fluidas e manter alvos tácteis de pelo menos 44px; o documento não ganha overflow horizontal. Claro/escuro usa os tokens neutros C e o verde Solcor apenas para ação/seleção/foco, sem mudar os tons semânticos das tarefas.
- Não alterar handlers, permissões, dados, filtros/API, cálculo de contagens, modais ou estado da tarefa; abrir/fechar a criação não deve perder a URL nem os filtros.
- Verificar a 1440/390 em claro e escuro, com papel de gestão e consulta: cabeçalho, filtros e controlos legíveis, scroll local real do Kanban, conteúdo da Lista, URL/histórico e ausência de ações de escrita para quem não as pode executar.

### Férias e aniversários — gestão secundária de feriados

- Tratar Férias e aniversários como uma superfície de trabalho diária: o calendário continua a mostrar os feriados relevantes, mas a gestão do catálogo não ocupa uma secção permanente nem apresenta o formulário ou a lista completa na página.
- Disponibilizar «Gerir feriados» como ação neutra no cabeçalho apenas para `holiday.manage`; manter a gestão num modal compacto, filtrado pelo ano corrente por omissão e com seletor de ano.
- Revelar o formulário de adição apenas após ação secundária. Não usar botão primário verde para adicionar, desativar ou reativar feriados; pedir confirmação antes de desativar um registo existente.
- Reutilizar os tokens e componentes existentes. Preservar Escape, restauro de foco, foco contido no modal e alvos tácteis globais de pelo menos 44px em mobile.
- Não alterar permissões, validações, chamadas API ou a representação de feriados na grelha do calendário.

### Hierarquia por importância — Inventário e Banco de Horas

- Configuração e administração de uso eventual não ocupa o fluxo principal de trabalho com catálogo completo ou formulário aberto. Mostrar primeiro o estado/resumo necessário à operação e oferecer gestão por ação secundária neutra.
- Em Inventário, manter a secção e o destino `#inventory-locations` navegáveis, com `aria-current` coerente; apresentar apenas a localização central ativa do proprietário selecionado, contagem curta e aviso quando não existe exatamente uma central. «Gerir localizações» abre o catálogo e os formulários existentes num modal, com o proprietário explícito e gestão restrita a `inventory.manage_catalog`.
- Em Banco de Horas, «Importar Excel» fica no cabeçalho como ação secundária apenas com as capabilities já requeridas (`time_bank.manage_all` e `time_bank.view_all`). Upload, preview, mapeamento, anomalias e confirmação vivem no modal; manter o readback da importação antes de recarregar o livro.
- Não alterar permissões, validações, handlers ou chamadas API ao recolher a interface. Usar componentes e tokens C existentes; preservar Escape, foco contido e restauro de foco, com alvos tácteis de pelo menos 44px em mobile.
