"""Bootstrap idempotente do catálogo de papéis/permissões e dos utilizadores
reais de staging — comando administrativo controlado, nunca um endpoint HTTP
(mesmo desenho de `app/cli/ingest_staging.py` e `app/cli/provision_entra_user.py`,
ver docs/DECISIONS.md D-034/D-037/D-050).

Resolve o vazio deixado por `docs/DECISIONS.md` D-049 e
`docs/OPEN_QUESTIONS.md` (pergunta "Quem cria `Person`/`User`/`UserRole`
reais em staging?", secção "Resolvidas"): até agora, criar `Person`/`User`/
`UserRole` reais em staging exigia Python/SQL manual (documentado em
`docs/STAGING_RUNBOOK.md` secção 9.1), porque `app.migration.seed_dev` está
deliberadamente bloqueado fora de `local`/`test` (D-049) — esse seed cria
dados sintéticos, nunca aceitável em staging.

**Duas barreiras de segurança, sempre aplicadas (D-050, revisão de
hardening):**

1. **Staging-only.** A CLI real (`main()`, o que corre
   `python -m app.cli.provision_staging`) recusa-se a fazer seja o que for
   fora de `APP_ENV=staging` — nunca `production` (provisionamento real de
   produção exige um processo próprio, fora do âmbito deste comando), nunca
   `local` (usar `app.migration.seed_dev`, que cria dados sintéticos), nunca
   `test` (os testes automatizados chamam `bootstrap_staging_users`
   diretamente, nunca via CLI). Ver `assert_staging_environment`. A lógica
   interna (`bootstrap_staging_users`) continua testável isoladamente em
   SQLite/`test` — só o `main()` tem esta barreira, de propósito, para os
   testes poderem exercer o núcleo sem precisar de simular `APP_ENV=staging`.
2. **`--actor-email` tem de ser um administrador real, ativo e autorizado.**
   Nunca um texto livre gravado às cegas em auditoria: `main()` resolve o
   email a um `User` ativo já existente e confirma que tem a permissão
   `admin.manage_users` (`app/security/catalog.py` — hoje só o papel
   `administrador` tem esta permissão) antes de escrever seja o que for.
   Email desconhecido, utilizador inativo, ou utilizador ativo sem essa
   permissão são todos recusados — **nunca um utilizador comum consegue
   criar/promover outro utilizador (incluindo administradores) através
   deste comando.** Exceção deliberada e estreita: se a base de dados não
   tiver **nenhum** `User` ainda (arranque a frio, mesmo problema do "primeiro
   administrador" de qualquer sistema novo), a verificação de autorização é
   dispensada só nesse caso específico — não existe nenhum "utilizador
   comum" que pudesse abusar disto, porque não existe nenhum utilizador de
   todo. Assim que o primeiro `User` for criado, todas as corridas
   seguintes voltam a exigir um `--actor-email` autorizado. Ver
   `_resolve_and_authorize_actor`. O `person_id`/`user_id` reais do ator
   (nunca só o texto do email fornecido) ficam gravados em
   `AuthAuditLog.detail`.

**O que este comando faz, sempre a partir de um ficheiro JSON externo ao
repositório** (nunca inventa nem lê dados de outro sítio):

- Semeia o catálogo de `Role`/`Permission`/`RolePermission`
  (`app.migration.seed_dev.seed_catalog`, reutilizado tal como está — já é
  seguro em qualquer ambiente, só cria o catálogo fixo de
  `app/security/catalog.py`, nunca pessoas/projetos sintéticos).
- Cria ou atualiza exatamente os `Person`/`User`/`UserRole` indicados no
  ficheiro — nunca inventa utilizadores adicionais, nunca cria
  `Project`/`Task`/qualquer outro dado sintético.
- Associa `User.entra_object_id`, se fornecido no ficheiro — mesma regra de
  `link_user_to_entra_object_id` (nunca reatribui, nunca reutiliza o mesmo
  Object ID para duas pessoas), mas idempotente: repetir com o mesmo valor
  já associado é um no-op, não um erro (ao contrário de
  `provision_entra_user.py`, pensado para correr uma vez por utilizador).
  `entra_object_id` é opcional por utilizador — pode ficar de fora do
  ficheiro e ser associado mais tarde via `provision_entra_user.py`.
- **Nunca guarda password nenhuma** (o modelo `User` não tem esse campo —
  autenticação é sempre delegada ao Microsoft Entra ID).
- Idempotente: correr duas vezes com o mesmo ficheiro produz o mesmo estado
  final, sem duplicar registos nem falhar na segunda corrida.
- Sempre auditado em `AuthAuditLog`: evento `admin_bootstrap_user` para
  cada `Person`/`User`/`UserRole` criado ou atualizado, e
  `admin_provision_link` (mesmo nome usado por `provision_entra_user.py`)
  quando associa um `entra_object_id` — sempre com o ator real (verificado)
  no detalhe, nunca só um texto não confirmado.

**O que este comando nunca faz:** nunca remove um papel já atribuído a um
utilizador que não esteja no ficheiro (edição é sempre aditiva); nunca
desativa um utilizador que deixe de aparecer no ficheiro (desativação é uma
decisão administrativa separada, fora do âmbito deste comando); nunca cria
projetos — a ingestão de projetos é sempre via `app.cli.ingest_staging`
(D-037); nunca escreve nada (nem o catálogo) se a validação do payload ou a
autorização do ator falhar primeiro.

Utilização (só em `APP_ENV=staging` — a CLI recusa-se em qualquer outro
ambiente, ver acima):

    python -m app.cli.provision_staging \\
        --file /caminho/fora/do/repo/utilizadores_staging.json \\
        --actor-email admin.ja.autorizado@empresa.pt \\
        --dry-run

    python -m app.cli.provision_staging \\
        --file /caminho/fora/do/repo/utilizadores_staging.json \\
        --actor-email admin.ja.autorizado@empresa.pt \\
        --confirm

Formato do ficheiro JSON (ver docs/STAGING_BOOTSTRAP.md):

    {
      "users": [
        {
          "display_name": "Nome Real",
          "email": "nome@empresa.pt",
          "role": "project_manager",
          "entra_object_id": "11111111-2222-3333-4444-555555555555"
        }
      ]
    }

`role` tem de ser um dos códigos de `app/security/catalog.py` (ROLES):
administrador, chefe_operacoes, project_manager, comercial, financeiro.
`entra_object_id` é opcional por utilizador.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.cli.ingest_staging import assert_file_is_not_trackable_by_git
from app.config import get_settings
from app.db import SessionLocal
from app.migration.seed_dev import seed_catalog
from app.models.identity import AuthAuditLog, Permission, Role, RolePermission, User, UserRole
from app.models.people import Person
from app.security.catalog import ROLES

STAGING_ENVIRONMENT = "staging"
ADMIN_PERMISSION_CODE = "admin.manage_users"


class BootstrapError(ValueError):
    """Erro de negócio conhecido — a mensagem é sempre segura para mostrar
    diretamente a quem corre o comando (nunca uma stack trace de
    infraestrutura)."""


@dataclass
class UserBootstrapOutcome:
    email: str
    person_created: bool = False
    user_created: bool = False
    display_name_updated: bool = False
    reactivated: bool = False
    role_assigned: bool = False
    entra_object_id_linked: bool = False
    unchanged: bool = False


@dataclass
class BootstrapResult:
    outcomes: list[UserBootstrapOutcome] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        return {
            "users_processed": len(self.outcomes),
            "people_created": sum(1 for o in self.outcomes if o.person_created),
            "users_created": sum(1 for o in self.outcomes if o.user_created),
            "display_names_updated": sum(1 for o in self.outcomes if o.display_name_updated),
            "reactivated": sum(1 for o in self.outcomes if o.reactivated),
            "roles_assigned": sum(1 for o in self.outcomes if o.role_assigned),
            "entra_object_ids_linked": sum(1 for o in self.outcomes if o.entra_object_id_linked),
            "unchanged": sum(1 for o in self.outcomes if o.unchanged),
        }


def assert_staging_environment(app_env: str) -> None:
    """Barreira staging-only da CLI real (D-050, revisão de hardening):
    este comando cria/liga identidades reais e nunca deve correr fora de
    `staging` — nunca `production` (fora do âmbito deste comando), nunca
    `local` (usar `app.migration.seed_dev`), nunca `test` (os testes
    chamam `bootstrap_staging_users` diretamente, nunca via CLI). Separada
    de `main()` para ser testável sem depender do cache de
    `get_settings()` (mesmo padrão de
    `app.cli.ingest_staging.assert_staging_only_environment`)."""
    if app_env != STAGING_ENVIRONMENT:
        raise BootstrapError(
            f"comando staging-only recusado em APP_ENV={app_env!r} — só corre em "
            f"{STAGING_ENVIRONMENT!r}. Nunca 'production' (provisionamento real de produção é um "
            "processo à parte), nunca 'local' (usar app.migration.seed_dev), nunca 'test' (os "
            "testes chamam bootstrap_staging_users diretamente, nunca via esta CLI)."
        )


def _actor_has_admin_permission(db: Session, actor: User) -> bool:
    return (
        db.query(RolePermission)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .filter(UserRole.user_id == actor.id, Permission.code == ADMIN_PERMISSION_CODE)
        .first()
        is not None
    )


def _resolve_and_authorize_actor(db: Session, actor_email: str) -> User | None:
    """Resolve `actor_email` a um `User` ativo com a permissão
    `admin.manage_users` — nunca aceita um texto livre não verificado.
    Devolve `None` só na exceção de arranque a frio (ver docstring do
    módulo): a base de dados ainda não tem **nenhum** `User`, logo não
    existe nenhum "utilizador comum" que pudesse abusar da ausência de
    verificação — o próprio acesso direto ao servidor/BD para correr esta
    CLI já é a barreira nesse caso (mesma filosofia de D-034/D-037).
    Só lê a base de dados — nunca escreve nada, para que uma falha de
    autorização não deixe nenhum rasto na base de dados."""
    actor_email = actor_email.strip()
    if not actor_email:
        raise BootstrapError(
            "actor_email (quem está a executar este comando) não pode ficar vazio — exigido para "
            "autorização e auditoria."
        )

    if db.query(User).count() == 0:
        return None

    actor = (
        db.query(User)
        .filter(func.lower(User.email) == actor_email.lower(), User.is_active.is_(True))
        .one_or_none()
    )
    if actor is None:
        raise BootstrapError(
            f"nenhum utilizador ATIVO com email {actor_email!r} — só um administrador real e ativo "
            "pode executar este comando."
        )
    if not _actor_has_admin_permission(db, actor):
        raise BootstrapError(
            f"utilizador {actor_email!r} não tem a permissão {ADMIN_PERMISSION_CODE!r} — só um "
            "administrador pode executar este comando (nunca um utilizador comum, mesmo que ativo, "
            "mesmo para criar outro utilizador comum)."
        )
    return actor


def _actor_descriptor(actor: User | None, actor_email: str) -> str:
    if actor is not None:
        return f"actor_user_id={actor.id!r} actor_person_id={actor.person_id!r} actor_email={actor.email!r}"
    return (
        f"actor_email={actor_email!r} (arranque a frio — base de dados sem nenhum utilizador "
        "ainda, sem ator a verificar)"
    )


def _validate_payload(payload: dict) -> list[dict]:
    """Validação atómica do ficheiro inteiro — nada escreve na base de dados
    se qualquer entrada for inválida (mensagens de erro claras, nunca uma
    escrita parcial)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("users"), list):
        raise BootstrapError("o ficheiro tem de ter a forma {'users': [...]}")
    users = payload["users"]
    if not users:
        raise BootstrapError("'users' está vazio — nada a provisionar")

    seen_emails: dict[str, int] = {}
    seen_object_ids: dict[str, int] = {}
    for index, entry in enumerate(users):
        if not isinstance(entry, dict):
            raise BootstrapError(f"entrada #{index} não é um objeto JSON válido")

        display_name = str(entry.get("display_name") or "").strip()
        email = str(entry.get("email") or "").strip().lower()
        role = str(entry.get("role") or "").strip()
        entra_object_id = entry.get("entra_object_id")
        entra_object_id = str(entra_object_id).strip() if entra_object_id else None

        if not display_name:
            raise BootstrapError(f"entrada #{index} ({email or '?'}): 'display_name' não pode ficar vazio")
        if not email:
            raise BootstrapError(f"entrada #{index}: 'email' não pode ficar vazio")
        if email in seen_emails:
            raise BootstrapError(
                f"email {email!r} repetido nas entradas #{seen_emails[email]} e #{index} — "
                "cada utilizador só pode aparecer uma vez no ficheiro"
            )
        seen_emails[email] = index

        if role not in ROLES:
            valid = ", ".join(sorted(ROLES))
            raise BootstrapError(f"entrada #{index} ({email}): papel {role!r} inválido — papéis válidos: {valid}")

        if entra_object_id:
            if entra_object_id in seen_object_ids:
                raise BootstrapError(
                    f"entra_object_id {entra_object_id!r} repetido nas entradas "
                    f"#{seen_object_ids[entra_object_id]} e #{index} — cada Object ID só pode "
                    "ligar a um único utilizador"
                )
            seen_object_ids[entra_object_id] = index

        users[index] = {
            "display_name": display_name,
            "email": email,
            "role": role,
            "entra_object_id": entra_object_id,
        }
    return users


