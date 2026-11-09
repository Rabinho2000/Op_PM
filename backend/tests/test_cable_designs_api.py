"""Backend contract for project-linked cable dimensioning studies."""
from __future__ import annotations

import json
import threading
import uuid

from sqlalchemy import text

from app.models.identity import Role, User, UserRole
from app.models.people import Person
from app.models.project import Project


def _headers(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _user_for_role(db_session, role_code: str, label: str) -> User:
    email = f"{label.lower().replace(' ', '-')}@example.invalid"
    person = Person(display_name=label, email=email, is_active=True)
    db_session.add(person)
    db_session.flush()
    user = User(person_id=person.id, email=email, is_active=True)
    db_session.add(user)
    db_session.flush()
    role = db_session.query(Role).filter(Role.code == role_code).one()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.flush()
    return user


def _project(db_session, person_id, label: str = "Project A") -> Project:
    project = Project(name=label, pm_person_id=person_id, lifecycle_status=None, is_active=True)
    db_session.add(project)
    db_session.flush()
    return project


def _input() -> dict[str, object]:
    return {"format": 1, "circuits": [{"code": "C1", "length_m": 10}]}


def _native_input(*, inverter_count: int = 1) -> dict[str, object]:
    return {
        "format": 1,
        "state": {
            "invs": [{"modelo": f"INV-{index + 1}"} for index in range(inverter_count)],
            "percs": [],
        },
    }


def _valid_result(
    *,
    engine_version: str = "engine-test-1",
    review: bool = False,
    inverters: int = 1,
) -> dict[str, object]:
    return {
        "format": 1,
        "engine_version": engine_version,
        "circuits": [{"code": "C1", "name": "Circuito 1", "review": review}],
        "totals": {"circuits": 1, "review": int(review), "inverters": inverters},
    }


def _create(api_client, project: Project, email: str, *, input_payload: object = ...):
    payload = {
        "title": "Estudo A",
        "input_json": _input() if input_payload is ... else input_payload,
        "engine_version": "engine-test-1",
    }
    return api_client.post(
        f"/api/projects/{project.id}/cable-designs",
        json=payload,
        headers=_headers(email),
    )


def test_cable_design_create_list_detail_update_and_hash(api_client, db_session):
    user = _user_for_role(db_session, "project_manager", "PM A")
    project = _project(db_session, user.person_id)

    created = _create(api_client, project, user.email)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["title"] == "Estudo A"
    assert body["project_id"] == str(project.id)
    assert body["current_revision"] == "A"
    assert body["version"] == 1
    assert body["revision"]["input_json"] == _input()
    assert body["revision"]["result_json"] == {}
    assert body["revision"]["status"] == "rascunho"

    listed = api_client.get(
        f"/api/projects/{project.id}/cable-designs", headers=_headers(user.email)
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["unresolved_circuits"] == 0

    design_id = body["id"]
    updated_result = {"format": 1, "circuits": [{"code": "C1", "review": False}]}
    updated = api_client.put(
        f"/api/cable-designs/{design_id}/revisions/current",
        json={
            "expected_version": 1,
            "title": "Estudo A actualizado",
            "input": _input(),
            "result": updated_result,
            "engine_version": "engine-test-2",
        },
        headers=_headers(user.email),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert updated.json()["revision"]["engine_version"] == "engine-test-2"
    assert updated.json()["revision"]["content_sha256"]

    detail = api_client.get(
        f"/api/cable-designs/{design_id}", headers=_headers(user.email)
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["revision"]["result_json"] == updated_result


def test_cable_design_approval_immutability_and_new_revision(api_client, db_session):
    user = _user_for_role(db_session, "project_manager", "PM A")
    project = _project(db_session, user.person_id)
    created = _create(api_client, project, user.email)
    design_id = created.json()["id"]

    pending = api_client.put(
        f"/api/cable-designs/{design_id}/revisions/current",
        json={
            "expected_version": 1,
            "input": _input(),
            "result": _valid_result(review=True),
            "engine_version": "engine-test-1",
        },
        headers=_headers(user.email),
    )
    assert pending.status_code == 200
    blocked = api_client.post(
        f"/api/cable-designs/{design_id}/approve",
        json={"expected_version": 2},
        headers=_headers(user.email),
    )
    assert blocked.status_code == 409

    saved = api_client.put(
        f"/api/cable-designs/{design_id}/revisions/current",
        json={
            "expected_version": 2,
            "input": _input(),
            "result": _valid_result(review=False),
            "engine_version": "engine-test-1",
        },
        headers=_headers(user.email),
    )
    assert saved.status_code == 200
    approved = api_client.post(
        f"/api/cable-designs/{design_id}/approve",
        json={"expected_version": 3},
        headers=_headers(user.email),
    )
    assert approved.status_code == 200, approved.text
    approved_version = approved.json()["version"]

    immutable = api_client.put(
        f"/api/cable-designs/{design_id}/revisions/current",
        json={
            "expected_version": approved_version,
            "input": _input(),
            "result": {"format": 1},
            "engine_version": "engine-test-3",
        },
        headers=_headers(user.email),
    )
    assert immutable.status_code == 423

    revision = api_client.post(
        f"/api/cable-designs/{design_id}/new-revision",
        json={"expected_version": approved_version},
        headers=_headers(user.email),
    )
    assert revision.status_code == 201, revision.text
    assert revision.json()["current_revision"] == "B"
    assert revision.json()["revision"]["rev"] == "B"
    assert revision.json()["revision"]["status"] == "rascunho"
    assert revision.json()["revision"]["input_json"] == _input()


def test_cable_design_scope_and_capability_fail_closed(api_client, db_session):
    owner = _user_for_role(db_session, "project_manager", "PM A")
    other = _user_for_role(db_session, "project_manager", "PM B")
    commercial = _user_for_role(db_session, "comercial", "PM C")
    owned = _project(db_session, owner.person_id, "Project A")
    foreign = _project(db_session, other.person_id, "Project B")
    created = _create(api_client, owned, owner.email)
    design_id = created.json()["id"]

    foreign_list = api_client.get(
        f"/api/projects/{foreign.id}/cable-designs", headers=_headers(owner.email)
    )
    assert foreign_list.status_code == 404
    foreign_detail = api_client.get(
        f"/api/cable-designs/{design_id}", headers=_headers(other.email)
    )
    assert foreign_detail.status_code == 404
    no_capability = api_client.get(
        f"/api/cable-designs/{uuid.uuid4()}", headers=_headers(commercial.email)
    )
    assert no_capability.status_code == 403
    no_capability_project = api_client.get(
        f"/api/projects/{uuid.uuid4()}/cable-designs", headers=_headers(commercial.email)
    )
    assert no_capability_project.status_code == 403


def test_cable_design_payload_shapes_are_422_not_500(api_client, db_session):
    user = _user_for_role(db_session, "project_manager", "PM A")
    project = _project(db_session, user.person_id)
    for value in ([], {}, 123, None):
        response = _create(api_client, project, user.email, input_payload=value)
        assert response.status_code == 422, (value, response.text)

    invalid_body_values = [[], {}, 123, None]
    created = _create(api_client, project, user.email)
    design_id = created.json()["id"]
    for value in invalid_body_values:
        response = api_client.put(
            f"/api/cable-designs/{design_id}/revisions/current",
            json={
                "expected_version": 1,
                "input": value,
                "result": {},
                "engine_version": "engine-test-1",
            },
            headers=_headers(user.email),
        )
        assert response.status_code == 422, (value, response.text)


def test_cable_design_history_is_transactional_and_short(db_session, api_client, monkeypatch):
    user = _user_for_role(db_session, "project_manager", "PM A")
    project = _project(db_session, user.person_id)
    created = _create(api_client, project, user.email)
    design_id = created.json()["id"]

    from app.services import cable_designs

    def fail_history(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(cable_designs, "_append_history", fail_history)
    response = api_client.put(
        f"/api/cable-designs/{design_id}/revisions/current",
        json={
            "expected_version": 1,
            "input": _input(),
            "result": {"format": 1},
            "engine_version": "engine-test-2",
        },
        headers=_headers(user.email),
    )
    assert response.status_code == 503
    replay = api_client.get(
        f"/api/cable-designs/{design_id}", headers=_headers(user.email)
    )
    assert replay.status_code == 200
    assert replay.json()["version"] == 1
    assert db_session.execute(
        text("SELECT COUNT(*) FROM cable_design_history WHERE design_id = :id"),
        {"id": design_id},
    ).scalar_one() == 1


def test_cable_design_stale_update_conflicts_without_mutation(api_client, db_session):
    user = _user_for_role(db_session, "project_manager", "PM A")
    project = _project(db_session, user.person_id)
    created = _create(api_client, project, user.email)
    design_id = created.json()["id"]

    current = api_client.put(
        f"/api/cable-designs/{design_id}/revisions/current",
        json={
            "expected_version": 1,
            "title": "Estudo actual",
            "input": {"format": 1, "source": "current"},
            "result": {"format": 1, "winner": "current"},
            "engine_version": "engine-current",
        },
        headers=_headers(user.email),
    )
    assert current.status_code == 200, current.text

    stale_marker = f"stale-{uuid.uuid4().hex}"
    stale = api_client.put(
        f"/api/cable-designs/{design_id}/revisions/current",
        json={
            "expected_version": 1,
            "title": stale_marker,
            "input": {"format": 1, "source": stale_marker},
            "result": {"format": 1, "winner": stale_marker},
            "engine_version": "engine-stale",
        },
        headers=_headers(user.email),
    )
    assert stale.status_code == 409, stale.text

    replay = api_client.get(
        f"/api/cable-designs/{design_id}", headers=_headers(user.email)
    )
    assert replay.status_code == 200, replay.text
    replay_body = replay.json()
    assert replay_body["version"] == 2
    assert replay_body["title"] == "Estudo actual"
    assert replay_body["revision"]["input_json"] == {"format": 1, "source": "current"}
    assert replay_body["revision"]["result_json"] == {"format": 1, "winner": "current"}
    assert stale_marker not in replay.text

    history = api_client.get(
        f"/api/cable-designs/{design_id}/history", headers=_headers(user.email)
    )
    assert history.status_code == 200, history.text
    assert [entry["action"] for entry in history.json()] == ["created", "saved"]


def test_cable_design_concurrent_same_version_has_one_success_and_one_conflict(
    tmp_path, monkeypatch
):
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    from app import config, db
    from app.db import Base, get_db
    from app.main import app
    from app.migration.seed_dev import seed_catalog

    monkeypatch.setenv(
        "DATABASE_URL", f"sqlite:///{(tmp_path / 'cable-design-concurrency.db').as_posix()}"
    )
    config.get_settings.cache_clear()
    local_engine = db._make_engine()
    SessionFactory = sessionmaker(bind=local_engine, autoflush=False, future=True)

    try:
        from app import (
            models as _models,  # noqa: F401 - register every mapped table before create_all
        )

        Base.metadata.create_all(bind=local_engine)
        setup_session = SessionFactory()
        try:
            seed_catalog(setup_session)
            user = _user_for_role(setup_session, "project_manager", "Concurrent PM")
            project = _project(setup_session, user.person_id, "Concurrent Project")
            setup_session.commit()
            email = user.email
            project_id = str(project.id)
        finally:
            setup_session.close()

        def override_get_db():
            session = SessionFactory()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as client:
            created = client.post(
                f"/api/projects/{project_id}/cable-designs",
                json={
                    "title": "Concurrent Study",
                    "input_json": _input(),
                    "engine_version": "engine-concurrency-0",
                },
                headers=_headers(email),
            )
            assert created.status_code == 201, created.text
            design_id = created.json()["id"]

        barrier = threading.Barrier(2)
        responses: list[tuple[int, str]] = []
        errors: list[str] = []
        guard = threading.Lock()

        def update_in_parallel(label: str) -> None:
            try:
                with TestClient(app) as client:
                    barrier.wait(timeout=10)
                    response = client.put(
                        f"/api/cable-designs/{design_id}/revisions/current",
                        json={
                            "expected_version": 1,
                            "input": _input(),
                            "result": {"format": 1, "winner": label},
                            "engine_version": f"engine-{label}",
                        },
                        headers=_headers(email),
                    )
                    with guard:
                        responses.append((response.status_code, response.text))
            except BaseException as exc:  # noqa: BLE001 - expose thread failures
                with guard:
                    errors.append(f"{type(exc).__name__}: {exc}")

        threads = [
            threading.Thread(target=update_in_parallel, args=("one",)),
            threading.Thread(target=update_in_parallel, args=("two",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert all(not thread.is_alive() for thread in threads), threads
        assert errors == []
        assert len(responses) == 2
        assert sorted(status for status, _ in responses) == [200, 409], responses
        assert sum(status == 200 for status, _ in responses) == 1
        winning_body = next(body for status, body in responses if status == 200)
        assert json.loads(winning_body)["version"] == 2

        with TestClient(app) as client:
            replay = client.get(
                f"/api/cable-designs/{design_id}", headers=_headers(email)
            )
        assert replay.status_code == 200, replay.text
        assert replay.json()["version"] == 2
    finally:
        app.dependency_overrides.pop(get_db, None)
        local_engine.dispose()
        monkeypatch.undo()
        config.get_settings.cache_clear()


def test_cable_design_delegated_support_is_read_only(api_client, db_session):
    from app.models.workflow import SupportDelegation

    owner = _user_for_role(db_session, "project_manager", "PM A")
    support = _user_for_role(db_session, "suporte_operacoes", "Suporte A")
    project = _project(db_session, owner.person_id, "Delegated Project")
    db_session.add(
        SupportDelegation(
            pm_person_id=owner.person_id,
            support_person_id=support.person_id,
        )
    )
    db_session.flush()
    created = _create(api_client, project, owner.email)
    assert created.status_code == 201, created.text
    design_id = created.json()["id"]

    listed = api_client.get(
        f"/api/projects/{project.id}/cable-designs", headers=_headers(support.email)
    )
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [design_id]
    detail = api_client.get(
        f"/api/cable-designs/{design_id}", headers=_headers(support.email)
    )
    assert detail.status_code == 200, detail.text

    create_forbidden = api_client.post(
        f"/api/projects/{project.id}/cable-designs",
        json={
            "title": "Support Write",
            "input_json": _input(),
            "engine_version": "engine-support",
        },
        headers=_headers(support.email),
    )
    assert create_forbidden.status_code == 403, create_forbidden.text

    update_forbidden = api_client.put(
        f"/api/cable-designs/{design_id}/revisions/current",
        json={
            "expected_version": 1,
            "input": _input(),
            "result": {"format": 1},
            "engine_version": "engine-support",
        },
        headers=_headers(support.email),
    )
    assert update_forbidden.status_code == 403, update_forbidden.text

    approve_forbidden = api_client.post(
        f"/api/cable-designs/{design_id}/approve",
        json={"expected_version": 1},
        headers=_headers(support.email),
    )
    assert approve_forbidden.status_code == 403, approve_forbidden.text


def test_cable_design_project_with_null_lifecycle_is_active_for_create_and_list(
    api_client, db_session
):
    user = _user_for_role(db_session, "project_manager", "PM A")
    project = _project(db_session, user.person_id, "Null Lifecycle Project")
    assert project.lifecycle_status is None
    created = _create(api_client, project, user.email)
    assert created.status_code == 201, created.text

    listed = api_client.get(
        f"/api/projects/{project.id}/cable-designs", headers=_headers(user.email)
    )
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [created.json()["id"]]


def test_cable_design_oversized_input_and_result_are_sanitized_4xx(
    api_client, db_session
):
    user = _user_for_role(db_session, "project_manager", "PM A")
    project = _project(db_session, user.person_id)

    input_marker = f"oversized-input-{uuid.uuid4().hex}"
    oversized_input = {
        "format": 1,
        "payload": input_marker + ("x" * (2 * 1024 * 1024)),
    }
    input_response = _create(
        api_client, project, user.email, input_payload=oversized_input
    )
    assert 400 <= input_response.status_code < 500, input_response.text
    assert input_response.status_code != 500
    assert input_marker not in input_response.text

    created = _create(api_client, project, user.email)
    assert created.status_code == 201, created.text
    design_id = created.json()["id"]
    result_marker = f"oversized-result-{uuid.uuid4().hex}"
    oversized_result = {
        "format": 1,
        "payload": result_marker + ("y" * (2 * 1024 * 1024)),
    }
    result_response = api_client.put(
        f"/api/cable-designs/{design_id}/revisions/current",
        json={
            "expected_version": 1,
            "input": _input(),
            "result": oversized_result,
            "engine_version": "engine-test-oversized",
        },
        headers=_headers(user.email),
    )
    assert 400 <= result_response.status_code < 500, result_response.text
    assert result_response.status_code != 500
    assert result_marker not in result_response.text

    replay = api_client.get(
        f"/api/cable-designs/{design_id}", headers=_headers(user.email)
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["version"] == 1
    assert replay.json()["revision"]["result_json"] == {}


def test_cable_design_approve_with_unresolved_circuits_conflicts_without_change(
    api_client, db_session
):
    user = _user_for_role(db_session, "project_manager", "PM A")
    project = _project(db_session, user.person_id)
    created = _create(api_client, project, user.email)
    design_id = created.json()["id"]

    pending = api_client.put(
        f"/api/cable-designs/{design_id}/revisions/current",
        json={
            "expected_version": 1,
            "input": _input(),
            "result": _valid_result(engine_version="engine-review", review=True),
            "engine_version": "engine-review",
        },
        headers=_headers(user.email),
    )
    assert pending.status_code == 200, pending.text
    before = api_client.get(
        f"/api/cable-designs/{design_id}", headers=_headers(user.email)
    )
    assert before.status_code == 200, before.text
    before_body = before.json()

    blocked = api_client.post(
        f"/api/cable-designs/{design_id}/approve",
        json={"expected_version": 2},
        headers=_headers(user.email),
    )
    assert blocked.status_code == 409, blocked.text

    after = api_client.get(
        f"/api/cable-designs/{design_id}", headers=_headers(user.email)
    )
    assert after.status_code == 200, after.text
    after_body = after.json()
    assert after_body["version"] == before_body["version"] == 2
    assert after_body["status"] == before_body["status"] == "rascunho"
    assert after_body["revision"]["status"] == before_body["revision"]["status"] == "rascunho"
    assert after_body["revision"]["unresolved_circuits"] == 1
    assert after_body["revision"]["result_json"] == before_body["revision"]["result_json"]

    history = api_client.get(
        f"/api/cable-designs/{design_id}/history", headers=_headers(user.email)
    )
    assert history.status_code == 200, history.text
    assert [entry["action"] for entry in history.json()] == ["created", "saved"]


def test_cable_design_delete_stale_conflicts_then_deactivates_and_keeps_history(
    api_client, db_session
):
    user = _user_for_role(db_session, "project_manager", "PM A")
    project = _project(db_session, user.person_id)
    created = _create(api_client, project, user.email)
    design_id = created.json()["id"]

    saved = api_client.put(
        f"/api/cable-designs/{design_id}/revisions/current",
        json={
            "expected_version": 1,
            "input": _input(),
            "result": {"format": 1},
            "engine_version": "engine-saved",
        },
        headers=_headers(user.email),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 2

    stale_delete = api_client.delete(
        f"/api/cable-designs/{design_id}?expected_version=1",
        headers=_headers(user.email),
    )
    assert stale_delete.status_code == 409, stale_delete.text

    still_listed = api_client.get(
        f"/api/projects/{project.id}/cable-designs", headers=_headers(user.email)
    )
    assert still_listed.status_code == 200, still_listed.text
    assert [item["id"] for item in still_listed.json()] == [design_id]

    deleted = api_client.delete(
        f"/api/cable-designs/{design_id}?expected_version=2",
        headers=_headers(user.email),
    )
    assert deleted.status_code == 204, deleted.text

    listed_after_delete = api_client.get(
        f"/api/projects/{project.id}/cable-designs", headers=_headers(user.email)
    )
    assert listed_after_delete.status_code == 200, listed_after_delete.text
    assert listed_after_delete.json() == []

    history_rows = db_session.execute(
        text(
            "SELECT action FROM cable_design_history "
            "WHERE design_id = :id ORDER BY created_at, id"
        ),
        {"id": design_id},
    ).scalars().all()
    assert len(history_rows) == 3
    assert history_rows.count("deactivated") == 1


def test_cable_design_approval_rejects_initial_empty_result_without_mutation(
    api_client, db_session
):
    user = _user_for_role(db_session, "project_manager", "PM Empty")
    project = _project(db_session, user.person_id, "Empty Result Project")
    created = _create(api_client, project, user.email)
    assert created.status_code == 201, created.text
    design_id = created.json()["id"]

    blocked = api_client.post(
        f"/api/cable-designs/{design_id}/approve",
        json={"expected_version": 1},
        headers=_headers(user.email),
    )
    assert blocked.status_code == 409, blocked.text

    replay = api_client.get(
        f"/api/cable-designs/{design_id}", headers=_headers(user.email)
    )
    assert replay.status_code == 200, replay.text
    body = replay.json()
    assert body["version"] == 1
    assert body["status"] == "rascunho"
    assert body["revision"]["status"] == "rascunho"
    assert body["revision"]["result_json"] == {}
    history = api_client.get(
        f"/api/cable-designs/{design_id}/history", headers=_headers(user.email)
    )
    assert history.status_code == 200, history.text
    assert [entry["action"] for entry in history.json()] == ["created"]


def test_cable_design_approval_rejects_empty_and_malformed_result_payloads(
    api_client, db_session
):
    user = _user_for_role(db_session, "project_manager", "PM Guard")
    project = _project(db_session, user.person_id, "Guard Project")

    missing_result = _create(api_client, project, user.email)
    assert missing_result.status_code == 201, missing_result.text
    missing_body = {
        "expected_version": 1,
        "input": _input(),
        "engine_version": "engine-test-1",
    }
    missing = api_client.put(
        f"/api/cable-designs/{missing_result.json()['id']}/revisions/current",
        json=missing_body,
        headers=_headers(user.email),
    )
    assert missing.status_code == 422, missing.text

    malformed_results = [
        {},
        {"format": 1},
        {
            "format": 1,
            "engine_version": "engine-test-1",
            "circuits": [],
            "totals": {"circuits": 0, "review": 0, "inverters": 0},
        },
        {
            "format": 1,
            "engine_version": "engine-test-1",
            "circuits": [{"code": "C1", "name": "Circuito 1", "review": "false"}],
            "totals": {"circuits": 1, "review": 0, "inverters": 1},
        },
        {
            "format": 1,
            "engine_version": "engine-test-1",
            "circuits": [{"code": "C1", "name": "Circuito 1", "review": False}],
            "totals": {"circuits": 2, "review": 0, "inverters": 1},
        },
        {
            "format": 1,
            "engine_version": "engine-test-1",
            "circuits": [{"code": "C1", "name": "Circuito 1", "review": False}],
            "totals": {"circuits": 1, "review": 0, "inverters": 2},
        },
        {
            "format": 1,
            "engine_version": "engine-test-1",
            "circuits": [{"code": "x" * 257, "name": "Circuito 1", "review": False}],
            "totals": {"circuits": 1, "review": 0, "inverters": 1},
        },
        {
            "format": 1,
            "engine_version": "engine-test-1",
            "circuits": [{"code": "C1", "name": "Circuito 1", "review": False}],
            "totals": {"circuits": 1, "review": 0, "inverters": 1, "kw_ac": 1_000_001},
        },
    ]
    for index, result in enumerate(malformed_results):
        created = _create(api_client, project, user.email)
        assert created.status_code == 201, created.text
        design_id = created.json()["id"]
        saved = api_client.put(
            f"/api/cable-designs/{design_id}/revisions/current",
            json={
                "expected_version": 1,
                "input": _input(),
                "result": result,
                "engine_version": "engine-test-1",
            },
            headers=_headers(user.email),
        )
        assert saved.status_code == 200, (index, saved.text)
        before = api_client.get(
            f"/api/cable-designs/{design_id}", headers=_headers(user.email)
        )
        assert before.status_code == 200, before.text
        before_body = before.json()

        blocked = api_client.post(
            f"/api/cable-designs/{design_id}/approve",
            json={"expected_version": 2},
            headers=_headers(user.email),
        )
        assert blocked.status_code == 409, (index, blocked.text)

        after = api_client.get(
            f"/api/cable-designs/{design_id}", headers=_headers(user.email)
        )
        assert after.status_code == 200, after.text
        after_body = after.json()
        assert after_body["version"] == before_body["version"] == 2
        assert after_body["status"] == before_body["status"] == "rascunho"
        assert after_body["revision"]["status"] == before_body["revision"]["status"] == "rascunho"
        assert after_body["revision"]["result_json"] == before_body["revision"]["result_json"]

    invalid_shapes = [[], None, 123]
    created = _create(api_client, project, user.email)
    assert created.status_code == 201, created.text
    for value in invalid_shapes:
        response = api_client.put(
            f"/api/cable-designs/{created.json()['id']}/revisions/current",
            json={
                "expected_version": 1,
                "input": _input(),
                "result": value,
                "engine_version": "engine-test-1",
            },
            headers=_headers(user.email),
        )
        assert response.status_code == 422, (value, response.text)


def test_cable_design_approval_rejects_huge_kw_ac_without_mutation(
    api_client, db_session
):
    user = _user_for_role(db_session, "project_manager", "PM Huge KW")
    project = _project(db_session, user.person_id, "Huge KW Project")
    created = _create(api_client, project, user.email)
    assert created.status_code == 201, created.text
    design_id = created.json()["id"]

    result: dict[str, object] = _valid_result()
    totals = result["totals"]
    assert isinstance(totals, dict)
    totals["kw_ac"] = 10**999
    saved = api_client.put(
        f"/api/cable-designs/{design_id}/revisions/current",
        json={
            "expected_version": 1,
            "input": _input(),
            "result": result,
            "engine_version": "engine-test-1",
        },
        headers=_headers(user.email),
    )
    assert saved.status_code == 200, saved.text

    before = api_client.get(
        f"/api/cable-designs/{design_id}", headers=_headers(user.email)
    )
    assert before.status_code == 200, before.text
    before_body = before.json()
    history_before = api_client.get(
        f"/api/cable-designs/{design_id}/history", headers=_headers(user.email)
    )
    assert history_before.status_code == 200, history_before.text
    history_before_body = history_before.json()

    blocked = api_client.post(
        f"/api/cable-designs/{design_id}/approve",
        json={"expected_version": 2},
        headers=_headers(user.email),
    )
    assert blocked.status_code == 409, blocked.text

    after = api_client.get(
        f"/api/cable-designs/{design_id}", headers=_headers(user.email)
    )
    assert after.status_code == 200, after.text
    assert after.json() == before_body
    history_after = api_client.get(
        f"/api/cable-designs/{design_id}/history", headers=_headers(user.email)
    )
    assert history_after.status_code == 200, history_after.text
    assert history_after.json() == history_before_body


def test_cable_design_approval_accepts_native_persisted_result_and_state(
    api_client, db_session
):
    user = _user_for_role(db_session, "project_manager", "PM Native")
    project = _project(db_session, user.person_id, "Native Project")
    created = _create(api_client, project, user.email)
    assert created.status_code == 201, created.text
    design_id = created.json()["id"]

    saved = api_client.put(
        f"/api/cable-designs/{design_id}/revisions/current",
        json={
            "expected_version": 1,
            "input": _native_input(inverter_count=1),
            "result": _valid_result(),
            "engine_version": "engine-test-1",
        },
        headers=_headers(user.email),
    )
    assert saved.status_code == 200, saved.text

    approved = api_client.post(
        f"/api/cable-designs/{design_id}/approve",
        json={"expected_version": 2},
        headers=_headers(user.email),
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "aprovado"
    assert body["revision"]["status"] == "aprovada"


def test_cable_design_approval_rechecks_persisted_counter_and_content(
    api_client, db_session
):
    from app.models.cable_designs import CableDesignRevision

    user = _user_for_role(db_session, "project_manager", "PM Recheck")
    project = _project(db_session, user.person_id, "Recheck Project")
    created = _create(api_client, project, user.email)
    assert created.status_code == 201, created.text
    design_id = created.json()["id"]
    saved = api_client.put(
        f"/api/cable-designs/{design_id}/revisions/current",
        json={
            "expected_version": 1,
            "input": _native_input(),
            "result": _valid_result(),
            "engine_version": "engine-test-1",
        },
        headers=_headers(user.email),
    )
    assert saved.status_code == 200, saved.text

    revision = db_session.query(CableDesignRevision).filter_by(design_id=design_id).one()
    revision.unresolved_circuits = 1
    db_session.flush()
    blocked_counter = api_client.post(
        f"/api/cable-designs/{design_id}/approve",
        json={"expected_version": 2},
        headers=_headers(user.email),
    )
    assert blocked_counter.status_code == 409, blocked_counter.text

    revision.unresolved_circuits = 0
    revision.result_json = json.dumps({"format": 1}, separators=(",", ":"))
    db_session.flush()
    blocked_content = api_client.post(
        f"/api/cable-designs/{design_id}/approve",
        json={"expected_version": 2},
        headers=_headers(user.email),
    )
    assert blocked_content.status_code == 409, blocked_content.text

    replay = api_client.get(
        f"/api/cable-designs/{design_id}", headers=_headers(user.email)
    )
    assert replay.status_code == 200, replay.text
    body = replay.json()
    assert body["version"] == 2
    assert body["status"] == "rascunho"
    assert body["revision"]["status"] == "rascunho"


def test_cable_design_approval_rejects_canonical_result_without_corresponding_state(
    api_client, db_session
):
    user = _user_for_role(db_session, "project_manager", "PM No State")
    project = _project(db_session, user.person_id, "No State Project")
    created = _create(api_client, project, user.email)
    assert created.status_code == 201, created.text
    design_id = created.json()["id"]

    saved = api_client.put(
        f"/api/cable-designs/{design_id}/revisions/current",
        json={
            "expected_version": 1,
            "input": {"format": 1},
            "result": _valid_result(),
            "engine_version": "engine-test-1",
        },
        headers=_headers(user.email),
    )
    assert saved.status_code == 200, saved.text
    blocked = api_client.post(
        f"/api/cable-designs/{design_id}/approve",
        json={"expected_version": 2},
        headers=_headers(user.email),
    )
    assert blocked.status_code == 409, blocked.text


def test_cable_design_without_session_returns_401(api_client):
    response = api_client.get(f"/api/projects/{uuid.uuid4()}/cable-designs")
    assert response.status_code == 401, response.text
