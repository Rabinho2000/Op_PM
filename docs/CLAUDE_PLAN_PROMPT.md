# Prompt para o Claude — plano do projeto Op_PM

Copiar o texto abaixo para o Claude Code, a partir da raiz do projeto existente.

```text
Atua como arquiteto sénior de software, product manager técnico e especialista em migração de sistemas operacionais.

Quero que analises este repositório existente e prepares um plano completo para transformar a aplicação atual numa webapp profissional com login, base de dados, permissões, integrações e funcionalidades de IA.

Não implementes código nesta fase. Primeiro analisa, identifica riscos, faz o plano e apresenta as perguntas bloqueantes. Não faças commits, push, alterações externas, envio de emails, criação de eventos ou alterações de dados reais sem autorização explícita.

## Primeiro passo

Executa `pwd`, lista os ficheiros e lê `AGENTS.md`, se existir. Lê também toda a documentação em `.planning/codebase/`, especialmente `ARCHITECTURE.md`, `CONCERNS.md`, `STACK.md`, `INTEGRATIONS.md` e `TESTING.md`.

Inspeciona o código real antes de fazer afirmações. Não reveles tokens, passwords, conteúdos de `.env`, `.secrets` ou dados pessoais.

## Contexto do produto

O sistema atual tem uma aplicação HTML/JavaScript, scripts Python, JSON partilhado e uma aplicação desktop para emails semanais. A nova direção é uma webapp com login real, até cinco utilizadores, sem requisito offline, permissões por perfil, histórico completo e integração com ClickUp.

Perfis previstos:

- Administrador
- Chefe de operações
- Project manager
- Comercial
- Financeiro

## Funcionalidades a avaliar

- dashboard semanal com estatísticas, trabalhos a fazer e vista comercial;
- férias e aniversários;
- planeamento semanal e visitas técnicas;
- propostas de datas ao cliente por email;
- conciliação e otimização de várias deslocações;
- mapa de instalações, fornecedores e recolhas;
- stock, stock mínimo, reservas e alertas;
- previsão de material necessário pelas obras futuras;
- pedidos a fornecedores e emails preparados por IA;
- orçamentos, adjudicações e envio ao Financial;
- custos estimados, adjudicados, reais e custos de deslocação;
- biblioteca de manuais e datasheets na Drive/OneDrive;
- pesquisa documental com Claude;
- formulários de visita técnica e comissionamento;
- anexos e fotografias obrigatórias;
- relatório interno semanal;
- integração remota com Claude através de API ou MCP seguro.

## Regras para a IA

O Claude pode propor, resumir, pesquisar e preparar rascunhos. Não deve ser a fonte de verdade dos custos, stock, calendário ou estado dos projetos.

Define ferramentas server-side com schemas explícitos para ações como:

- consultar disponibilidade;
- calcular deslocações;
- propor horários;
- preparar email;
- pesquisar documentos;
- analisar material;
- gerar relatório.

Enviar emails, criar eventos, adjudicar compras e alterar custos deve exigir aprovação humana e produzir auditoria.

A otimização das rotas deve usar regras determinísticas ou um solver próprio. O Claude deve interpretar requisitos e explicar opções, mas não substituir o cálculo.

## Arquitetura a comparar

Compara:

1. manter a aplicação local com JSON;
2. webapp com API e base de dados;
3. webapp integrada com Microsoft 365, Outlook, calendário e OneDrive;
4. solução híbrida com base operacional e Drive como arquivo documental.

Recomenda uma opção e justifica-a para cinco utilizadores e sem modo offline.

Avalia frontend, backend, base de dados, autenticação, permissões, ClickUp, Microsoft Graph, Outlook clássico, Outlook novo, OneDrive/SharePoint, Financial, mapas, rotas, Claude, MCP, alojamento, backups e auditoria.

## Dados e migração

Define:

- IDs estáveis de projeto e relação com ClickUp;
- fonte de verdade por campo;
- modelo de dados;
- histórico e auditoria;
- estratégia para conflitos;
- migração dos JSON atuais;
- validação e qualidade dos dados;
- fixtures fictícias para testes;
- separação entre código, dados de produção e documentos.

## Segurança

- Nunca ler ou imprimir secrets.
- Nunca versionar `.env`, `.secrets`, dados reais ou backups.
- Não apagar nem sobrescrever alterações existentes.
- Não usar comandos destrutivos ou force push.
- Não criar recursos externos sem aprovação.
- Recomendar repositório GitHub privado e limpo para o código.
- Assinalar tudo o que não possa ser confirmado.

## Entregáveis

Produz um plano em português de Portugal com:

1. resumo executivo;
2. estado atual;
3. funcionalidades reaproveitáveis;
4. matriz de viabilidade;
5. arquitetura recomendada;
6. modelo de dados;
7. fonte de verdade por campo;
8. permissões por perfil;
9. plano de integrações;
10. plano de IA e MCP;
11. plano de migração;
12. segurança e privacidade;
13. roadmap por fases;
14. dependências;
15. critérios de aceitação;
16. testes;
17. deployment e GitHub;
18. riscos;
19. perguntas bloqueantes;
20. primeiro MVP recomendado.

Para cada fase indica objetivo, entidades, integrações, testes, riscos, rollback e critérios objetivos de conclusão.

Não inventes respostas. Usa `DECISÃO NECESSÁRIA` para informação em falta.

Se estiveres a trabalhar no Claude Code, podes criar apenas:

- `docs/PLAN.md`
- `docs/OPEN_QUESTIONS.md`
- `docs/ARCHITECTURE_PROPOSAL.md`

Não alteres código de produção nem faças commit até o plano ser revisto e aprovado.
```
