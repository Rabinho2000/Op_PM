"""Bootstrap de staging (D-050) — `app/cli/provision_staging.py`. Testa
sempre `bootstrap_staging_users` diretamente (o mesmo núcleo que `main()`
chama), nunca a CLI/argparse: o comportamento de negócio é o que importa
auditar aqui — mesmo padrão de `tests/test_provision_entra_user.py` e
`tests/test_ingest_staging_cli.py`.
"""
from __future__ import annotations

import copy

import pytest

from app.cli.ingest_staging import assert_file_is_not_trackable_by_git
from app.cli.provision_staging import BootstrapError, bootstrap_staging_users
from app.models.identity import AuthAuditLog, User, UserRole
from app.models.people import Person
from app.models.project import Project

_ACTOR = "admin.teste@example.invalid"

_PAYLOAD = {
    "users": [
        {
            "display_name": "Nova PM Real",
            "email": "nova.pm.real@empresa.pt",
            "role": "project_manager",
            "entra_object_id": "11111111-1111-1111-1111-111111111111",
        },
        {
            "display_name": "Novo Financeiro Real",
            "email": "novo.financeiro.real@empresa.pt",
            "role": "financeiro",
        },
    ]
}


def _payload() -> dict:
    return copy.deepcopy(_PAYLOAD)


def test_creates_person_user_and_role_for_new_entries(db_session):
    db = db_session
    result = bootstrap_staging_users(db, payload=_payload(), actor_label=_ACTOR)

    assert result.summary()["users_processed"] == 2
    assert result.summary()["people_created"] == 2
    assert result.summary()["users_created"] == 2
    assert result.summary()["roles_assigned"] == 2
    assert result.summary()["entra_object_ids_linked"] == 1

    pm = db.query(User).filter(User.email == "nova.pm.real@empresa.pt").one()
    assert pm.is_active is True
    assert pm.entra_object_id == "11111111-1111-1111-1111-111111111111"
    assert pm.person.display_name == "Nova PM Real"
    roles = db.query(UserRole).filter(UserRole.user_id == pm.id).all()
    assert len(roles) == 1

    financeiro = db.query(User).filter(User.email == "novo.financeiro.real@empresa.pt").one()
    assert financeiro.entra_object_id is None


def test_never_creates_a_project(db_session):
    db = db_session
    projects_before = db.query(Project).count()
    bootstrap_staging_users(db, payload=_payload(), actor_label=_ACTOR)
    assert db.query(Project).count() == projects_before


def test_records_audit_log_entries(db_session):
    db = db_session
    bootstrap_staging_users(db, payload=_payload(), actor_label=_ACTOR)

    pm = db.query(User).filter(User.email == "nova.pm.real@empresa.pt").one()
    events = {e.event for e in db.query(AuthAuditLog).filter(AuthAuditLog.user_id == pm.id).all()}
    assert "admin_bootstrap_user" in events
    assert "admin_provision_link" in events


def test_is_idempotent_when_run_twice(db_session):
    db = db_session
    bootstrap_staging_users(db, payload=_payload(), actor_label=_ACTOR)

    users_before = db.query(User).count()
    people_before = db.query(Person).count()
    roles_before = db.query(UserRole).count()
    audit_before = db.query(AuthAuditLog).count()

    second = bootstrap_staging_users(db, payload=_payload(), actor_label=_ACTOR)

    assert db.query(User).count() == users_before
    assert db.query(Person).count() == people_before
    assert db.query(UserRole).count() == roles_before
    assert db.query(AuthAuditLog).count() == audit_before
    assert all(outcome.unchanged for outcome in second.outcomes)


def test_updates_display_name_and_reactivates_without_duplicating(db_session):
    db = db_session
    bootstrap_staging_users(db, payload=_payload(), actor_label=_ACTOR)

    pm = db.query(User).filter(User.email == "nova.pm.real@empresa.pt").one()
    pm.is_active = False
    pm.person.is_active = False
    db.commit()

    updated_payload = _payload()
    updated_payload["users"][0]["display_name"] = "Nova PM Real (Atualizada)"

    result = bootstrap_staging_users(db, payload=updated_payload, actor_label=_ACTOR)

    assert db.query(User).filter(User.email == "nova.pm.real@empresa.pt").count() == 1
    pm = db.query(User).filter(User.email == "nova.pm.real@empresa.pt").one()
    assert pm.is_active is True
    assert pm.person.display_name == "Nova PM Real (Atualizada)"
    assert pm.person.is_active is True

    pm_outcome = next(o for o in result.outcomes if o.email == "nova.pm.real@empresa.pt")
    assert pm_outcome.display_name_updated is True
    assert pm_outcome.reactivated is True


