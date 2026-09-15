# Bootstrap de staging — utilizadores reais (D-050)

> Procedimento executável para quem vai criar os `Person`/`User`/
> `UserRole` reais em staging usando `python -m app.cli.provision_staging`.
> Não exige conhecimento de código — só seguir os passos por ordem.
> Complementa `docs/STAGING_RUNBOOK.md` secção 9 (onde este comando é
> chamado no procedimento completo) e `docs/STAGING_CHECKLIST.md`
> secções 4/5 (sign-off).
>
> Resolve a pergunta "Quem cria `Person`/`User`/`UserRole` reais em
> staging?" em `docs/OPEN_QUESTIONS.md` (secção "Resolvidas"): antes
> deste comando, os registos tinham de ser criados manualmente por
> Python/SQL.

## O que este comando faz e não faz

Faz:

- Cria (ou reutiliza, se já existirem) o catálogo de papéis/permissões
  (`administrador`, `chefe_operacoes`, `project_manager`, `comercial`,
  `financeiro`).
- Cria ou atualiza exatamente os utilizadores listados no ficheiro que
  lhe fornecer — nome, email, papel, e opcionalmente o Object ID do
  Microsoft Entra ID.
- É seguro correr mais do que uma vez com o mesmo ficheiro — a segunda
  vez não duplica nada nem falha.
- Regista tudo em auditoria (`auth_audit_log`, consultável diretamente
  na base de dados), sempre com o `user_id`/`person_id` reais de quem
  executou o comando.

Nunca faz:

- **Nunca corre fora de `APP_ENV=staging`** — recusa-se explicitamente em
  `production`, `local` e `test` com uma mensagem clara. Não há forma de
  contornar isto por flag nenhuma.
- **Nunca aceita `--actor-email` sem verificar quem é** — tem de
  corresponder a um `User` ativo com a permissão `admin.manage_users`
  (ou seja, já um administrador). Um utilizador comum nunca consegue
  criar nem promover ninguém — nem a si próprio, nem a outra pessoa a
  administrador — através deste comando. Ver "Primeira execução" abaixo
  para a única exceção (a base de dados ainda não ter nenhum
  utilizador).
- Nunca cria projetos, tarefas, ou qualquer outro dado além de
  utilizadores/papéis.
- Nunca guarda uma password (a autenticação é sempre feita pelo
  Microsoft Entra ID — ver `docs/STAGING_RUNBOOK.md` secção 2).
- Nunca remove um utilizador ou um papel que já exista e não esteja no
  ficheiro — só acrescenta/atualiza.
- Nunca escreve nada na base de dados (nem o catálogo) se o ficheiro for
  inválido ou o `--actor-email` não for autorizado.
- Nunca escreve nada na base de dados sem a flag `--confirm`.

## Primeira execução (arranque a frio, sem nenhum administrador ainda)

Numa base de dados de staging completamente vazia (schema criado pelo
`alembic upgrade head`, mas sem nenhum `Person`/`User` ainda), não existe
nenhum administrador para autorizar a primeira execução. Este é o mesmo
problema do "primeiro administrador" de qualquer sistema novo — o
comando trata-o de forma explícita: **só quando a base de dados não tem
nenhum `User`**, a verificação de `--actor-email` é dispensada (o email
que fornecer fica só registado em auditoria como quem executou, sem ser
verificado — porque não há ainda nenhum utilizador contra o qual
verificar). Assim que essa primeira execução criar o primeiro
utilizador, **todas as execuções seguintes voltam a exigir um
`--actor-email` que já seja administrador** — não há uma segunda
oportunidade de contornar a verificação.

Por isso, a primeira vez que correr este comando contra uma base de
dados de staging nova, garanta que o ficheiro inclui pelo menos um
utilizador com `"role": "administrador"` — caso contrário, ninguém
consegue correr o comando outra vez sem editar a base de dados
diretamente.

## Passo 1 — Preparar o ficheiro de utilizadores (fora do repositório)

Criar um ficheiro `.json` **num caminho fora desta pasta do repositório**
(recomendado — por exemplo no seu ambiente de trabalho pessoal, nunca
dentro de `Op_PM/`) com esta forma exata:

