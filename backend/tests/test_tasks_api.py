"""Endpoints de tarefa: CRUD, máquina de estados, atribuição, permissões
por perfil, e histórico gerado em toda a escrita. Mesmo padrão de
tests/test_project_api.py (X-Dev-User-Email, mecanismo de desenvolvimento).
"""
from __future__ import annotations

from app.models.people import Person
from app.models.project import Project
from app.models.task import Task, TaskHistory


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _own_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


def _other_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()


def test_pm_can_create_task_on_own_project(db_session, api_client):
    db = db_session
    project = _own_project(db)

    resp = api_client.post(
        "/api/tasks",
        json={"project_id": str(project.id), "title": "Tarefa ad-hoc do PM", "priority": "high"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "todo"
    assert body["project_id"] == str(project.id)


def test_pm_cannot_create_task_on_project_without_pm(db_session, api_client):
    db = db_session
    other = _other_project(db)
    assert other.pm_person_id is None

    resp = api_client.post(
        "/api/tasks",
        json={"project_id": str(other.id), "title": "Tentativa indevida"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 403


def test_chefe_can_create_task_on_any_project(db_session, api_client):
    db = db_session
    other = _other_project(db)

    resp = api_client.post(
        "/api/tasks",
        json={"project_id": str(other.id), "title": "Tarefa criada pelo Chefe"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 201


def test_comercial_cannot_create_task(db_session, api_client):
    db = db_session
    project = _own_project(db)

    resp = api_client.post(
        "/api/tasks",
        json={"project_id": str(project.id), "title": "Tentativa indevida do comercial"},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert resp.status_code == 403


def test_task_cannot_be_assigned_to_nonexistent_person(db_session, api_client):
    db = db_session
    project = _own_project(db)

    resp = api_client.post(
        "/api/tasks",
        json={
            "project_id": str(project.id),
            "title": "Tarefa com responsável inexistente",
            "assigned_to_person_id": "00000000-0000-0000-0000-000000000000",
        },
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 400


def test_task_reassignment_to_nonexistent_person_rejected_on_update(db_session, api_client):
    db = db_session
    project = _own_project(db)
    task = Task(project_id=project.id, title="Tarefa sintética para reatribuição")
    db.add(task)
    db.commit()

    resp = api_client.patch(
        f"/api/tasks/{task.id}",
        json={"assigned_to_person_id": "00000000-0000-0000-0000-000000000000"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 400


def test_valid_status_transition_updates_history_and_completed_at(db_session, api_client):
    db = db_session
    project = _own_project(db)
    task = Task(project_id=project.id, title="Tarefa sintética de transição")
    db.add(task)
    db.commit()

    resp = api_client.patch(
        f"/api/tasks/{task.id}",
        json={"status": "in_progress"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"
    assert resp.json()["completed_at"] is None

    resp2 = api_client.patch(
        f"/api/tasks/{task.id}",
        json={"status": "done"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "done"
    assert resp2.json()["completed_at"] is not None

    history = db.query(TaskHistory).filter(TaskHistory.task_id == task.id).all()
    status_changes = [h for h in history if h.field_name == "status"]
    assert len(status_changes) == 2


def test_invalid_status_transition_blocked_to_done_is_rejected(db_session, api_client):
    db = db_session
    project = _own_project(db)
    task = Task(project_id=project.id, title="Tarefa sintética bloqueada", status="blocked")
    db.add(task)
    db.commit()

    resp = api_client.patch(
        f"/api/tasks/{task.id}",
        json={"status": "done"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 400


def test_cancelled_task_can_only_reopen_to_todo(db_session, api_client):
    db = db_session
    project = _own_project(db)
    task = Task(project_id=project.id, title="Tarefa sintética cancelada", status="cancelled")
    db.add(task)
    db.commit()

    resp_bad = api_client.patch(
        f"/api/tasks/{task.id}",
        json={"status": "done"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp_bad.status_code == 400

    resp_ok = api_client.patch(
        f"/api/tasks/{task.id}",
        json={"status": "todo"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp_ok.status_code == 200
    assert resp_ok.json()["status"] == "todo"


def test_reopening_done_task_clears_completed_at(db_session, api_client):
    db = db_session
    project = _own_project(db)
    task = Task(project_id=project.id, title="Tarefa sintética concluída")
    db.add(task)
    db.commit()

    api_client.patch(
        f"/api/tasks/{task.id}", json={"status": "done"}, headers=_headers("chefe.sintetico@example.invalid")
    )
    resp = api_client.patch(
        f"/api/tasks/{task.id}", json={"status": "todo"}, headers=_headers("chefe.sintetico@example.invalid")
    )
    assert resp.status_code == 200
    assert resp.json()["completed_at"] is None


def test_pm_can_edit_task_created_by_self_even_off_their_project(db_session, api_client):
    """PM edita tarefas que criou, independentemente do projeto — a posse
    é por identidade (criador/atribuído), não por ser o PM do projeto (ver
    docs/DECISIONS.md, secção de tarefas)."""
    db = db_session
    other = _other_project(db)
    pm = db.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    own_task = Task(project_id=other.id, title="Tarefa criada pelo PM", created_by_person_id=pm.id)
    unrelated_task = Task(project_id=other.id, title="Tarefa de outra pessoa")
    db.add_all([own_task, unrelated_task])
    db.commit()

    resp_own = api_client.patch(
        f"/api/tasks/{own_task.id}",
        json={"notes": "Nota do PM"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_own.status_code == 200

    resp_other = api_client.patch(
        f"/api/tasks/{unrelated_task.id}",
        json={"notes": "Tentativa indevida"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_other.status_code == 403


def test_pm_cannot_edit_task_of_own_project_not_created_by_or_assigned_to_them(db_session, api_client):
    """Um PM já não herda direito de edição só por ser o PM do projeto —
    uma tarefa criada/atribuída a outra pessoa no seu próprio projeto
    continua fora do seu alcance de escrita (só de leitura, via
    task.view_all)."""
    db = db_session
    own = _own_project(db)
    task = Task(project_id=own.id, title="Tarefa de outra pessoa no projeto do PM")
    db.add(task)
    db.commit()

    resp = api_client.patch(
        f"/api/tasks/{task.id}",
        json={"notes": "Tentativa indevida"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 403


def test_pm_cannot_reassign_task_even_one_they_created(db_session, api_client):
    db = db_session
    project = _own_project(db)
    pm = db.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    other_person = db.query(Person).filter(Person.display_name != "PM Sintético Um").first()
    task = Task(project_id=project.id, title="Tarefa do PM", created_by_person_id=pm.id)
    db.add(task)
    db.commit()

    resp = api_client.patch(
        f"/api/tasks/{task.id}",
        json={"assigned_to_person_id": str(other_person.id)},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 400


def test_chefe_can_reassign_any_task(db_session, api_client):
    db = db_session
    project = _own_project(db)
    other_person = db.query(Person).filter(Person.display_name != "PM Sintético Um").first()
    task = Task(project_id=project.id, title="Tarefa para reatribuir")
    db.add(task)
    db.commit()

    resp = api_client.patch(
        f"/api/tasks/{task.id}",
        json={"assigned_to_person_id": str(other_person.id)},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 200
    assert resp.json()["assigned_to_person_id"] == str(other_person.id)


def test_pm_can_only_create_task_assigned_to_self(db_session, api_client):
    db = db_session
    project = _own_project(db)
    other_person = db.query(Person).filter(Person.display_name != "PM Sintético Um").first()

    resp_bad = api_client.post(
        "/api/tasks",
        json={
            "project_id": str(project.id),
            "title": "Tentativa de atribuir a outra pessoa",
            "assigned_to_person_id": str(other_person.id),
        },
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_bad.status_code == 400

    resp_ok = api_client.post(
        "/api/tasks",
        json={"project_id": str(project.id), "title": "Tarefa ad-hoc do PM, sem responsável indicado"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_ok.status_code == 201
    pm = db.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    assert resp_ok.json()["assigned_to_person_id"] == str(pm.id)


def test_pm_can_edit_task_assigned_to_them_even_off_their_project(db_session, api_client):
    """Um PM sem `task.edit_all` pode editar uma tarefa que lhe foi
    atribuída diretamente, mesmo que o projeto não seja o seu (ver
    can_edit_task em app/security/permissions.py)."""
    db = db_session
    other = _other_project(db)
    pm = db.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    task = Task(project_id=other.id, title="Tarefa atribuída pontualmente", assigned_to_person_id=pm.id)
    db.add(task)
    db.commit()

    resp = api_client.patch(
        f"/api/tasks/{task.id}",
        json={"status": "in_progress"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 200


def test_comercial_is_read_only_on_tasks(db_session, api_client):
    db = db_session
    project = _own_project(db)
    task = Task(project_id=project.id, title="Tarefa sintética")
    db.add(task)
    db.commit()

    resp_get = api_client.get(f"/api/tasks/{task.id}", headers=_headers("comercial.sintetico@example.invalid"))
    assert resp_get.status_code == 200

    resp_patch = api_client.patch(
        f"/api/tasks/{task.id}",
        json={"status": "in_progress"},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert resp_patch.status_code == 403


def test_pm_sees_tasks_from_every_project(db_session, api_client):
    """PM tem visibilidade global de tarefas (task.view_all) — só a
    escrita continua restrita a criador/atribuído (ver testes de edição
    acima)."""
    db = db_session
    other = _other_project(db)
    other_task = Task(project_id=other.id, title="Tarefa de outro projeto, visível ao PM")
    db.add(other_task)
    db.commit()

    resp = api_client.get("/api/tasks", headers=_headers("pm.um.sintetico@example.invalid"))
    assert resp.status_code == 200
    ids = {t["id"] for t in resp.json()}
    assert str(other_task.id) in ids

    detail = api_client.get(
        f"/api/tasks/{other_task.id}", headers=_headers("pm.um.sintetico@example.invalid")
    )
    assert detail.status_code == 200
    assert detail.json()["can_edit"] is False


def test_filter_tasks_by_project_and_status(db_session, api_client):
    db = db_session
    project = _own_project(db)
    t1 = Task(project_id=project.id, title="A", status="todo")
    t2 = Task(project_id=project.id, title="B", status="done")
    db.add_all([t1, t2])
    db.commit()

    resp = api_client.get(
        f"/api/tasks?project_id={project.id}&status=done",
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 200
    titles = {t["title"] for t in resp.json()}
    assert "B" in titles
    assert "A" not in titles


def test_unauthenticated_request_is_rejected(api_client):
    resp = api_client.get("/api/tasks")
    assert resp.status_code == 401
