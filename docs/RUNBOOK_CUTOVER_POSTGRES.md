# Runbook: migrar uma instância Op_PM de SQLite para PostgreSQL (produção)

> Procedimento genérico (sem IDs, hostnames nem caminhos reais). Cada instância
> mantém a sua versão concreta, com os comandos exatos, fora do Git.
> Resolve A8 (SQLite com dois processos a escrever) e, junto com
> `docker-compose.production.example.yml`, a parte de infraestrutura de C1/A7
> (`APP_ENV=production`, segredos por ficheiro, sem seed).

Componentes:

| Peça | Onde |
|---|---|
| Composição de produção (PostgreSQL, `migrate`, backend, scheduler, frontend) | `docker-compose.production.example.yml` |
| Cópia SQLite → PostgreSQL com verificação | `python -m app.cli.migrate_sqlite_to_postgres` |
| Ligação de utilizadores Entra | `python -m app.cli.provision_entra_user` ou janela de transição com `ENTRA_JIT_LINK_BY_EMAIL=true` |
| Segredos por ficheiro | `SECRET_KEY_FILE`, `DATABASE_URL_FILE`, `DATABASE_PASSWORD_FILE` (`app/config.py`) |

## 1. Preparação (sem paragem)

1. **Código**: a imagem do backend tem de incluir a CLI de cópia e o suporte de segredos por ficheiro (branch que contém `app/cli/migrate_sqlite_to_postgres.py`).
2. **Segredos** numa pasta `0700` fora do Git (`$OP_PM_SECRETS_DIR`), ficheiros `0600`, uma linha cada, gerados sem os imprimir:
   - `oppm_db_password`: `python3 -c "import secrets;print(secrets.token_hex(32))"`;
   - `oppm_app_secret_key`: `python3 -c "import secrets;print(secrets.token_urlsafe(64))"`;
   - `oppm_secrets.key`: a chave Fernet que **já existe** (não gerar outra: as credenciais de portais guardadas deixariam de abrir).
   - O utilizador `app` do contentor (uid 999) tem de os ler: `setfacl -m u:999:r <ficheiro>` (sem alterar o dono).
3. **Compose concreto** a partir do exemplo, fora do Git: mesmo nome de projeto, os mesmos volumes de ficheiros (com `name:` explícito) e um volume novo para a BD.
4. `docker compose -f <compose> config --quiet` tem de passar.
5. **Ensaio** (obrigatório, com recursos de nome próprio, por exemplo `-p <instancia>-rehearsal`, sem portas públicas): PostgreSQL novo → `migrate` → cópia a partir de um backup real → `--verify-only` → backend em `APP_ENV=production` → testes de fumo. Apagar tudo no fim.
6. **Utilizadores Entra** (secção 5): decidir a solução antes da janela.
7. Avisar os utilizadores da janela (a paragem técnica é de poucos minutos; reservar 15).
8. Pré-construir as imagens (`build backend migrate scheduler`) para a paragem não incluir o build.

## 2. Cutover (janela)

Cada passo só avança se o anterior correu bem. Qualquer falha antes do passo 9 = rollback (secção 4); a origem SQLite nunca é alterada.

1. **Aviso** aos utilizadores.
2. **Backup** (BD + ficheiros) e anotar o nome do ficheiro e as contagens de projetos/utilizadores.
3. **Parar backend e scheduler** (o frontend pode ficar a mostrar erro). A partir daqui a BD SQLite deixa de receber escritas.
4. **Backup final** (agora consistente com o estado parado) e copiar o `.db` para uma pasta de trabalho `0700`. Confirmar `PRAGMA integrity_check = ok` e que não existe `-wal` com dados ao lado.
5. **Arrancar o PostgreSQL** e esperar pelo estado saudável (`up -d --wait postgres`).
6. **`migrate`** (`run --rm migrate`): cria o esquema com Alembic (nunca `create_all`).
7. **Copiar e verificar**, com o `.db` montado só em leitura no contentor do `migrate`:
   - primeiro `--dry-run`: tem de terminar com `Verificação: OK` e **sem** linhas rejeitadas;
   - depois a cópia real (mesmo comando sem `--dry-run`). Tudo corre numa só transação: se a verificação falhar, nada fica gravado.
8. **Trocar o compose**: guardar o antigo sob outro nome (é o rollback) e pôr o de produção no lugar.
9. **`up -d --wait backend scheduler frontend`**.
10. **Testes de fumo**: `/health` (`app_env=production`, `database_dialect=postgresql`, `demo_mode=false`); `/me` sem token → 401; `/docs` → 404; `run-due --dry-run` e `health` do scheduler; contagens de projetos e utilizadores iguais às do passo 2; um login real de um utilizador.
11. **Backup depois do cutover**: ver secção 6. Até lá, o backup antigo continua a copiar o SQLite abandonado.

### Ferramenta de cópia: o que faz e o que recusa