```json
{
  "users": [
    {
      "display_name": "Nome Completo Real",
      "email": "nome.real@empresa.pt",
      "role": "administrador"
    },
    {
      "display_name": "Outro Nome Real",
      "email": "outro.real@empresa.pt",
      "role": "chefe_operacoes"
    }
  ]
}
```

- `role` tem de ser exatamente um destes textos: `administrador`,
  `chefe_operacoes`, `project_manager`, `comercial`, `financeiro`.
- `entra_object_id` é **opcional** — pode incluir já o Object ID do
  Azure Portal para cada pessoa (ver `docs/STAGING_RUNBOOK.md` secção
  9.2 para onde o encontrar) ou deixar de fora e associá-lo mais tarde.
- Cada email só pode aparecer uma vez no ficheiro.
- **Se colocar este ficheiro dentro da pasta do repositório por engano**
  (mesmo temporariamente), o comando recusa-se a lê-lo a menos que o
  caminho esteja coberto pelo `.gitignore` (ex. `backend/data/`) — é uma
  proteção deliberada, não um bug.

## Passo 2 — Pré-visualizar (nunca escreve nada)

A partir de `backend/`, com `APP_ENV=staging` e `DATABASE_URL` já a
apontar para a base de dados de staging (mesmas variáveis usadas no
resto do runbook) — o comando recusa-se em qualquer outro `APP_ENV`:

```bash
python -m app.cli.provision_staging \
  --file /caminho/fora/do/repo/utilizadores_staging.json \
  --actor-email <o-seu-email> \
  --dry-run
```

`<o-seu-email>` tem de ser o email de um `User` ativo que já seja
administrador nesta base de dados — a menos que esta seja mesmo a
primeira execução de sempre (ver "Primeira execução" acima), o comando
recusa-se com uma mensagem clara se o email for desconhecido, o
utilizador estiver inativo, ou não tiver a permissão
`admin.manage_users`.

Confirme o resumo impresso (`people_created`, `users_created`,
`roles_assigned`, `entra_object_ids_linked`) antes de continuar — nada
foi escrito ainda, mesmo sem `--dry-run` explícito: sem `--confirm`, o
comando comporta-se sempre assim.

## Passo 3 — Aplicar a sério

```bash
python -m app.cli.provision_staging \
  --file /caminho/fora/do/repo/utilizadores_staging.json \
  --actor-email <o-seu-email> \
  --confirm
```

Confirme a saída `OK: alterações escritas na base de dados.` e o resumo.

## Passo 4 — Confirmar em auditoria

```sql
SELECT event, detail, occurred_at FROM auth_audit_log ORDER BY occurred_at DESC LIMIT 20;
```

Deve ver uma entrada `admin_bootstrap_user` por cada pessoa criada/
atualizada, e `admin_provision_link` para cada uma com
`entra_object_id` já incluído no ficheiro.

## Passo 5 — Repetir com segurança

Correr o mesmo comando outra vez (ex. para confirmar idempotência, ou
porque o ficheiro foi atualizado com mais uma pessoa) é seguro: pessoas
já criadas aparecem como "sem alterações" no resumo, sem duplicar nada.

## Se o Object ID do Entra ID ainda não estiver disponível

Deixe `entra_object_id` fora dessa entrada no ficheiro — a pessoa fica
criada e com o papel atribuído, só sem login funcional ainda. Quando o
Object ID estiver disponível, ligue-o com `provision_entra_user.py`
(`docs/STAGING_RUNBOOK.md` secção 9.2) ou volte a correr
`provision_staging` com o ficheiro atualizado a incluir esse campo.

## Bloqueios externos (o que precisa de fornecer antes deste passo)

1. A base de dados de staging já criada e acessível (`DATABASE_URL`) —
   ver `docs/STAGING_RUNBOOK.md` secções 3/4.
2. Os nomes/emails reais das pessoas a provisionar.
3. Opcionalmente, os Object IDs do Azure Portal para cada uma (secção
   9.2 do runbook) — pode ser feito depois, separadamente.

Nada mais é necessário para este passo específico — não depende do
alojamento nem do domínio de staging estarem decididos.
