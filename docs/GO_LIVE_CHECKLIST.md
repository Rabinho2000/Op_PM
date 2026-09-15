# Checklist de go-live — Op_PM

> Passagem a `production`. Pressupõe `docs/STAGING_CHECKLIST.md` e
> `docs/DATA_MIGRATION_RUNBOOK.md` já completos e assinados — este
> documento não repete os detalhes de cada um, só a sequência e as
> verificações específicas de produção. Nunca marcar uma caixa sem a
> ter verificado de facto.

## 1. Pré-requisitos

- [ ] `docs/STAGING_CHECKLIST.md` — todas as caixas marcadas, staging a
      correr de forma estável há tempo suficiente para dar confiança
      (período mínimo: `DECISÃO NECESSÁRIA`, não assumido aqui).
- [ ] `docs/DATA_MIGRATION_RUNBOOK.md` — secções 6 e 7 (critérios de
      aprovação e confirmação de preservação de dados) totalmente
      cumpridas em staging.
- [ ] Aprovação explícita de negócio para avançar (quem aprova é
      `DECISÃO NECESSÁRIA` — provavelmente o Chefe de Operações e/ou
      Administrador, mas não assumido aqui sem confirmação).

## 2. App registrations Entra ID — produção

**Nunca reutilizar as app registrations de staging em produção** — cada
ambiente tem as suas próprias, pelos mesmos motivos que as bases de dados
são separadas (isolamento de falhas, revogação independente, redirect
URIs diferentes). Repetir `docs/STAGING_CHECKLIST.md` secção 2 na íntegra,
substituindo:

- [ ] Redirect URIs pelo domínio real de produção (nunca o de staging).
- [ ] Nomes das app registrations claramente distintos (ex.
      `Op_PM API — produção`, `Op_PM Frontend — produção`) — nunca
      ambíguo sobre qual ambiente cada uma serve.
- [ ] Consentimento de administrador concedido de novo (é por app
      registration, não transferível de staging).

## 3. Variáveis de ambiente de produção

Repetir `docs/STAGING_CHECKLIST.md` secção 3, com:

- [ ] `APP_ENV=production` (não `staging`).
- [ ] `SECRET_KEY` **novo e distinto** do de staging — nunca o mesmo
      valor em dois ambientes.
- [ ] `DATABASE_URL` apontado à base de dados de **produção**, distinta
      da de staging (nunca a mesma instância/nome de base de dados).
- [ ] `ENTRA_TENANT_ID`/`ENTRA_CLIENT_ID`/`ENTRA_REQUIRED_SCOPE` da app
      registration de produção (secção 2), nunca a de staging.
- [ ] `CORS_ALLOWED_ORIGINS` com o domínio real de produção.
- [ ] Confirmar mais uma vez, manualmente, que nenhuma integração externa
      (`GRAPH_ENABLED`, `CLICKUP_ENABLED`, `FINANCIAL_ENABLED`,
      `CLAUDE_ENABLED`) está ligada, a menos que essa integração
      específica já tenha sido implementada, testada, e aprovada
      separadamente (nenhuma estava, ao escrever este documento — ver
      `docs/PLAN.md`).

## 4. Base de dados de produção

- [ ] Criar a base de dados/utilizador de produção (nunca reutilizar os
      de staging).
- [ ] Aplicar as migrações: `python -m alembic upgrade head` contra a
      base de dados de produção **vazia** (schema só, sem dados ainda).
- [ ] Confirmar backups automáticos configurados e testados (mesmo
      procedimento de `docs/STAGING_CHECKLIST.md` secção 6, repetido para
      produção — nunca assumir que "já foi testado em staging" cobre
      produção, são serviços/credenciais diferentes).

## 5. Promoção dos dados migrados (staging → produção)

Ver `docs/DATA_MIGRATION_RUNBOOK.md` secção 8 para o mecanismo. Antes de
executar:

- [ ] Backup completo da base de dados de staging (mesmo já validada —
      nunca assumir que não vai ser preciso voltar atrás).
- [ ] Backup completo da base de dados de produção (mesmo estando ainda
      só com o schema, sem dados — hábito consistente, nunca pular este
      passo "porque ainda não há nada importante").
