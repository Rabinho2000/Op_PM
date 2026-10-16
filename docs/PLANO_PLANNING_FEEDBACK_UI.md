# Plano/UI — feedback do planeamento

Estado: implementado no snapshot `Op_PM-planning-feedback-20261015`, por
publicar. A página usa o contrato de `docs/API_PLANNING_FEEDBACK.md`; não cria
Tasks falsas, não edita o Processo e não usa Graph.

## Requisitos fechados

1. **Projetos pesquisáveis** — os dois seletores de projeto (filtros e modal)
   usam combobox acessível, pesquisa imediata sem acentos/case, ordem numérica
   natural (`123.2` antes de `123.10`), Escape/click exterior e limpeza
   explícita. Texto digitado sem escolha nunca é enviado como `project_id`.
2. **Vista guardada por conta** — a página começa no mês enquanto carrega
   `GET /api/me/planning-preferences`; aplica a resposta do servidor e o botão
   `Fixar vista` guarda vista + `hide_weekends` em `PATCH`. Falhas de leitura
   usam mês como fallback e mostram retry; falhas de escrita não bloqueiam o
   calendário e mostram retry.
3. **Calendário PT/Lisboa** — mês, semana e lista mantêm a janela completa
   enviada ao backend em Europe/Lisbon; ocultar fins de semana só remove dias
   da apresentação. Navegação, limites de dia e DST usam midnights locais, sem
   somar 24 horas fixas.
4. **Participantes** — criação/edição envia a lista N:N e mantém o primário
   legado no primeiro lugar. A vista mostra todos os nomes com `Avatar` de
   iniciais/fallback acessível, sem inventar URLs de fotografia.
5. **Categorias** — o catálogo do servidor alimenta select, legenda, filtros,
   cor e label dos eventos manuais e projetados. Não existe tabela local de
   labels/cores concorrente.
6. **Conflitos** — a interseção considera qualquer participante partilhado,
   ignora cancelados e permite confirmação explícita sem perder os restantes
   responsáveis no payload.
7. **Processo** — eventos manuais podem ligar etapa/subtarefa através de
   `GET process-options`; o seletor de tarefas normais continua separado. A
   página faz merge manual + projeção automática pela chave exata do contrato,
   preferindo manual, sem remover ocorrências com datas diferentes. Projeções
   são read-only, mostram origem/categoria/responsáveis e usam o
   `project_url`/`?tab=processo` devolvido pelo servidor.
8. **Filtros/regressão** — foram preservados todos/meus, PM, projeto,
   responsável, equipa e estado de cancelados; mudanças de projeto limpam
   tarefa e referências do Processo, com cancelamento de respostas assíncronas
   antigas e erro explícito. `ProjectsList`/`ProjectsList.css` e o helper de
   agrupamento não foram alterados.

## Ficheiros da fatia

- `frontend/src/pages/Planning.tsx`
- `frontend/src/pages/Planning.test.tsx`
- `frontend/src/pages/Planning.css`
- `frontend/src/api/client.ts` (tipos e funções do contrato de planeamento)
- `docs/PLANO_PLANNING_FEEDBACK_UI.md`

## Verificação local

- Vitest focado de planeamento: 10 testes passados.
- Suite Vitest do frontend: 43 ficheiros, 359 testes passados.
- `npm run lint`: passou.
- `npm run build`: passou; o Vite emitiu apenas o aviso já conhecido de chunk
  acima de 500 kB.
- `git diff --check` da allowlist da fatia: passou.

## Gates ainda fora desta fatia

- Não foi feito login interativo nem smoke test autenticado no browser.
- Não foi executado PostgreSQL; a validação do contrato/migração backend está
  no handoff backend separado.
- Não foi feito restart, deploy, commit, push, merge ou publicação.
- Antes de publicar, o parent deve aplicar apenas o delta desta allowlist ao
  alvo atual, confirmar byte-equal da preimagem e voltar a executar lint,
  Vitest e build no snapshot combinado.
