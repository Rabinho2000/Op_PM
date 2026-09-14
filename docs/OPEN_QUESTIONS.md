# Perguntas em aberto — Op_PM

> Cada pergunta bloqueante/importante indica: impacto, a decisão necessária,
> e uma recomendação por defeito (quando existe uma razoável) — mas nenhuma
> resposta foi assumida no código ou nos outros documentos sem confirmação.
> Duas perguntas da versão anterior deste documento já ficaram resolvidas
> nesta sessão — ver "Resolvidas" no final.

## Bloqueantes

### 1. Tenant Microsoft 365 / Entra ID

**Impacto:** sem isto, a Fase 1 (autenticação real) e a Fase 3 (Graph real —
email/calendário) não podem avançar além do mecanismo de desenvolvimento
(`AUTH_ENABLED=false`, D-012).

**Decisão necessária:** confirmar que existe um tenant Microsoft 365
administrável, com alguém capaz de registar uma aplicação (app
registration) e conceder consentimento de administrador para os âmbitos
necessários (Mail.Send, Calendars.ReadWrite, Files.ReadWrite, etc.).

**Recomendação por defeito:** nenhuma — depende inteiramente de recursos
que só a organização tem.

### 2. Sistema Financial

**Impacto:** sem isto, a Fase 5 (custos reais/margens) fica limitada a
custo estimado; `CsvFinancialAdapter` já existe mas precisa de um CSV real
exportado manualmente enquanto não há decisão.

**Decisão necessária:** que sistema é, e que opções de integração existem —
API, exportação CSV/Excel, ou só relatório manual.

**Recomendação por defeito:** usar o modo CSV (`FINANCIAL_MODE=csv`) como
primeiro passo, independentemente da resposta final — é o caminho que
funciona com o menor compromisso técnico.

### 3. Regra oficial para os campos obrigatórios de um projeto

**Impacto:** sem isto, os endpoints de criação/edição de projeto da Fase 1
não sabem que validação aplicar; o modelo atual (`Project`) tem quase todos
os campos opcionais de propósito, para não bloquear a preservação dos
projetos incompletos (108–198 dos 295 projetos reais, conforme a análise do
repositório do código legado, não têm coordenadas/email/contacto).

**Decisão necessária:** o responsável operacional define quais campos são
realmente obrigatórios (e a partir de quando — na criação, ou só para
avançar de fase do workflow).

**Recomendação por defeito:** nenhum campo obrigatório à criação (preserva
o padrão atual dos dados reais); obrigatórios só para avançar certas
etapas do workflow (ex. não pode agendar comissionamento sem contacto).

### 4. Calendários e equipas a considerar no planeamento de visitas

**Impacto:** sem isto, `get_availability` (Fase 3) não sabe que calendários
consultar via Graph.

**Decisão necessária:** confirmar se é o calendário individual de cada PM,
um calendário partilhado de operações, ou ambos.

**Recomendação por defeito:** calendário individual de cada PM + um
calendário partilhado de "visitas" para visibilidade cruzada.

### 5. Quem aprova o quê

**Impacto:** o modelo de permissões (`ARCHITECTURE_PROPOSAL.md` secção 5)
já distingue "criar rascunho" de "aprovar", mas a matriz exata de quem
aprova email/visita/pedido de material/adjudicação/custo por tipo de
projeto ainda não está confirmada.

**Decisão necessária:** confirmar a matriz de aprovação por perfil e, se
necessário, por valor/tipo de projeto (ex.: acima de X€ precisa de
aprovação adicional).

**Recomendação por defeito:** a matriz já implementada em
`app/security/catalog.py` (Chefe de Operações e Administrador aprovam
tudo; PM aprova só o seu próprio envio/evento) — a confirmar ou ajustar.

## Importantes

### 6. Uma visita pode envolver mais do que uma pessoa/equipa?

**Impacto:** afeta o modelo de `visits`/`calendar_events` (hoje 1
`created_by`/1 `approved_by`, sem lista de participantes internos além dos
`attendees` do evento).

**Recomendação por defeito:** assumir que pode haver múltiplos
participantes internos desde já no modelo de `calendar_events.attendees`
(já suportado), sem alteração de schema.

### 7. Horários, zonas geográficas, almoço, limites diários

**Impacto:** necessário para `propose_visit_dates`/`analyze_travel` (Fase 3
e o cálculo determinístico de deslocações).

**Recomendação por defeito:** nenhuma sem confirmação — este cálculo é
demasiado específico do negócio para assumir um valor por defeito seguro.

### 8. O cliente escolhe a data ou só recebe propostas?

**Impacto:** afeta se `email_drafts`/`visits` precisam de um mecanismo de
confirmação externa (ex. link para o cliente escolher).

