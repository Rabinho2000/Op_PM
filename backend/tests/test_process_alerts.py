"""Alarmes de etapas do processo: subscrições, gatilho por etapa, notificações in-app."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.models.identity import Role, User, UserRole
from app.models.notification import Notification
from app.models.people import Person
from app.models.process_alerts import ProcessStageSubscription
from app.models.project import Project, ProjectSubtaskProgress
from app.models.workflow import WorkflowStage, WorkflowSubtask
from app.security.catalog import ROLE_PM

CHEFE = "chefe.sintetico@example.invalid"
PM_UM = "pm.um.sintetico@example.invalid"
COMERCIAL = "comercial.sintetico@example.invalid"
ADMIN = "admin.sintetico@example.invalid"
OWN = "Instalação Sintética de Demonstração"  # PM Um
LEGACY_PM = "Instalação Sintética F — PM Legado"  # sem PM Um
# etapa-01 tem uma só subtarefa (etapa-01.0): marcá-la completa a etapa de uma vez.
STAGE_ONE_CODE = "etapa-01"
STAGE_TWO_CODE = "etapa-02"  # seis subtarefas


def _h(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _project(db, name: str) -> Project:
    return db.query(Project).filter(Project.name == name).one()


def _stage(db, code: str) -> WorkflowStage:
    return db.query(WorkflowStage).filter(WorkflowStage.code == code).one()


def _subtask_ids(db, stage_code: str) -> list[uuid.UUID]:
    stage = _stage(db, stage_code)
    return [
        s.id
        for s in db.query(WorkflowSubtask)
        .filter(WorkflowSubtask.stage_id == stage.id)
        .order_by(WorkflowSubtask.sort_order)
        .all()
    ]


def _mark_subtask(api_client, project, subtask_id, *, done=True, email=CHEFE):
    return api_client.patch(
        f"/api/projects/{project.id}/process/subtasks/{subtask_id}", json={"done": done}, headers=_h(email)
    )


def _mark_stage(api_client, project, stage, *, done=True, email=CHEFE):
    return api_client.patch(
        f"/api/projects/{project.id}/process/stages/{stage.id}/subtasks", json={"done": done}, headers=_h(email)
    )


def _user(db, email: str, role_codes: list[str]) -> User:
    person = Person(display_name=f"Pessoa {email.split('@')[0]}", email=email, is_active=True)
    db.add(person)
    db.flush()
    user = User(person_id=person.id, email=email, is_active=True)
    db.add(user)
    db.flush()
    for code in role_codes:
        role = db.query(Role).filter(Role.code == code).one()
        db.add(UserRole(user_id=user.id, role_id=role.id))
    db.flush()
    return user


def _subscribe(api_client, email: str, stage_codes: list[str]):
    # Resolve ids pela API de catálogo: o cliente só envia ids do catálogo.
    return api_client.put(
        "/api/me/process-alerts/subscriptions",
        json={"stage_ids": stage_codes},
        headers=_h(email),
    )


def _stage_ids(db, codes: list[str]) -> list[str]:
    return [str(_stage(db, c).id) for c in codes]


def _notifications(db, user: User) -> list[Notification]:
    return db.query(Notification).filter(Notification.user_id == user.id).all()


# --- subscrições -------------------------------------------------------------------------


def test_subscribe_and_unsubscribe_own_stages(db_session, api_client):
    ids = _stage_ids(db_session, [STAGE_ONE_CODE, STAGE_TWO_CODE])
    resp = _subscribe(api_client, PM_UM, ids)
    assert resp.status_code == 200
    subscribed = {s["code"] for p in resp.json()["phases"] for s in p["stages"] if s["subscribed"]}
    assert subscribed == {STAGE_ONE_CODE, STAGE_TWO_CODE}

    pm = db_session.query(User).filter(User.email == PM_UM).one()
    assert db_session.query(ProcessStageSubscription).filter_by(user_id=pm.id).count() == 2

    resp = _subscribe(api_client, PM_UM, [ids[0]])
    assert resp.status_code == 200
    assert db_session.query(ProcessStageSubscription).filter_by(user_id=pm.id).count() == 1

    get = api_client.get("/api/me/process-alerts/subscriptions", headers=_h(PM_UM)).json()
    flags = {s["code"]: s["subscribed"] for p in get["phases"] for s in p["stages"]}
    assert flags[STAGE_ONE_CODE] is True and flags[STAGE_TWO_CODE] is False


def test_subscribing_twice_is_idempotent_and_unknown_stage_is_refused(db_session, api_client):
    ids = _stage_ids(db_session, [STAGE_ONE_CODE])
    assert _subscribe(api_client, PM_UM, ids).status_code == 200
    assert _subscribe(api_client, PM_UM, ids).status_code == 200
    pm = db_session.query(User).filter(User.email == PM_UM).one()
    assert db_session.query(ProcessStageSubscription).filter_by(user_id=pm.id).count() == 1

    bogus = _subscribe(api_client, PM_UM, [str(uuid.uuid4())])
    assert bogus.status_code == 422
    # Nada alterado: a subscrição anterior mantém-se (a escrita não é parcial).
    assert db_session.query(ProcessStageSubscription).filter_by(user_id=pm.id).count() == 1


def test_installer_external_role_gets_403_on_every_alert_endpoint(db_session, api_client):
    _user(db_session, "instalador.alertas.sintetico@example.invalid", ["instalador_colaborador"])
    email = "instalador.alertas.sintetico@example.invalid"
    ids = _stage_ids(db_session, [STAGE_ONE_CODE])
    assert api_client.get("/api/me/process-alerts/subscriptions", headers=_h(email)).status_code == 403
    assert _subscribe(api_client, email, ids).status_code == 403
    assert api_client.get("/api/me/notifications", headers=_h(email)).status_code == 403
    assert api_client.get("/api/me/notifications/unread-count", headers=_h(email)).status_code == 403
    assert api_client.post("/api/me/notifications/read-all", headers=_h(email)).status_code == 403
    fake = str(uuid.uuid4())
    assert api_client.post(f"/api/me/notifications/{fake}/read", headers=_h(email)).status_code == 403


def test_user_without_alert_permission_is_forbidden(db_session, api_client):
    # Um papel sem process_alert.use (ex.: ninguém do catálogo além do instalador) → 403.
    user = _user(db_session, "sem.alertas.sintetico@example.invalid", [])
    assert api_client.get("/api/me/process-alerts/subscriptions", headers=_h(user.email)).status_code == 403
    assert api_client.get("/api/me/notifications", headers=_h(user.email)).status_code == 403


# --- gatilho ----------------------------------------------------------------------------


def test_completing_a_single_subtask_that_finishes_the_stage_notifies_subscribers(db_session, api_client):
    project = _project(db_session, OWN)
    pm = db_session.query(User).filter(User.email == PM_UM).one()
    assert _subscribe(api_client, PM_UM, _stage_ids(db_session, [STAGE_ONE_CODE])).status_code == 200

    sid = _subtask_ids(db_session, STAGE_ONE_CODE)[0]
    assert _mark_subtask(api_client, project, sid).status_code == 200

    rows = _notifications(db_session, pm)
    assert len(rows) == 1
    n = rows[0]
    assert n.kind == "process_stage_completed"
    assert n.project_id == project.id and n.stage_id == _stage(db_session, STAGE_ONE_CODE).id
    assert n.is_read is False and n.read_at is None
    assert "Etapa concluída" in n.message and project.name in n.message


def test_completing_an_entire_stage_in_bulk_notifies_once(db_session, api_client):
    project = _project(db_session, OWN)
    pm = db_session.query(User).filter(User.email == PM_UM).one()
    assert _subscribe(api_client, PM_UM, _stage_ids(db_session, [STAGE_TWO_CODE])).status_code == 200

    resp = _mark_stage(api_client, project, _stage(db_session, STAGE_TWO_CODE))
    assert resp.status_code == 200
    assert len(_notifications(db_session, pm)) == 1


def test_partial_completion_does_not_notify(db_session, api_client):
    project = _project(db_session, OWN)
    pm = db_session.query(User).filter(User.email == PM_UM).one()
    assert _subscribe(api_client, PM_UM, _stage_ids(db_session, [STAGE_TWO_CODE])).status_code == 200
    sids = _subtask_ids(db_session, STAGE_TWO_CODE)
    for sid in sids[:-1]:
        assert _mark_subtask(api_client, project, sid).status_code == 200
    assert _notifications(db_session, pm) == []
    assert _mark_subtask(api_client, project, sids[-1]).status_code == 200
    assert len(_notifications(db_session, pm)) == 1


def test_unmarking_does_not_delete_and_recompleting_creates_a_new_notification(db_session, api_client):
    project = _project(db_session, OWN)
    pm = db_session.query(User).filter(User.email == PM_UM).one()
    assert _subscribe(api_client, PM_UM, _stage_ids(db_session, [STAGE_ONE_CODE])).status_code == 200
    sid = _subtask_ids(db_session, STAGE_ONE_CODE)[0]

    _mark_subtask(api_client, project, sid)
    assert len(_notifications(db_session, pm)) == 1

    _mark_subtask(api_client, project, sid, done=False)  # desmarcar não apaga
    assert len(_notifications(db_session, pm)) == 1

    _mark_subtask(api_client, project, sid)  # re-completar gera uma nova
    assert len(_notifications(db_session, pm)) == 2


def test_repeating_a_completed_action_creates_no_duplicates(db_session, api_client):
    project = _project(db_session, OWN)
    pm = db_session.query(User).filter(User.email == PM_UM).one()
    assert _subscribe(api_client, PM_UM, _stage_ids(db_session, [STAGE_ONE_CODE])).status_code == 200
    sid = _subtask_ids(db_session, STAGE_ONE_CODE)[0]
    _mark_subtask(api_client, project, sid)
    _mark_subtask(api_client, project, sid)  # já feita: nenhuma transição
    _mark_stage(api_client, project, _stage(db_session, STAGE_ONE_CODE))  # idem por etapa
    assert len(_notifications(db_session, pm)) == 1


def test_actor_does_not_notify_themselves(db_session, api_client):
    project = _project(db_session, OWN)
    chefe = db_session.query(User).filter(User.email == CHEFE).one()
    assert _subscribe(api_client, CHEFE, _stage_ids(db_session, [STAGE_ONE_CODE])).status_code == 200
    sid = _subtask_ids(db_session, STAGE_ONE_CODE)[0]
    assert _mark_subtask(api_client, project, sid).status_code == 200
    assert _notifications(db_session, chefe) == []


def test_actor_is_excluded_but_other_subscribers_are_notified(db_session, api_client):
    project = _project(db_session, OWN)
    pm = db_session.query(User).filter(User.email == PM_UM).one()
    chefe = db_session.query(User).filter(User.email == CHEFE).one()
    ids = _stage_ids(db_session, [STAGE_ONE_CODE])
    assert _subscribe(api_client, PM_UM, ids).status_code == 200
    assert _subscribe(api_client, CHEFE, ids).status_code == 200
    sid = _subtask_ids(db_session, STAGE_ONE_CODE)[0]
    assert _mark_subtask(api_client, project, sid, email=CHEFE).status_code == 200
    assert len(_notifications(db_session, pm)) == 1
    assert _notifications(db_session, chefe) == []


def test_subscriber_without_visibility_of_the_project_is_not_notified(db_session, api_client):
    # PM Um não é PM de LEGACY_PM: não o vê (404), logo não recebe o alarme.
    project = _project(db_session, LEGACY_PM)
    pm = db_session.query(User).filter(User.email == PM_UM).one()
    assert _subscribe(api_client, PM_UM, _stage_ids(db_session, [STAGE_ONE_CODE])).status_code == 200
    assert api_client.get(f"/api/projects/{project.id}/process", headers=_h(PM_UM)).status_code == 404
    sid = _subtask_ids(db_session, STAGE_ONE_CODE)[0]
    assert _mark_subtask(api_client, project, sid).status_code == 200
    assert _notifications(db_session, pm) == []


def test_visibility_is_checked_at_trigger_time_and_at_listing_time(db_session, api_client):
    project = _project(db_session, OWN)
    pm = db_session.query(User).filter(User.email == PM_UM).one()
    assert _subscribe(api_client, PM_UM, _stage_ids(db_session, [STAGE_ONE_CODE])).status_code == 200
    sid = _subtask_ids(db_session, STAGE_ONE_CODE)[0]
    _mark_subtask(api_client, project, sid)
    assert api_client.get("/api/me/notifications", headers=_h(PM_UM)).json()["total"] == 1

    # Deixa de ser PM do projeto → a notificação antiga deixa de aparecer na listagem.
    project.pm_person_id = None
    db_session.flush()
    listing = api_client.get("/api/me/notifications", headers=_h(PM_UM)).json()
    assert listing["total"] == 0 and listing["items"] == []
    assert api_client.get("/api/me/notifications/unread-count", headers=_h(PM_UM)).json()["unread"] == 0
    assert len(_notifications(db_session, pm)) == 1  # não foi apagada


def test_inactive_subscriber_is_not_notified(db_session, api_client):
    project = _project(db_session, OWN)
    pm = db_session.query(User).filter(User.email == PM_UM).one()
    assert _subscribe(api_client, PM_UM, _stage_ids(db_session, [STAGE_ONE_CODE])).status_code == 200
    pm.is_active = False
    db_session.flush()
    sid = _subtask_ids(db_session, STAGE_ONE_CODE)[0]
    _mark_subtask(api_client, project, sid)
    assert _notifications(db_session, pm) == []


# --- leitura, marcação e isolamento -------------------------------------------------------


def test_list_unread_count_and_mark_read_for_own_notifications(db_session, api_client):
    project = _project(db_session, OWN)
    ids = _stage_ids(db_session, [STAGE_ONE_CODE, STAGE_TWO_CODE])
    assert _subscribe(api_client, PM_UM, ids).status_code == 200
    _mark_subtask(api_client, project, _subtask_ids(db_session, STAGE_ONE_CODE)[0])
    _mark_stage(api_client, project, _stage(db_session, STAGE_TWO_CODE))
    assert api_client.get("/api/me/notifications/unread-count", headers=_h(PM_UM)).json()["unread"] == 2

    page = api_client.get("/api/me/notifications?limit=1&offset=0", headers=_h(PM_UM)).json()
    assert page["total"] == 2 and len(page["items"]) == 1
    assert page["items"][0]["project_name"] == OWN and page["items"][0]["stage_title"]
    first_id = page["items"][0]["id"]

    marked = api_client.post(f"/api/me/notifications/{first_id}/read", headers=_h(PM_UM))
    assert marked.status_code == 200 and marked.json()["is_read"] is True
    assert marked.json()["read_at"] is not None
    assert api_client.get("/api/me/notifications/unread-count", headers=_h(PM_UM)).json()["unread"] == 1

    unread = api_client.get("/api/me/notifications?unread_only=true", headers=_h(PM_UM)).json()
    assert unread["total"] == 1 and all(not i["is_read"] for i in unread["items"])

    assert api_client.post("/api/me/notifications/read-all", headers=_h(PM_UM)).json()["marked"] == 1
    assert api_client.get("/api/me/notifications/unread-count", headers=_h(PM_UM)).json()["unread"] == 0
    assert api_client.post("/api/me/notifications/read-all", headers=_h(PM_UM)).json()["marked"] == 0


def test_users_only_see_and_change_their_own_notifications(db_session, api_client):
    project = _project(db_session, OWN)
    assert _subscribe(api_client, PM_UM, _stage_ids(db_session, [STAGE_ONE_CODE])).status_code == 200
    _mark_subtask(api_client, project, _subtask_ids(db_session, STAGE_ONE_CODE)[0])
    pm_note = db_session.query(Notification).filter(Notification.project_id == project.id).one()

    # Admin tem visibilidade total de projetos mas não é o destinatário.
    assert api_client.get("/api/me/notifications", headers=_h(ADMIN)).json()["total"] == 0
    assert api_client.get("/api/me/notifications/unread-count", headers=_h(ADMIN)).json()["unread"] == 0
    assert api_client.post(f"/api/me/notifications/{pm_note.id}/read", headers=_h(ADMIN)).status_code == 404
    assert pm_note.is_read is False  # a alheia não foi tocada

    assert api_client.post(f"/api/me/notifications/{pm_note.id}/read", headers=_h(PM_UM)).status_code == 200


def test_subscriptions_are_per_user_and_unknown_notification_is_404(db_session, api_client):
    ids = _stage_ids(db_session, [STAGE_ONE_CODE])
    assert _subscribe(api_client, PM_UM, ids).status_code == 200
    comercial_view = api_client.get("/api/me/process-alerts/subscriptions", headers=_h(COMERCIAL)).json()
    flags = {s["code"]: s["subscribed"] for p in comercial_view["phases"] for s in p["stages"]}
    assert flags[STAGE_ONE_CODE] is False
    assert api_client.post(f"/api/me/notifications/{uuid.uuid4()}/read", headers=_h(PM_UM)).status_code == 404


def test_subscription_row_points_to_a_real_catalog_stage(db_session):
    # Integridade: a subscrição tem de apontar para uma etapa real do catálogo (FK).
    pm = db_session.query(User).filter(User.email == PM_UM).one()
    stage = _stage(db_session, STAGE_TWO_CODE)
    row = ProcessStageSubscription(user_id=pm.id, stage_id=stage.id)
    db_session.add(row)
    db_session.flush()
    assert row.id is not None
    assert db_session.query(ProcessStageSubscription).filter_by(user_id=pm.id, stage_id=stage.id).count() == 1


# --- migração ---------------------------------------------------------------------------

from tests.test_client_report_permissions_migration import (  # noqa: E402
    _alembic_ok,
    _engine,
    _report_permissions,
    _seed_production_like,
)

PREVIOUS = "e9b1d3f5a7c8"
THIS = "a1c3e5f7b9d2"
PERM = "process_alert.use"


def _grants(engine) -> set[tuple[str, str]]:
    with engine.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT p.code, r.code FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id "
                "JOIN roles r ON r.id = rp.role_id WHERE p.code = :code"
            ),
            {"code": PERM},
        ).all()
    return {(code, role) for code, role in rows}


def _table_exists(engine, name: str) -> bool:
    with engine.connect() as c:
        return c.execute(
            sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"), {"n": name}
        ).first() is not None


def _columns(engine, table: str) -> set[str]:
    with engine.connect() as c:
        return {row[1] for row in c.execute(sa.text(f"PRAGMA table_info({table})")).all()}


def test_migration_upgrade_downgrade_upgrade_on_sqlite(tmp_path: Path):
    database_path = tmp_path / "process-alerts.db"
    _alembic_ok(database_path, "upgrade", PREVIOUS)
    engine = _engine(database_path)
    # Base "de produção": papéis + catálogo SEM process_alert.use (para o provisionar a migração).
    _seed_production_like(engine)
    # O seed copia o catálogo inteiro; apaga a permissão nova para simular a BD antes desta migração.
    with engine.begin() as c:
        pid = c.execute(sa.text("SELECT id FROM permissions WHERE code = :c"), {"c": PERM}).scalar_one()
        c.execute(sa.text("DELETE FROM role_permissions WHERE permission_id = :p"), {"p": pid})
        c.execute(sa.text("DELETE FROM permissions WHERE id = :p"), {"p": pid})
    assert _grants(engine) == set()

    _alembic_ok(database_path, "upgrade", THIS)
    assert _table_exists(engine, "process_stage_subscriptions")
    assert {"project_id", "stage_id", "read_at"} <= _columns(engine, "notifications")
    expected = {
        (PERM, "administrador"),
        (PERM, "chefe_operacoes"),
        (PERM, "project_manager"),
        (PERM, "comercial"),
        (PERM, "financeiro"),
        (PERM, "suporte_operacoes"),
    }
    assert _grants(engine) == expected
    assert _report_permissions(engine)  # o relatório semanal continua intacto

    _alembic_ok(database_path, "downgrade", PREVIOUS)
    assert _grants(engine) == set()
    with engine.connect() as c:
        assert c.execute(sa.text("SELECT COUNT(*) FROM permissions WHERE code = :c"), {"c": PERM}).scalar_one() == 0
    assert not _table_exists(engine, "process_stage_subscriptions")
    assert not ({"project_id", "stage_id", "read_at"} & _columns(engine, "notifications"))

    _alembic_ok(database_path, "upgrade", THIS)
    assert _grants(engine) == expected