- Não cria o esquema: tem de estar no destino (passo 6) e as revisões Alembic da origem e do destino têm de coincidir com o `head` do código.
- Recusa um destino com dados (exceto as linhas de referência semeadas pelas migrações, que substitui). `--replace-existing-data` apaga tudo e só se usa de forma deliberada.
- Antes de gravar, reporta por (tabela, coluna, motivo, contagem), sem conteúdo, o que o PostgreSQL rejeitaria e o SQLite aceitou: texto acima do `VARCHAR(n)`, `NUL` em texto, booleanos fora de 0/1, UUID/JSON/datas inválidos, casas decimais a mais em `Numeric`, chaves estrangeiras órfãs. Com `--dry-run` conta também o que só o motor avalia (CHECK, UNIQUE).
- Verificação: contagem e checksum por tabela sobre colunas normalizadas (UUID, JSON, Numeric, datas em UTC), feita dentro da transação antes do `COMMIT`.
- `--verify-only` repete a comparação mais tarde, sem escrever.
- Texto de datas sem fuso é lido como UTC (é como a aplicação grava).

## 3. Critérios de go / no-go

**Go (antes de parar o serviço)**: ensaio recente e verde na mesma versão do código; imagens construídas; segredos presentes e legíveis pelo uid 999; backup recente com `integrity_check = ok`; decisão tomada sobre os utilizadores Entra; janela comunicada.

**No-go / abortar e fazer rollback** se, durante a janela: o `migrate` falha; o `--dry-run` reporta linhas rejeitadas ou divergências; o backend não fica saudável em 2 minutos; `/health` não indica PostgreSQL e `production`; `/me` sem token não dá 401 ou `/docs` não dá 404; as contagens de projetos/utilizadores divergem das do backup; ninguém consegue entrar com o login real.

## 4. Rollback

A BD SQLite e o volume de ficheiros ficam intactos durante todo o procedimento. Para voltar:

1. Parar backend, scheduler e frontend do compose novo.
2. Repor o compose antigo (SQLite, `APP_ENV=local`) e fazer `up -d --remove-orphans` (remove o contentor do PostgreSQL; o volume `pgdata` fica).
3. Confirmar `/health` com `database_dialect=sqlite`.

Atenção: tudo o que for gravado no PostgreSQL depois do cutover **não volta** ao SQLite. Por isso o rollback é fácil na primeira hora e passa a ser uma perda de dados depois de os utilizadores trabalharem. Nesse caso, decidir caso a caso (por exemplo, corrigir para a frente com um backup do PostgreSQL).

## 5. Utilizadores Entra

Com `APP_ENV=production` a ligação automática por email (JIT) fica desligada: um utilizador ativo **sem** `entra_object_id` deixa de conseguir entrar. Contar antes do cutover:

```sql
SELECT count(*) FILTER (WHERE is_active AND entra_object_id IS NULL) AS sem_ligacao,
       count(*) FILTER (WHERE is_active AND entra_object_id IS NOT NULL) AS ligados
FROM users;
```

Duas soluções (escolher uma):

- **A. Janela de transição**: definir `ENTRA_JIT_LINK_BY_EMAIL=true` de forma explícita no compose durante alguns dias. Cada utilizador sem ligação liga-se no primeiro login (o email do token tem de coincidir com o do utilizador; fica registado em auditoria como `jit_link_by_email`). Quando `sem_ligacao` chegar a zero (ou os restantes forem contas que já não vão entrar), remover a variável e fazer `up -d backend`. Requer que o tenant seja de confiança (single-tenant, `tid` validado).
- **B. Provisionamento administrativo**: `python -m app.cli.provision_entra_user --actor-email ... --user-email ... --entra-object-id ... --confirm` para cada utilizador, com o `oid` obtido no Entra. Sem janela de risco, mais trabalho manual.

## 6. Backup depois do cutover

- O backup passa a ser `pg_dump --format=custom` (consistente, sem parar nada), em vez de `sqlite.backup`. Os ficheiros do volume (fotos, documentos, outbox) continuam a ir no `tar`; o `*.db*` excluído já deixa de fora o SQLite antigo.
- Se existir uma BD de preços SQLite separada, continua a precisar do `sqlite.backup`.
- Verificar cada dump com `pg_restore --list` e, periodicamente, restaurar num PostgreSQL descartável e comparar contagens:

  ```bash
  pg_restore --no-owner -d <base_vazia> <dump>
  ```
- Reter o SQLite antigo e o último backup SQLite até o PostgreSQL ter, pelo menos, alguns dias de dumps verificados.

## 7. Depois

- Remover `ENTRA_JIT_LINK_BY_EMAIL` quando todos estiverem ligados.
- Passar o volume do SQLite antigo a só-arquivo (não apagar sem decisão explícita).
- Atualizar a documentação do servidor (compose, backup, portas).