**Recomendação por defeito:** só propostas por email nesta fase — evita
construir um portal externo sem necessidade confirmada.

### 9. Fornecedores a suportar na primeira versão

**Impacto:** afeta o catálogo inicial de `suppliers` na Fase 5.

**Recomendação por defeito:** nenhum pré-carregado — criar conforme
necessidade real, sem inventar uma lista.

### 10. Como são recebidos e aprovados os orçamentos de fornecedores

**Impacto:** afeta o fluxo de `material_requests` (estado
`orcamento_recebido` → `aprovado`).

**Recomendação por defeito:** anexo de documento (via biblioteca
documental, Fase 6) + aprovação manual no estado do pedido — sem
integração automática de parsing de orçamento nesta fase.

### 11. Estrutura atual da Drive e permissões por documento

**Impacto:** afeta o desenho da Fase 6 (biblioteca documental).

**Recomendação por defeito:** nenhuma sem confirmação — herdar a estrutura
e permissões do SharePoint existente é mais seguro do que assumir uma nova.

### 12. Quantos anos de histórico devem ser migrados

**Impacto:** afeta o volume e o esforço da Fase 2 (migração real).

**Recomendação por defeito:** migrar tudo o que existir no export legado —
o mecanismo de staging já preserva campos incompletos sem custo adicional
por migrar mais dados.

### 13. Fecho de visita/comissionamento: bloqueio rígido ou aviso?

**Impacto:** afeta `form_responses.status` (`bloqueado_fotos` como estado
rígido vs. apenas um aviso ignorável).

**Recomendação por defeito:** bloqueio rígido, com possibilidade de
override explícito por um Administrador/Chefe de Operações (nunca
silencioso).

### 14. Orçamento/limite de uso da API Claude

**Impacto:** afeta a Fase 7 — sem limite definido, o custo pode escalar sem
controlo.

**Recomendação por defeito:** definir um teto mensal antes de
`CLAUDE_ENABLED=true` alguma vez ser verdadeiro fora de desenvolvimento.

### 15. Retenção de dados (backups, logs, exports antigos)

**Impacto:** afeta o plano de backups/segurança (`docs/PLAN.md`).

**Recomendação por defeito:** nenhuma sem confirmação — é uma decisão de
compliance/privacidade que não deve ser assumida tecnicamente.

### 16. `upacRegisto`/`m2mCard`: há um sistema externo que devia ser a fonte de verdade?

**Impacto:** a revisão de hardening da Fase 0 deu a estes dois campos
legados (registo UPAC, cartão M2M) um lugar explícito no `Project`
(`upac_registration`, `m2m_card` — ver `ARCHITECTURE_PROPOSAL.md` secção
5), mas como cópia simples do export legado, com Op_PM como fonte de
verdade por omissão. Se existir um sistema de licenciamento/DGEG ou do
operador de rede que devesse ser a fonte de verdade real destes valores, a
Fase 4+ (integrações) precisa de o saber.

**Decisão necessária:** confirmar se estes valores vêm só do processo
manual da equipa (e por isso Op_PM é mesmo a fonte de verdade) ou de um
sistema externo ainda não mapeado.

**Recomendação por defeito:** manter Op_PM como fonte de verdade até haver
evidência de um sistema externo — não inventar uma integração que pode não
existir.

## Podem ser decididas mais tarde

- Fornecedor do serviço de mapas/rotas.
- Modelo específico do Claude a usar em produção (a interface já é
  agnóstica ao modelo — `Settings.claude_model`).
- Aparência final do dashboard.
- Notificações por email, Teams, ou só dentro da aplicação (`notifications`
  já modelado, sem canal de entrega definido).
- Relatórios adicionais além do semanal.
- Exportações para Excel/PDF.
- Alojamento (cloud vs. on-premises) e orçamento — necessário antes do
  primeiro deployment de staging, não antes.
- Robustez do worker/scheduler (APScheduler vs. fila dedicada) — só
  relevante quando houver volume real a justificar revisão (D-013).

## Resolvidas nesta sessão

- **"O repositório deve continuar público ou passar a privado?"** —
  Resolvida: mantém-se público, por instrução explícita do utilizador. Ver
  `docs/DECISIONS.md` D-015. A regra que passa a valer sempre: nunca dados
  reais, segredos, ou exports de produção neste repositório.
- **"Como conciliar 5 utilizadores ativos com o histórico de 8 PMs?"** —
  Resolvida arquiteturalmente: separação `Person`/`User` (D-003) — todos os
  PMs (ativos ou não) existem como `Person` para preservar o histórico;
  só até 5 têm `User` (conta de login) associada.
