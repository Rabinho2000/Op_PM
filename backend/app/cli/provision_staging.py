"""Bootstrap idempotente do catálogo de papéis/permissões e dos utilizadores
reais de staging — comando administrativo controlado, nunca um endpoint HTTP
(mesmo desenho de `app/cli/ingest_staging.py` e `app/cli/provision_entra_user.py`,
ver docs/DECISIONS.md D-034/D-037/D-050).

Resolve o vazio deixado por `docs/DECISIONS.md` D-049 e
`docs/OPEN_QUESTIONS.md` pergunta 26: até agora, criar `Person`/`User`/
`UserRole` reais em staging exigia Python/SQL manual (documentado em
`docs/STAGING_RUNBOOK.md` secção 9.1), porque `app.migration.seed_dev` está
deliberadamente bloqueado fora de `local`/`test` (D-049) — esse seed cria
dados sintéticos, nunca aceitável em staging.

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
  quando associa um `entra_object_id`.

**O que este comando nunca faz:** nunca remove um papel já atribuído a um
utilizador que não esteja no ficheiro (edição é sempre aditiva); nunca
desativa um utilizador que deixe de aparecer no ficheiro (desativação é uma
decisão administrativa separada, fora do âmbito deste comando); nunca cria
projetos — a ingestão de projetos é sempre via `app.cli.ingest_staging`
(D-037).

Utilização (staging — nunca necessário em local/test, onde
`app.migration.seed_dev` já resolve isto com dados sintéticos):

    python -m app.cli.provision_staging \\
        --file /caminho/fora/do/repo/utilizadores_staging.json \\
        --actor-email admin@empresa.pt \\
        --dry-run

    python -m app.cli.provision_staging \\
        --file /caminho/fora/do/repo/utilizadores_staging.json \\
        --actor-email admin@empresa.pt \\
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
from app.db import SessionLocal
from app.migration.seed_dev import seed_catalog
from app.models.identity import AuthAuditLog, Role, User, UserRole
from app.models.people import Person
from app.security.catalog import ROLES


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
    actor_label: str,
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
                detail=f"User criado por bootstrap de staging (email={email!r}), executado por actor={actor_label!r}.",
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
                        f"{', '.join(changed_fields)}, executado por actor={actor_label!r}."
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
                    f"executado por actor={actor_label!r}."
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
                        f"bootstrap de staging, executada por actor={actor_label!r}."
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
    actor_label: str,
    dry_run: bool = False,
) -> BootstrapResult:
    """Núcleo do comando — chamado tanto por `main()` como pelos testes
    (`tests/test_provision_staging_cli.py`), para nunca haver duas lógicas
    divergentes entre a CLI e o que é realmente testado.

    Idempotente: chamar duas vezes com o mesmo `payload` produz o mesmo
    estado final na base de dados (nenhuma linha duplicada, nenhum erro na
    segunda chamada) — ver `UserBootstrapOutcome.unchanged` para o que cada
    entrada reportou na segunda corrida."""
    actor_label = actor_label.strip()
    if not actor_label:
        raise BootstrapError("actor_label (quem está a executar este comando) não pode ficar vazio — exigido para auditoria.")

    users = _validate_payload(payload)

    role_objs = seed_catalog(db)

    result = BootstrapResult()
    for entry in users:
        outcome = _bootstrap_one_user(db, entry=entry, role_objs=role_objs, actor_label=actor_label)
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
        help="Email de quem está a executar este comando — gravado em auditoria (AuthAuditLog).",
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
            actor_label=args.actor_email,
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
