# Backup e restauro

Runbook do backup local da instância Op_PM (Docker Compose, SQLite) e do respetivo ensaio de restauro. Resolve a parte local do achado A9 de [`ANALISE_OP_PM.md`](ANALISE_OP_PM.md); o que falta está na secção 7.

> Os scripts de backup e de ensaio vivem no servidor, fora deste repositório (têm caminhos e nomes de volume específicos da instância). Este documento descreve o comportamento e os passos genéricos. Marcadores como `<backup-dir>` e `<volume-de-dados>` substituem-se pelos valores da instância.

## 1. O que é guardado

Cada execução produz, com o mesmo carimbo temporal `<AAAAMMDD_HHMMSS>`, estes artefactos em `<backup-dir>`:

| Artefacto | Conteúdo |
|---|---|
| `op_pm_auto_<carimbo>.db` | Base de dados operacional (SQLite) |
| `material_prices_auto_<carimbo>.db` | Base de dados de preços de materiais (só se existir) |
| `op_pm_files_auto_<carimbo>.tar.gz` | Todos os ficheiros do volume de dados, exceto bases de dados (`*.db*`) e ficheiros efémeros (`*.heartbeat`): `project_photos/`, `inventory/` (documentos), `outbox/` (se existir) e quaisquer outros diretórios |
| `op_pm_manifest_auto_<carimbo>.json` | Manifesto: tabelas e número de linhas de cada BD, e número de ficheiros e bytes por diretório |
| `op_pm_sha256_auto_<carimbo>.txt` | `sha256` da BD, do tar.gz e do manifesto |
| `LAST_OK` | Carimbo do último backup concluído com sucesso |

Bases de dados:

- A cópia usa a API de backup do SQLite sobre a BD aberta em modo só de leitura, por isso é consistente com o modo WAL sem parar a aplicação.
- Cada cópia passa por `PRAGMA integrity_check`; se não devolver `ok`, o backup falha.

Ficheiros:

- O tar é feito por um container descartável sem rede, com o volume montado só em leitura, e escrito para o disco do anfitrião com o dono e as permissões do utilizador.
- Os ficheiros de backup ficam com permissões `0600` e a diretoria com `0700`.

## 2. Frequência e retenção

- Frequência: 4 vezes por dia (00:15, 06:15, 12:15 e 18:15), por um timer systemd de utilizador.
- Retenção: 14 dias, para todos os artefactos (BD, ficheiros, manifesto e sha256). Configurável por variável de ambiente.
- Um backup manual deve ser feito antes de qualquer `docker compose up` que inclua migrações novas.
- Espaço: cada execução ocupa aproximadamente o tamanho da BD mais o do tar.gz dos ficheiros; multiplicar por 4 × 14 para estimar o total.

## 3. Monitorização

- O script sai com código diferente de zero em qualquer falha (container indisponível, `integrity_check` falhado, `tar` falhado, `sha256` que não confere). Como o serviço systemd é `oneshot`, a falha aparece em `systemctl --user status <serviço-de-backup>` e em `systemctl --user --failed`.
- `LAST_OK` só avança depois de todos os artefactos estarem escritos e verificados. Um alarme simples: falhar se `LAST_OK` tiver mais de 8 horas.
- Dois backups nunca correm em simultâneo (há um bloqueio por `flock`).

## 4. Restaurar passo a passo

Pressupostos: Docker Compose, volume `<volume-de-dados>` montado em `/app/data`, e a app a correr com o utilizador de uid `<uid-app>` (ver o `Dockerfile` do backend). Ajustar se o contexto for outro.

1. **Escolher o backup** e verificar a integridade:

   ```bash
   cd <backup-dir>
   sha256sum -c op_pm_sha256_auto_<carimbo>.txt
   ```

   Se falhar, usar um backup anterior.

2. **Parar o backend e o scheduler** (para não haver escritas durante o restauro). O frontend pode ficar.

   ```bash
   docker compose -p <projeto> -f <compose.yml> stop backend scheduler
   ```