def _bootstrap_one_user(
    db: Session,
    *,
    entry: dict,
    role_objs: dict[str, Role],
    actor_descriptor: str,
) -> UserBootstrapOutcome:
    email = entry["email"]
    outcome = UserBootstrapOutcome(email=email)

    user = db.query(User).filter(func.lower(User.email) == email).one_or_none()
    if user is None:
        person = (
            db.query(Person)
            .filter(func.lower(Person.email) == email)
            .join(User, User.person_id == Person.id, isouter=True)
            .filter(User.id.is_(None))
            .one_or_none()
        )
        if person is None:
            person = Person(display_name=entry["display_name"], email=email, is_active=True)
            db.add(person)
            db.flush()
            outcome.person_created = True
        user = User(person_id=person.id, email=email, is_active=True)
        db.add(user)
        db.flush()
        outcome.user_created = True
        db.add(
            AuthAuditLog(
                user_id=user.id,
                event="admin_bootstrap_user",
                detail=f"User criado por bootstrap de staging (email={email!r}), executado por {actor_descriptor}.",
            )
        )
    else:
        person = user.person
        changed_fields: list[str] = []
        if person.display_name != entry["display_name"]:
            person.display_name = entry["display_name"]
            outcome.display_name_updated = True
            changed_fields.append("display_name")
        if not person.is_active:
            person.is_active = True
            outcome.reactivated = True
            changed_fields.append("person.is_active")
        if not user.is_active:
            user.is_active = True
            outcome.reactivated = True
            changed_fields.append("user.is_active")
        if changed_fields:
            db.add(
                AuthAuditLog(
                    user_id=user.id,
                    event="admin_bootstrap_user",
                    detail=(
                        f"User atualizado por bootstrap de staging (email={email!r}), campos: "
                        f"{', '.join(changed_fields)}, executado por {actor_descriptor}."
                    ),
                )
            )

    role = role_objs[entry["role"]]
    has_role = (
        db.query(UserRole).filter(UserRole.user_id == user.id, UserRole.role_id == role.id).one_or_none()
    )
    if has_role is None:
        db.add(UserRole(user_id=user.id, role_id=role.id))
        outcome.role_assigned = True
        db.add(
            AuthAuditLog(
                user_id=user.id,
                event="admin_bootstrap_user",
                detail=(
                    f"Papel {entry['role']!r} atribuído por bootstrap de staging (email={email!r}), "
                    f"executado por {actor_descriptor}."
                ),
            )
        )

    entra_object_id = entry["entra_object_id"]
    if entra_object_id:
        if user.entra_object_id == entra_object_id:
            pass  # já ligado a este valor exato — idempotente, nada a fazer
        elif user.entra_object_id:
            raise BootstrapError(
                f"utilizador {email!r} já está ligado a outro entra_object_id "
                f"({user.entra_object_id!r}) — este comando nunca reatribui; desligar é uma decisão "
                "administrativa separada."
            )
        else:
            conflict = (
                db.query(User)
                .filter(User.entra_object_id == entra_object_id, User.id != user.id)
                .one_or_none()
            )
            if conflict is not None:
                raise BootstrapError(
                    f"entra_object_id {entra_object_id!r} já está associado ao utilizador "
                    f"{conflict.email!r} — cada Object ID só pode ligar a um único utilizador."
                )
            user.entra_object_id = entra_object_id
            outcome.entra_object_id_linked = True
            db.add(
                AuthAuditLog(
                    user_id=user.id,
                    event="admin_provision_link",
                    detail=(
                        f"Ligação de entra_object_id={entra_object_id!r} a user_email={email!r} via "
                        f"bootstrap de staging, executada por {actor_descriptor}."
                    ),
                )
            )

    outcome.unchanged = not any(
        [
            outcome.person_created,
            outcome.user_created,
            outcome.display_name_updated,
            outcome.reactivated,
            outcome.role_assigned,
            outcome.entra_object_id_linked,
        ]
    )
    return outcome