- [ ] Executar o `pg_dump`/`pg_restore` (ou o mecanismo finalmente
      decidido — `DECISÃO NECESSÁRIA`, ver
      `docs/DATA_MIGRATION_RUNBOOK.md` secção 8) das tabelas de projetos
      e histórico já validadas em staging.
- [ ] Confirmar em produção, imediatamente a seguir: `GET /api/projects`
      (autenticado como Administrador) devolve a mesma contagem total
      confirmada em staging (`docs/DATA_MIGRATION_RUNBOOK.md` secção 6).
- [ ] Amostragem: repetir a mesma verificação de pelo menos 10 projetos
      (incluindo pelo menos um incompleto) feita em staging, agora contra
      produção — confirmar que os valores e o histórico batem
      exatamente.

## 6. Provisionamento dos 5 utilizadores em produção

- [ ] Repetir `docs/STAGING_CHECKLIST.md` secção 5 **integralmente** para
      produção — `app/cli/provision_entra_user.py` corrido contra a base
      de dados de produção, com os `Object ID` reais do Entra ID (os
      mesmos objetos de utilizador do tenant — só o `entra_object_id` é
      igual entre ambientes; a ligação em si é feita separadamente em
      cada base de dados).
- [ ] Confirmar que **só** os 5 utilizadores reais existem como `User`
      ativo em produção — nenhum utilizador de teste/sintético de
      staging foi copiado (a promoção da secção 5 só traz `projects`/
      histórico, nunca `users`, de propósito).

## 7. Testes finais em produção

Repetir `docs/STAGING_CHECKLIST.md` secção 7 (login real, permissões por
perfil, auditoria, CORS) integralmente contra produção — nunca assumir
que "já passou em staging" é suficiente, os dois ambientes têm
configuração e credenciais distintas por desenho.

- [ ] Teste de login real com pelo menos 2 dos 5 utilizadores (idealmente
      todos, se praticável).
- [ ] Teste de permissões por perfil (pelo menos um caso permitido e um
      negado por papel).
- [ ] Teste de auditoria: uma edição de projeto de teste gera
      `project_history` correta; nenhuma entrada inesperada em
      `auth_audit_log`.
- [ ] `GET /health` responde `200`, `app_env='production'`,
      `database_dialect='postgresql'`.

## 8. Procedimento de rollback

- [ ] **Se um problema for descoberto antes de qualquer utilizador real
      ter usado produção:** reverter para o estado anterior (schema vazio
      + nenhum dado), corrigir o problema em staging primeiro, repetir a
      partir da secção 4.
- [ ] **Se um problema for descoberto depois de utilizadores reais já
      terem usado produção:**
  - Nenhuma escrita em `projects` acontece fora de `PATCH
    /api/projects/{id}` (gera sempre `project_history`) — reverter um
    valor errado é sempre possível manualmente, comparando com
    `project_history`, mesmo sem um botão de "desfazer" dedicado.
  - Se o problema for estrutural (schema, configuração): `python -m
    alembic downgrade` para a revisão anterior, ou corrigir a variável de
    ambiente e reiniciar — nunca aplicar uma correção não testada
    primeiro em staging, salvo emergência documentada.
  - Restaurar o backup da secção 4/5 como último recurso, se os dados
    ficarem num estado que os passos acima não resolvam — aceitar a
    perda de qualquer edição feita entre o backup e a restauração
    (comunicar isto aos utilizadores antes de restaurar, nunca depois).
- [ ] Registar qualquer rollback executado (o quê, quando, porquê) fora
      deste repositório (ex. num registo de incidentes) — nunca só de
      memória.

## 9. Confirmação final

- [ ] Nenhum dado sintético/de teste chegou a produção (secção 6).
- [ ] Nenhuma integração externa real foi ligada além do que foi
      explicitamente decidido e testado (secção 3).
- [ ] Os dados antigos (295 projetos, 8 PMs históricos) estão preservados
      e verificados em produção (secção 5) — mesmas verificações feitas
      em `docs/DATA_MIGRATION_RUNBOOK.md` secção 7, repetidas aqui contra
      produção.
- [ ] Backups de produção configurados e testados (secção 4).
- [ ] Todos os testes da secção 7 passam.
- [ ] Aprovação de negócio registada (secção 1).