3. **Guardar o estado atual** do volume, se ainda existir, antes de o substituir (por exemplo `docker run --rm -v <volume-de-dados>:/data:ro ... tar czf - /data > pre-restauro.tar.gz`).

4. **Restaurar a BD.** Copiar o `.db` para o volume com o nome original da BD e **apagar os `-wal` e `-shm` antigos**, que pertencem à BD anterior:

   ```bash
   docker run --rm -v <volume-de-dados>:/data -v <backup-dir>:/bk:ro <imagem-alpine> sh -c '
     rm -f /data/op_pm_demo.db-wal /data/op_pm_demo.db-shm &&
     cp /bk/op_pm_auto_<carimbo>.db /data/op_pm_demo.db'
   ```

   Se existir `material_prices_auto_<carimbo>.db`, fazer o mesmo para `material_prices.db`.

5. **Restaurar os ficheiros** (substitui o conteúdo atual de `project_photos/`, `inventory/`, `outbox/`, etc.):

   ```bash
   docker run --rm -v <volume-de-dados>:/data -v <backup-dir>:/bk:ro <imagem-alpine> sh -c '
     tar -xzf /bk/op_pm_files_auto_<carimbo>.tar.gz -C /data --no-same-owner &&
     chown -R <uid-app>:<uid-app> /data'
   ```

6. **Verificar o esquema.** Com a imagem do backend e sem rede, `python -m alembic current` deve indicar a revisão esperada. Se o backup for anterior a migrações já aplicadas, correr `alembic upgrade head` (de preferência depois de um novo backup).

7. **Arrancar** o backend e o scheduler e confirmar `/health`, o login e a abertura de um projeto com fotos.

8. **Comparar com o manifesto**: o número de linhas por tabela e o de ficheiros por diretório devem coincidir com `op_pm_manifest_auto_<carimbo>.json`. O ensaio (secção 5) automatiza esta comparação.

## 5. Ensaio de restauro

O script de ensaio faz tudo isto sem tocar na instância em execução:

1. escolhe o backup mais recente (ou o carimbo indicado) e verifica os `sha256`;
2. restaura a BD e os ficheiros para um diretório temporário e para um volume Docker descartável;
3. arranca a imagem do backend sem rede, com `APP_ENV=local`, `AUTH_ENABLED=false` e `DATABASE_URL` a apontar para a cópia;
4. corre `alembic current` e um verificador Python que compara as contagens por tabela com o manifesto, corre `integrity_check` e compara o número de ficheiros e bytes por diretório com o manifesto;
5. apaga o volume e o diretório temporário, mesmo em caso de erro.

Sai com código 0 só se tudo coincidir. Não imprime dados, apenas contagens.

Cadência recomendada: um ensaio trimestral, e sempre depois de alterar o script de backup, o esquema do volume ou a versão do SQLite/Python da imagem. Registar a data e o resultado.

## 6. Testes de falha já feitos

- Artefacto corrompido (um byte alterado no tar.gz): o ensaio falha na verificação de `sha256`.
- Manifesto adulterado com `sha256` recalculado: o ensaio falha na comparação de contagens.
- Container inexistente: o backup sai com código 1, o serviço systemd fica `failed` e o `LAST_OK` não avança.

## 7. O que falta

- **Cópia off-site cifrada.** Por decisão atual os backups são só locais, no mesmo anfitrião da instância: perder o disco ou o servidor perde os dados e os backups. É o maior risco em aberto de A9.
- **Alerta ativo** quando o serviço falha ou o `LAST_OK` envelhece (hoje só se vê consultando o systemd).
- **PostgreSQL.** Quando a produção migrar (achado A8), a função `backup_database` do script, a única que conhece o motor, passa a usar `pg_dump` (formato custom) e o ensaio passa a restaurar para um PostgreSQL descartável com `pg_restore`. O backup dos ficheiros e o manifesto mantêm-se. A secção 4 muda nos passos 4 e 6.
- **Cifra em repouso** dos backups locais (contêm dados reais de clientes; hoje dependem das permissões do sistema de ficheiros).