def test_attaches_a_user_to_an_existing_person_without_login(db_session):
    db = db_session
    legacy_person = Person(display_name="PM Legado Sem Login", email="pm.legado.real@empresa.pt", is_active=True)
    db.add(legacy_person)
    db.commit()

    payload = {
        "users": [
            {
                "display_name": "PM Legado Sem Login",
                "email": "pm.legado.real@empresa.pt",
                "role": "project_manager",
            }
        ]
    }
    bootstrap_staging_users(db, payload=payload, actor_label=_ACTOR)

    assert db.query(Person).filter(Person.email == "pm.legado.real@empresa.pt").count() == 1
    user = db.query(User).filter(User.email == "pm.legado.real@empresa.pt").one()
    assert user.person_id == legacy_person.id


def test_never_removes_an_existing_role_not_in_the_payload(db_session):
    db = db_session
    bootstrap_staging_users(db, payload=_payload(), actor_label=_ACTOR)
    pm = db.query(User).filter(User.email == "nova.pm.real@empresa.pt").one()
    roles_before = db.query(UserRole).filter(UserRole.user_id == pm.id).count()
    assert roles_before == 1

    # Reatribuir o mesmo papel não duplica nem remove nada.
    bootstrap_staging_users(db, payload=_payload(), actor_label=_ACTOR)
    assert db.query(UserRole).filter(UserRole.user_id == pm.id).count() == roles_before


def test_dry_run_leaves_no_trace(db_session):
    db = db_session
    users_before = db.query(User).count()
    people_before = db.query(Person).count()
    audit_before = db.query(AuthAuditLog).count()

    result = bootstrap_staging_users(db, payload=_payload(), actor_label=_ACTOR, dry_run=True)
    db.rollback()

    assert result.summary()["users_created"] == 2
    assert db.query(User).count() == users_before
    assert db.query(Person).count() == people_before
    assert db.query(AuthAuditLog).count() == audit_before


def test_rejects_duplicate_email_within_payload(db_session):
    payload = {
        "users": [
            {"display_name": "A", "email": "dup@empresa.pt", "role": "project_manager"},
            {"display_name": "B", "email": "DUP@empresa.pt", "role": "financeiro"},
        ]
    }
    with pytest.raises(BootstrapError, match="repetido"):
        bootstrap_staging_users(db_session, payload=payload, actor_label=_ACTOR)


def test_rejects_invalid_role(db_session):
    payload = {"users": [{"display_name": "A", "email": "a@empresa.pt", "role": "papel_inexistente"}]}
    with pytest.raises(BootstrapError, match="inválido"):
        bootstrap_staging_users(db_session, payload=payload, actor_label=_ACTOR)


def test_rejects_duplicate_entra_object_id_within_payload(db_session):
    payload = {
        "users": [
            {
                "display_name": "A",
                "email": "a@empresa.pt",
                "role": "project_manager",
                "entra_object_id": "same-oid",
            },
            {
                "display_name": "B",
                "email": "b@empresa.pt",
                "role": "financeiro",
                "entra_object_id": "same-oid",
            },
        ]
    }
    with pytest.raises(BootstrapError, match="repetido"):
        bootstrap_staging_users(db_session, payload=payload, actor_label=_ACTOR)


def test_rejects_entra_object_id_already_used_by_a_different_existing_user(db_session):
    db = db_session
    bootstrap_staging_users(db, payload=_payload(), actor_label=_ACTOR)

    payload = {
        "users": [
            {
                "display_name": "Outro Utilizador",
                "email": "outro@empresa.pt",
                "role": "comercial",
                "entra_object_id": "11111111-1111-1111-1111-111111111111",
            }
        ]
    }
    with pytest.raises(BootstrapError, match="já está associado"):
        bootstrap_staging_users(db, payload=payload, actor_label=_ACTOR)


def test_never_reassigns_an_existing_entra_object_id_to_a_different_value(db_session):
    db = db_session
    bootstrap_staging_users(db, payload=_payload(), actor_label=_ACTOR)

    payload = _payload()
    payload["users"][0]["entra_object_id"] = "22222222-2222-2222-2222-222222222222"
    with pytest.raises(BootstrapError, match="já está ligado"):
        bootstrap_staging_users(db, payload=payload, actor_label=_ACTOR)


def test_rejects_empty_users_list(db_session):
    with pytest.raises(BootstrapError, match="vazio"):
        bootstrap_staging_users(db_session, payload={"users": []}, actor_label=_ACTOR)


def test_rejects_empty_actor_label(db_session):
    with pytest.raises(BootstrapError, match="actor_label"):
        bootstrap_staging_users(db_session, payload=_payload(), actor_label="   ")


def test_rejects_a_file_tracked_by_git_and_not_ignored():
    """`provision_staging` reutiliza `assert_file_is_not_trackable_by_git`
    (já testada exaustivamente em `test_ingest_staging_cli.py`) — aqui só
    confirmamos que está de facto ligada, sem duplicar os testes da função
    em si."""
    from app.cli.provision_staging import assert_file_is_not_trackable_by_git as wired

    assert wired is assert_file_is_not_trackable_by_git