def bootstrap_staging_users(
    db: Session,
    *,
    payload: dict,
    actor_email: str,
    dry_run: bool = False,
) -> BootstrapResult:
    """Núcleo do comando — chamado tanto por `main()` como pelos testes
    (`tests/test_provision_staging_cli.py`), para nunca haver duas lógicas
    divergentes entre a CLI e o que é realmente testado. Corre em qualquer
    ambiente (a barreira staging-only vive só em `main()`, ver
    `assert_staging_environment`) — para que os testes automatizados
    (`APP_ENV=test`) continuem a exercer exatamente esta lógica.

    `actor_email` é sempre resolvido e autorizado antes de qualquer
    escrita (`_resolve_and_authorize_actor`) — nunca um texto livre. Nada
    é escrito (nem o catálogo de papéis/permissões) se a validação do
    payload ou a autorização do ator falhar.

    Idempotente: chamar duas vezes com o mesmo `payload` produz o mesmo
    estado final na base de dados (nenhuma linha duplicada, nenhum erro na
    segunda chamada) — ver `UserBootstrapOutcome.unchanged` para o que cada
    entrada reportou na segunda corrida."""
    users = _validate_payload(payload)
    actor = _resolve_and_authorize_actor(db, actor_email)
    actor_descriptor = _actor_descriptor(actor, actor_email.strip())

    role_objs = seed_catalog(db)

    result = BootstrapResult()
    for entry in users:
        outcome = _bootstrap_one_user(db, entry=entry, role_objs=role_objs, actor_descriptor=actor_descriptor)
        result.outcomes.append(outcome)

    if not dry_run:
        db.commit()
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.provision_staging",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--file", required=True, type=Path, help="Caminho para o ficheiro JSON de utilizadores.")
    parser.add_argument(
        "--actor-email",
        required=True,
        help="Email de um administrador (permissão admin.manage_users) já existente e ativo — "
        "verificado antes de qualquer escrita, gravado em auditoria (AuthAuditLog).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra o plano (criações/atualizações) sem escrever nada. Comportamento por omissão sem --confirm.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Escreve mesmo na base de dados. Sem esta flag, o comando comporta-se sempre como --dry-run.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    try:
        assert_staging_environment(settings.app_env)
    except BootstrapError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    args = _build_parser().parse_args(argv)
    effective_dry_run = args.dry_run or not args.confirm

    if not args.file.exists():
        print(f"Erro: ficheiro não encontrado: {args.file}", file=sys.stderr)
        return 1
    try:
        assert_file_is_not_trackable_by_git(args.file)
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    try:
        payload = json.loads(args.file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Erro: ficheiro não é JSON válido: {exc}", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        result = bootstrap_staging_users(
            db,
            payload=payload,
            actor_email=args.actor_email,
            dry_run=effective_dry_run,
        )
    except (BootstrapError, ValueError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    finally:
        if effective_dry_run:
            db.rollback()
        db.close()

    if effective_dry_run:
        print("DRY-RUN: nada foi escrito.")
    else:
        print("OK: alterações escritas na base de dados.")
    print("Resumo:")
    for key, value in result.summary().items():
        print(f"  {key}: {value}")
    for outcome in result.outcomes:
        status = "sem alterações" if outcome.unchanged else "alterado"
        print(f"  - {outcome.email}: {status}")

    if effective_dry_run:
        print("\nPara aplicar a sério, repita com --confirm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
