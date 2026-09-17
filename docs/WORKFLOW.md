# Percurso de obra (18 etapas)

O percurso de obra é o processo operacional de cada projeto: **6 fases, 18
etapas, subtarefas e pontos de contacto com o cliente**, com prazos em dias
úteis a partir da data de início do projeto. É o equivalente, na Op_PM, à
checklist/cronograma da plataforma original (`solcor-gestao.html`).
Decisão: `docs/DECISIONS.md` D-052.

## Onde está

| Peça | Ficheiro |
|---|---|
| Modelo (fases, etapas, subtarefas, progresso) | `backend/app/models/workflow.py`, `backend/app/models/project.py` |
| Definição + carregamento idempotente | `backend/app/workflow/definition.py` |
| Processo de **exemplo** (sintético) | `backend/app/workflow/processo_exemplo.json` |
| Datas, estados, marcação, histórico | `backend/app/services/workflow.py` |
| API | `backend/app/api/routes_workflow.py` |
| CLI | `backend/app/cli/workflow.py` |
| Interface | `frontend/src/components/ProjectWorkflow.tsx` (separador "Percurso de obra" do projeto) |

## O processo oficial NÃO está no repositório

O repositório é público. O repositório traz só um processo de exemplo com
a mesma forma (mesmas fases, números de etapa, prazos, dependências e
pontos de contacto), com texto genérico. O processo oficial vive num
ficheiro local, fora do Git — por convenção
`backend/data/processo_obra_solcor.json` (a pasta `data/` é ignorada).

Carregar (a simulação é o comportamento por omissão):

```bash
cd backend
python -m app.cli.workflow load --file data/processo_obra_solcor.json          # mostra o que muda
python -m app.cli.workflow load --file data/processo_obra_solcor.json --apply  # grava
python -m app.cli.workflow show                                                # confirma
```

Funciona em qualquer ambiente (local, staging, produção) — usa o
`DATABASE_URL` configurado. É idempotente e **recusa remover** etapas ou
subtarefas que já tenham progresso registado em algum projeto.

O seed de desenvolvimento/demonstração carrega o exemplo só numa base sem
percurso (ou com o seed genérico antigo de 6 etapas); nunca substitui um
percurso carregado pelo CLI.

## Formato do ficheiro

```json
{
  "name": "Percurso de obra — …",
  "phases": [{ "code": "handover", "name": "Handover e arranque", "color": "#2E75B6" }],
  "stages": [
    {
      "number": 4,
      "phase": "handover",
      "title": "E-mail de apresentação",
      "responsible_role": "project_manager",
      "responsible_label": "PM",
      "depends_on": 3,
      "start_day": 9,
      "end_day": 10,
      "contact": { "day": 9, "type": "contacto", "note": "Apresentação + agendar visita" },
      "note": "",
      "subtasks": ["Texto simples", { "title": "Contacto com o cliente", "client_contact": true }]
    }
  ]
}
```

- `number` — número da etapa (1..N), global a todas as fases. Chave estável:
  `etapa.NN`.
- Subtarefas — chave `etapa.NN.M` (posição dentro da etapa, a partir de 1),
  ou `code` explícito. **Reordenar subtarefas muda a chave**: o progresso
  fica associado à posição. Para inserir no meio sem baralhar o progresso,
  dar `code` explícito às subtarefas.
- `responsible_role` — um dos papéis da app (`administrador`,
  `chefe_operacoes`, `project_manager`, `comercial`, `financeiro`) ou
  `null`. `responsible_label` é o texto mostrado — **uma função, nunca o
  nome de uma pessoa**.
- `start_day`/`end_day` — dias úteis desde o início (dia 1 = data de
  início).
- `contact.type` — `contacto` (contacto com o cliente) ou `update`
  (atualização ao cliente); `contact.day` — dia útil do contacto.

## Regras

- **Datas:** dias úteis (segunda a sexta) a partir de `Project.start_date`.
  Feriados não são descontados (igual ao original). Sem data de início, o
  percurso aparece sem datas.
- **Estado de cada etapa:** `concluida` (todas as subtarefas feitas) →
  `atrasada` (prazo passou) → `em_curso` (alguma feita) → `a_aguardar`
  (a etapa de que depende não está concluída) → `por_iniciar`.
- **Dependências só informam** — nada impede marcar trabalho fora de
  ordem (não há regra de avanço de fase confirmada, OPEN_QUESTIONS #19).
- **Permissões:** ver o percurso = ver o projeto. Marcar = `project.edit_all`
  (Chefe de Operações, Admin) ou `project.edit_own_progress` sendo o PM do
  projeto. Comercial e Financeiro só leem.
- **Auditoria:** cada marcação/desmarcação fica no histórico do projeto
  (`percurso.etapa.NN.M` / `percurso.etapa.NN.contacto`), com autor e data.

## API

| Método | Caminho | |
|---|---|---|
| GET | `/api/projects/{id}/workflow` | Percurso completo com datas e estados |
| PUT | `/api/projects/{id}/workflow/subtasks/{code}` | `{"done": true}` |
| PUT | `/api/projects/{id}/workflow/stages/{code}/contact` | `{"done": true}` |

As escritas devolvem o percurso atualizado.

## Ainda não coberto

- Reagendar etapas (os "shifts" do PM e do Chefe e a vista Gantt de todas
  as obras do original).
- Duração da obra automática pela potência.
- Relação com as tarefas (`Task`) da Fase 1.5 — hoje coexistem; ver
  OPEN_QUESTIONS #19 e as perguntas 22/24.
- Importar o progresso dos 295 projetos do export legado (chaves
  posicionais `done['12.3']` → `etapa.12.4`) — faz parte da Fase 4.
