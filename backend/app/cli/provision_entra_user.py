"""Provisionamento administrativo: liga um `User` já existente ao seu
`entra_object_id` real do Microsoft Entra ID (o claim `oid` de um token
validado — ver `app/security/entra_auth.py`).

Deliberadamente um **comando administrativo controlado**, não um endpoint
HTTP: pensado para ser corrido manualmente por alguém com acesso direto ao
servidor/base de dados de staging/produção (ex. via `docker exec`/SSH),
nunca a partir do frontend. Isto evita acrescentar uma nova superfície de
API só para uma operação rara (até 5 utilizadores — ver docs/PLAN.md) e
mantém o único caminho de autenticação real (`get_current_user`) livre de
qualquer lógica de criação/associação de identidade. Ver docs/DECISIONS.md
D-034 e docs/STAGING_CHECKLIST.md ("Provisionamento dos 5 utilizadores").

Regras, sempre aplicadas por `link_user_to_entra_object_id` (nunca só pelo
`main()` da linha de comandos, para que os testes exerçam exatamente a
mesma lógica):

- **Nunca cria um `User` novo** — só liga a um `User` já existente e
  ativo, criado antes por outro processo administrativo (seed/migração de
  pessoas). Um email desconhecido ou inativo é sempre um erro, nunca uma
  criação silenciosa.
- **Nunca reatribui** — um `User` já ligado a QUALQUER `entra_object_id`
  (o mesmo ou outro) é sempre um erro; desligar é uma decisão
  administrativa separada, fora do âmbito deste comando (mantém o
  comando pequeno e sem ambiguidade sobre "o que faz").
- **Nunca reutiliza um `entra_object_id` em dois utilizadores** — a coluna
  `User.entra_object_id` já tem uma restrição UNIQUE na base de dados
  (`app/models/identity.py`), mas esta verificação explícita dá um erro
  compreensível em vez de deixar a `IntegrityError` do motor de base de
  dados subir sem contexto.
- **Sempre registado em auditoria** (`AuthAuditLog`, evento
  `admin_provision_link`) — com o email do utilizador, o `entra_object_id`,
  e quem executou o comando (`actor_label`, obrigatório).

Utilização (staging/produção — nunca necessário em local/test, onde o JIT
linking por email já resolve isto automaticamente):

    python -m app.cli.provision_entra_user \
        --actor-email admin@empresa.pt \
        --user-email pm.silva@empresa.pt \
        --entra-object-id 11111111-2222-3333-4444-555555555555 \
        --confirm

Sem `--confirm`, o comando só mostra o que faria (nunca escreve na base de
dados) — proteção contra execução acidental de um comando administrativo
irreversível (é sempre reversível *tecnicamente* via SQL direto, mas nunca
por um segundo comando desta CLI, de propósito: desligar não é um caso de
uso previsto aqui).
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.identity import AuthAuditLog, User


class ProvisioningError(ValueError):
    """Erro de negócio conhecido — a mensagem é sempre segura para mostrar
    diretamente a quem corre o comando (nunca uma stack trace de
    infraestrutura)."""


def link_user_to_entra_object_id(
    db: Session,
    *,
    user_email: str,
    entra_object_id: str,
    actor_label: str,
) -> User:
    """Núcleo do provisionamento — chamado tanto por `main()` como pelos
    testes (`tests/test_provision_entra_user.py`), para nunca haver duas
    lógicas divergentes entre a CLI e o que é realmente testado."""
    user_email = user_email.strip()
    entra_object_id = entra_object_id.strip()
    actor_label = actor_label.strip()

    if not user_email:
        raise ProvisioningError("user_email não pode ficar vazio.")
    if not entra_object_id:
        raise ProvisioningError("entra_object_id não pode ficar vazio.")
    if not actor_label:
        raise ProvisioningError(
            "actor_label (quem está a executar este comando) não pode ficar vazio — exigido para auditoria."
        )

    user = (
        db.query(User)
        .filter(func.lower(User.email) == user_email.lower(), User.is_active.is_(True))
        .one_or_none()
    )
    if user is None:
        raise ProvisioningError(
            f"nenhum utilizador ATIVO com email {user_email!r}. Este comando nunca cria um "
            "User novo (ver docs/DECISIONS.md D-034) — crie o User primeiro por outro processo "
            "administrativo (seed/migração de pessoas), depois repita este comando."
        )

    if user.entra_object_id:
        if user.entra_object_id == entra_object_id:
            raise ProvisioningError(f"utilizador {user_email!r} já está ligado exatamente a este entra_object_id.")
        raise ProvisioningError(
            f"utilizador {user_email!r} já está ligado a outro entra_object_id "
            f"({user.entra_object_id!r}). Desligar um utilizador já provisionado é uma decisão "
            "administrativa separada, fora do âmbito deste comando."
        )

    conflict = db.query(User).filter(User.entra_object_id == entra_object_id, User.id != user.id).one_or_none()
    if conflict is not None:
        raise ProvisioningError(
            f"entra_object_id {entra_object_id!r} já está associado ao utilizador {conflict.email!r} — "
            "cada entra_object_id só pode ligar a um único User."
        )

    user.entra_object_id = entra_object_id
    db.add(
        AuthAuditLog(
            user_id=user.id,
            event="admin_provision_link",
            detail=(
                f"Ligação administrativa de entra_object_id={entra_object_id!r} a "
                f"user_email={user_email!r}, executada por actor={actor_label!r}."
            ),
        )
    )
    db.commit()
    db.refresh(user)
    return user


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.provision_entra_user",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--user-email", required=True, help="Email do User já existente a ligar.")
    parser.add_argument(
        "--entra-object-id",
        required=True,
        help="Claim 'oid' do utilizador no tenant Microsoft Entra ID (Azure Portal → Users → Object ID).",
    )
    parser.add_argument(
        "--actor-email",
        required=True,
        help="Email de quem está a executar este comando — gravado em auditoria (AuthAuditLog).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Escreve mesmo na base de dados. Sem esta flag, só mostra o que seria feito (dry-run).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if not args.confirm:
        print(
            "Dry-run (sem --confirm) — nada foi escrito.\n"
            f"  ligaria user_email={args.user_email!r} a entra_object_id={args.entra_object_id!r}\n"
            f"  actor={args.actor_email!r}\n"
            "Repetir com --confirm para aplicar."
        )
        return 0

    db = SessionLocal()
    try:
        user = link_user_to_entra_object_id(
            db,
            user_email=args.user_email,
            entra_object_id=args.entra_object_id,
            actor_label=args.actor_email,
        )
    except ProvisioningError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    print(f"OK: user_id={user.id} email={user.email!r} agora ligado a entra_object_id={user.entra_object_id!r}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
