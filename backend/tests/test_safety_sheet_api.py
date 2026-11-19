from __future__ import annotations


from app.models.identity import Role, User, UserRole
from app.models.installer_access import InstallerAccessMembership
from app.models.people import Person
from app.models.project import Project


def _headers(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _own_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


def _other_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()


def test_safety_sheet_get_put_version_and_append_only_history(db_session, api_client):
    project = _own_project(db_session)
    url = f"/api/projects/{project.id}/safety-sheet"
    headers = _headers("pm.um.sintetico@example.invalid")

    initial = api_client.get(url, headers=headers)
    assert initial.status_code == 200
    assert initial.json()["version"] == 0
    assert initial.json()["workers"] == []

    first = api_client.put(
        url,
        headers=headers,
        json={
            "expected_version": 0,
            "roof_type": "telha_ceramica",
            "roof_other": None,
            "approximate_height_m": 6.5,
            "access_method": "escada",
            "access_other": None,
            "risks": ["queda_altura", "eletrico_dc_ac"],
            "risk_other": None,
            "safety_measures": ["linha_vida", "arnes"],
            "measure_other": None,
            "workers": [{"person_id": None, "name": "Trabalhador Externo"}],
            "safety_responsible": "Responsável Sintético",
            "emergency_contacts": "112; Hospital local",
            "observations": "Verificar claraboias",
            "work_start_date": "2026-11-02",
            "work_end_date": "2026-11-04",
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 1
    assert first.json()["workers"][0]["name"] == "Trabalhador Externo"

    second = api_client.put(
        url,
        headers=headers,
        json={
            **first.json(),
            "expected_version": 1,
            "observations": "Trabalho revisto",
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["version"] == 2
    assert second.json()["observations"] == "Trabalho revisto"

    stale = api_client.put(
        url,
        headers=headers,
        json={"expected_version": 1, "observations": "Alteração obsoleta"},
    )
    assert stale.status_code == 409

    history = api_client.get(f"{url}/history", headers=headers)
    assert history.status_code == 200
    assert [entry["version"] for entry in history.json()] == [2, 1]
    assert history.json()[0]["snapshot"]["observations"] == "Trabalho revisto"


def test_safety_sheet_prefill_uses_assigned_team_and_installer_people(db_session, api_client):
    project = _own_project(db_session)
    person = Person(display_name="Trabalhador Associado", email="trabalhador@example.invalid")
    db_session.add(person)
    db_session.flush()
    db_session.add(
        InstallerAccessMembership(
            person_id=person.id,
            installer_id=project.installer_id,
            is_active=True,
        )
    )
    db_session.flush()

    response = api_client.get(
        f"/api/projects/{project.id}/safety-sheet/workers-prefill",
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert response.status_code == 200, response.text
    workers = response.json()["workers"]
    assert any(worker["name"] == "Chefe Sintético Um" for worker in workers)
    assert any(worker["person_id"] == str(person.id) for worker in workers)


def test_safety_sheet_pm_scope_and_installer_is_read_only(db_session, api_client):
    project = _own_project(db_session)
    other = _other_project(db_session)

    own_edit = api_client.put(
        f"/api/projects/{project.id}/safety-sheet",
        headers=_headers("pm.um.sintetico@example.invalid"),
        json={"expected_version": 0, "observations": "Editado pelo PM"},
    )
    assert own_edit.status_code == 200

    unrelated_pm = api_client.get(
        f"/api/projects/{other.id}/safety-sheet",
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert unrelated_pm.status_code == 404

    collaborator = Person(display_name="Colaborador Sintético", email="instalador@example.invalid")
    db_session.add(collaborator)
    db_session.flush()
    role = db_session.query(Role).filter(Role.code == "instalador_colaborador").one()
    user = User(person_id=collaborator.id, email=collaborator.email, is_active=True)
    db_session.add(user)
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.add(
        InstallerAccessMembership(
            person_id=collaborator.id,
            installer_id=project.installer_id,
            is_active=True,
        )
    )
    db_session.flush()

    installer_headers = _headers("instalador@example.invalid")
    read = api_client.get(f"/api/projects/{project.id}/safety-sheet", headers=installer_headers)
    assert read.status_code == 200
    write = api_client.put(
        f"/api/projects/{project.id}/safety-sheet",
        headers=installer_headers,
        json={"expected_version": 1, "observations": "Não permitido"},
    )
    assert write.status_code == 403


def test_safety_sheet_requires_session(db_session, api_client):
    project = _own_project(db_session)
    response = api_client.get(f"/api/projects/{project.id}/safety-sheet")
    assert response.status_code == 401


def test_safety_sheet_print_escapes_user_content(db_session, api_client):
    project = _own_project(db_session)
    response = api_client.put(
        f"/api/projects/{project.id}/safety-sheet",
        headers=_headers("chefe.sintetico@example.invalid"),
        json={"expected_version": 0, "observations": "<script>alert('x')</script>"},
    )
    assert response.status_code == 200, response.text

    printed = api_client.get(f"/api/projects/{project.id}/safety-sheet/print", headers=_headers("comercial.sintetico@example.invalid"))
    assert printed.status_code == 200
    assert printed.headers["content-type"].startswith("text/html")
    assert "<script>alert('x')</script>" not in printed.text
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in printed.text
    assert "@page" in printed.text and "A4" in printed.text


def test_safety_sheet_read_is_available_to_project_viewers_but_write_needs_capability(db_session, api_client):
    project = _own_project(db_session)
    viewer_headers = _headers("comercial.sintetico@example.invalid")
    assert api_client.get(f"/api/projects/{project.id}/safety-sheet", headers=viewer_headers).status_code == 200
    denied = api_client.put(
        f"/api/projects/{project.id}/safety-sheet",
        headers=viewer_headers,
        json={"expected_version": 0, "roof_type": "solo"},
    )
    assert denied.status_code == 403
