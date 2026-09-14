"""Provisionamento administrativo de utilizadores Entra ID (D-034) —
`app/cli/provision_entra_user.py`. Testa sempre `link_user_to_entra_object_id`
diretamente (o mesmo núcleo que `main()` chama), nunca a CLI/argparse: o
comportamento de negócio é o que importa auditar aqui.
"""
from __future__ import annotations

import pytest

from app.cli.provision_entra_user import ProvisioningError, link_user_to_entra_object_id
from app.models.identity import AuthAuditLog, User

_PM_EMAIL = "pm.um.sintetico@example.invalid"
_CHEFE_EMAIL = "chefe.sintetico@example.invalid"


def test_links_an_existing_active_user(db_session):
    db = db_session
    user = link_user_to_entra_object_id(
        db,
        user_email=_PM_EMAIL,
        entra_object_id="11111111-1111-1111-1111-111111111111",
        actor_label="admin.teste@example.invalid",
    )
    assert user.entra_object_id == "11111111-1111-1111-1111-111111111111"

    db.refresh(user)
    assert user.entra_object_id == "11111111-1111-1111-1111-111111111111"


def test_records_audit_log_entry(db_session):
    db = db_session
    user = link_user_to_entra_object_id(
        db,
        user_email=_PM_EMAIL,
        entra_object_id="22222222-2222-2222-2222-222222222222",
        actor_label="admin.teste@example.invalid",
    )

    entries = db.query(AuthAuditLog).filter(AuthAuditLog.user_id == user.id).all()
    assert len(entries) == 1
    assert entries[0].event == "admin_provision_link"
    assert "22222222-2222-2222-2222-222222222222" in entries[0].detail
    assert "admin.teste@example.invalid" in entries[0].detail


def test_is_case_insensitive_on_email(db_session):
    db = db_session
    user = link_user_to_entra_object_id(
        db,
        user_email=_PM_EMAIL.upper(),
        entra_object_id="33333333-3333-3333-3333-333333333333",
        actor_label="admin.teste@example.invalid",
    )
    assert user.email == _PM_EMAIL


def test_rejects_unknown_email(db_session):
    db = db_session
    with pytest.raises(ProvisioningError, match="nenhum utilizador ATIVO"):
        link_user_to_entra_object_id(
            db,
            user_email="ninguem.assim@example.invalid",
            entra_object_id="44444444-4444-4444-4444-444444444444",
            actor_label="admin.teste@example.invalid",
        )


def test_rejects_inactive_user(db_session):
    db = db_session
    user = db.query(User).filter(User.email == _PM_EMAIL).one()
    user.is_active = False
    db.commit()

    with pytest.raises(ProvisioningError, match="nenhum utilizador ATIVO"):
        link_user_to_entra_object_id(
            db,
            user_email=_PM_EMAIL,
            entra_object_id="55555555-5555-5555-5555-555555555555",
            actor_label="admin.teste@example.invalid",
        )


def test_never_creates_a_new_user(db_session):
    db = db_session
    users_before = db.query(User).count()
    with pytest.raises(ProvisioningError):
        link_user_to_entra_object_id(
            db,
            user_email="alguem.novo@example.invalid",
            entra_object_id="66666666-6666-6666-6666-666666666666",
            actor_label="admin.teste@example.invalid",
        )
    assert db.query(User).count() == users_before


def test_rejects_relinking_an_already_linked_user(db_session):
    db = db_session
    link_user_to_entra_object_id(
        db,
        user_email=_PM_EMAIL,
        entra_object_id="77777777-7777-7777-7777-777777777777",
        actor_label="admin.teste@example.invalid",
    )

    with pytest.raises(ProvisioningError, match="já está ligado"):
        link_user_to_entra_object_id(
            db,
            user_email=_PM_EMAIL,
            entra_object_id="88888888-8888-8888-8888-888888888888",
            actor_label="admin.teste@example.invalid",
        )


def test_rejects_reusing_the_same_entra_object_id_for_two_users(db_session):
    db = db_session
    link_user_to_entra_object_id(
        db,
        user_email=_PM_EMAIL,
        entra_object_id="99999999-9999-9999-9999-999999999999",
        actor_label="admin.teste@example.invalid",
    )

    with pytest.raises(ProvisioningError, match="já está associado"):
        link_user_to_entra_object_id(
            db,
            user_email=_CHEFE_EMAIL,
            entra_object_id="99999999-9999-9999-9999-999999999999",
            actor_label="admin.teste@example.invalid",
        )

    chefe = db.query(User).filter(User.email == _CHEFE_EMAIL).one()
    assert chefe.entra_object_id is None


def test_database_unique_constraint_is_the_final_backstop(db_session):
    """Mesmo que a verificação explícita acima seja contornada (ex. um bug
    futuro), a coluna `entra_object_id` tem UNIQUE na base de dados — nunca
    depende só da lógica Python. Confirmado diretamente aqui."""
    db = db_session
    user_a = db.query(User).filter(User.email == _PM_EMAIL).one()
    user_b = db.query(User).filter(User.email == _CHEFE_EMAIL).one()
    user_a.entra_object_id = "shared-oid-sintetico"
    db.commit()

    user_b.entra_object_id = "shared-oid-sintetico"
    with pytest.raises(Exception):  # IntegrityError concreta depende do dialect
        db.commit()
    db.rollback()


@pytest.mark.parametrize(
    "kwargs,match",
    [
        (dict(user_email="", entra_object_id="x", actor_label="a"), "user_email"),
        (dict(user_email="x@example.invalid", entra_object_id="", actor_label="a"), "entra_object_id"),
        (dict(user_email="x@example.invalid", entra_object_id="x", actor_label=""), "actor_label"),
    ],
)
def test_rejects_empty_required_arguments(db_session, kwargs, match):
    with pytest.raises(ProvisioningError, match=match):
        link_user_to_entra_object_id(db_session, **kwargs)
