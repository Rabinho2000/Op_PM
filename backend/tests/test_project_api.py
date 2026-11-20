"""Endpoints de projeto: permissões reais aplicadas no servidor, e
histórico gerado em toda a escrita. Usa `api_client` (mecanismo de
desenvolvimento — X-Dev-User-Email, só local/test) para simular cada
perfil, tal como pedido explicitamente para a Fase 1.
"""
from __future__ import annotations

from app.models.project import Project, ProjectHistory


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def test_pm_can_edit_only_own_project(db_session, api_client):
    db = db_session
    own = db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()
    other = db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()
    assert other.pm_person_id is None  # não é do PM Um

    resp_own = api_client.patch(
        f"/api/projects/{own.id}",
        json={"notes": "Nota sintética editada pelo PM dono."},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_own.status_code == 200
    assert resp_own.json()["notes"] == "Nota sintética editada pelo PM dono."

    resp_other = api_client.patch(
        f"/api/projects/{other.id}",
        json={"notes": "Tentativa indevida."},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp_other.status_code == 403


def test_chefe_operacoes_can_edit_any_authorized_project(db_session, api_client):
    db = db_session
    other = db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()

    resp = api_client.patch(
        f"/api/projects/{other.id}",
        json={"notes": "Editado pelo Chefe de Operações."},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "Editado pelo Chefe de Operações."


def test_comercial_is_read_only(db_session, api_client):
    db = db_session
    project = db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()

    resp_get = api_client.get(f"/api/projects/{project.id}", headers=_headers("comercial.sintetico@example.invalid"))
    assert resp_get.status_code == 200

    resp_list = api_client.get("/api/projects", headers=_headers("comercial.sintetico@example.invalid"))
    assert resp_list.status_code == 200
    assert len(resp_list.json()) >= 1  # project.view_all

    resp_patch = api_client.patch(
        f"/api/projects/{project.id}",
        json={"notes": "Tentativa indevida do comercial."},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert resp_patch.status_code == 403


def test_pm_projects_list_includes_projects_outside_assignment_scope(api_client):
    resp = api_client.get("/api/projects", headers=_headers("pm.um.sintetico@example.invalid"))
    assert resp.status_code == 200
    names = {p["name"] for p in resp.json()}
    assert "Instalação Sintética de Demonstração" in names
    assert "Instalação Sintética Incompleta" in names
    foreign = next(p for p in resp.json() if p["name"] == "Instalação Sintética Incompleta")
    assert foreign["can_change_status"] is True
    assert foreign["editable_fields"] == []
    assert foreign["can_plan_work"] is False
    assert foreign["payments"] is None


def test_history_entry_created_for_every_field_changed(db_session, api_client):
    db = db_session
    project = db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()
    history_before = db.query(ProjectHistory).filter(ProjectHistory.project_id == project.id).count()

    resp = api_client.patch(
        f"/api/projects/{project.id}",
        json={"client_contact": "Contacto Sintético Novo", "role": "supervisor"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 200

    history_after = db.query(ProjectHistory).filter(ProjectHistory.project_id == project.id).count()
    assert history_after == history_before + 2  # um por campo alterado

    latest = (
        db.query(ProjectHistory)
        .filter(ProjectHistory.project_id == project.id)
        .order_by(ProjectHistory.changed_at.desc())
        .limit(2)
        .all()
    )
    assert {h.field_name for h in latest} == {"client_contact", "role"}
    assert all(h.source == "ui" for h in latest)
    assert all(h.changed_by_person_id is not None for h in latest)


def test_history_entry_not_created_when_value_unchanged(db_session, api_client):
    db = db_session
    project = db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()
    history_before = db.query(ProjectHistory).filter(ProjectHistory.project_id == project.id).count()

    resp = api_client.patch(
        f"/api/projects/{project.id}",
        json={"notes": project.notes},  # mesmo valor
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 200
    history_after = db.query(ProjectHistory).filter(ProjectHistory.project_id == project.id).count()
    assert history_after == history_before


def test_no_endpoint_allows_editing_history_directly(api_client):
    """Não existe nenhum endpoint de escrita para project_history — só
    leitura. Confirma que os métodos de escrita comuns não têm rota."""
    resp_post = api_client.post(
        "/api/projects/00000000-0000-0000-0000-000000000000/history",
        json={},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp_post.status_code in (404, 405)


def test_unauthenticated_request_is_rejected(api_client):
    resp = api_client.get("/api/projects")
    assert resp.status_code == 401


_SENSITIVE_BASE_FIELDS = (
    "client_name", "client_contact", "client_email", "address", "lat", "lon", "power_raw",
    "start_date", "installer_id", "installer_team_id", "work_start_date", "work_end_date",
    "clickup_status_mirror", "role", "equipment_notes", "injection_notes", "om_notes",
    "commercial_assumptions", "upac_registration", "m2m_card", "upac_connection_date_raw",
    "award_year_raw", "installer_name", "installer_team_name", "installer_team_leader_name",
    "next_task_title", "next_task_due_date",
)


def _fill_foreign_project(db) -> Project:
    import datetime as dt

    project = db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()
    project.client_name = "Cliente Sintético Alheio"
    project.client_contact = "Contacto Alheio"
    project.client_email = "alheio@example.invalid"
    project.address = "Rua Sintética Alheia 1"
    project.lat = 38.7
    project.lon = -9.1
    project.power_raw = "10,5 kWp"
    project.equipment_notes = "equip alheio"
    project.injection_notes = "inj alheio"
    project.om_notes = "om alheio"
    project.commercial_assumptions = "comercial alheio"
    project.m2m_card = "M2M-ALHEIO"
    project.notes = "nota alheia"
    project.start_date = dt.date(2026, 1, 1)
    db.flush()
    return project


def _assert_redacted(body: dict) -> None:
    assert body["can_view_project_scope"] is False
    for field in _SENSITIVE_BASE_FIELDS:
        assert body[field] in (None, ""), field
    assert body["notes"] == ""
    assert body["payments"] is None
    assert body["has_email"] is False and body["has_contact"] is False and body["has_coordinates"] is False
    assert body["overdue_tasks_count"] == 0 and body["workflow_progress_percent"] == 0
    assert body["photos_pending_warning"] is False and body["has_project_photo"] is False
    assert "alheio" not in str(body).lower()


def test_pm_foreign_project_is_redacted_in_list_detail_and_status(db_session, api_client):
    project = _fill_foreign_project(db_session)
    pm = _headers("pm.um.sintetico@example.invalid")

    detail = api_client.get(f"/api/projects/{project.id}", headers=pm)
    assert detail.status_code == 200
    _assert_redacted(detail.json())
    assert detail.json()["name"] == "Instalação Sintética Incompleta"
    assert detail.json()["can_change_status"] is True

    listed = next(p for p in api_client.get("/api/projects", headers=pm).json() if p["id"] == str(project.id))
    _assert_redacted(listed)

    changed = api_client.patch(
        f"/api/projects/{project.id}/status", json={"lifecycle_status": "construido"}, headers=pm
    )
    assert changed.status_code == 200
    assert changed.json()["project"]["lifecycle_status"] == "construido"
    _assert_redacted(changed.json()["project"])

    db_session.refresh(project)
    assert project.client_email == "alheio@example.invalid"  # ORM intacto


def test_pm_foreign_project_status_is_schema_default_but_lifecycle_is_real(db_session, api_client):
    project = _fill_foreign_project(db_session)
    project.lifecycle_status = "entregue_cliente"  # derivaria status="concluido" a partir das tarefas/ciclo
    db_session.flush()
    pm = _headers("pm.um.sintetico@example.invalid")

    detail = api_client.get(f"/api/projects/{project.id}", headers=pm).json()
    assert detail["status"] == "nao_iniciado"
    assert detail["lifecycle_status"] == "entregue_cliente"

    listed = next(p for p in api_client.get("/api/projects", headers=pm).json() if p["id"] == str(project.id))
    assert listed["status"] == "nao_iniciado"
    assert listed["lifecycle_status"] == "entregue_cliente"


def test_pm_list_search_does_not_match_redacted_fields_of_foreign_projects(db_session, api_client):
    foreign = _fill_foreign_project(db_session)
    own = db_session.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()
    own.client_contact = "Contacto Proprio Unico"
    db_session.flush()
    pm = _headers("pm.um.sintetico@example.invalid")

    def ids(q: str) -> set[str]:
        resp = api_client.get("/api/projects", params={"q": q}, headers=pm)
        assert resp.status_code == 200
        return {p["id"] for p in resp.json()}

    for term in ("Contacto Alheio", "Cliente Sintético Alheio", "alheio@example", "Rua Sintética Alheia", "nota alheia", "M2M-ALHEIO"):
        assert str(foreign.id) not in ids(term), term
    assert str(foreign.id) in ids("Instalação Sintética Incompleta")  # nome continua pesquisável
    # no próprio projeto (escopo normal) mantém-se o comportamento atual
    assert str(own.id) in ids("Contacto Proprio Unico")


def test_pm_sees_full_base_record_on_own_project(db_session, api_client):
    own = db_session.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()
    own.client_email = "proprio@example.invalid"
    own.notes = "nota própria"
    db_session.flush()
    body = api_client.get(f"/api/projects/{own.id}", headers=_headers("pm.um.sintetico@example.invalid")).json()
    assert body["can_view_project_scope"] is True
    assert body["client_email"] == "proprio@example.invalid"
    assert body["notes"] == "nota própria"


def test_pm_list_start_date_filters_never_depend_on_redacted_start_date_of_foreign_projects(db_session, api_client):
    import datetime as dt

    foreign = _fill_foreign_project(db_session)  # start_date 2026-01-01 (redigido para o PM)
    own = db_session.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()
    own.start_date = dt.date(2026, 1, 1)
    db_session.flush()
    pm = _headers("pm.um.sintetico@example.invalid")

    def ids(**params) -> set[str]:
        resp = api_client.get("/api/projects", params=params, headers=pm)
        assert resp.status_code == 200
        return {p["id"] for p in resp.json()}

    # o resultado para o projeto alheio é o mesmo quer a data redigida case ou não com o filtro
    matching = ids(start_from="2025-12-01", start_to="2026-02-01")
    not_matching = ids(start_from="2027-01-01")
    assert str(foreign.id) not in matching
    assert str(foreign.id) not in not_matching
    assert str(own.id) in matching and str(own.id) not in not_matching  # escopo normal mantém-se

    foreign.start_date = dt.date(2030, 5, 5)
    db_session.flush()
    assert str(foreign.id) not in ids(start_from="2025-12-01", start_to="2026-02-01")
    assert str(foreign.id) not in ids(start_from="2027-01-01")


def test_pm_list_status_filter_never_depends_on_task_state_of_foreign_projects(db_session, api_client):
    from app.api import routes_projects

    foreign = _fill_foreign_project(db_session)
    own = db_session.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()
    pm = _headers("pm.um.sintetico@example.invalid")
    chefe = _headers("chefe.sintetico@example.invalid")

    def ids(headers, status: str) -> set[str]:
        resp = api_client.get("/api/projects", params={"status": status}, headers=headers)
        assert resp.status_code == 200
        return {p["id"] for p in resp.json()}

    def snapshot() -> dict[str, set[str]]:
        return {s: ids(pm, s) for s in ("nao_iniciado", "em_curso", "concluido")}

    before = snapshot()
    assert all(str(foreign.id) not in found for found in before.values())

    # mudar o estado real (derivado) do projeto alheio não altera o conjunto devolvido
    foreign.lifecycle_status = "entregue_cliente"  # derivaria status="concluido"
    db_session.flush()
    assert snapshot() == before

    # o estado derivado do projeto alheio nem sequer é calculado para a lista com filtro
    calls: list[object] = []
    real = routes_projects.compute_project_task_summary
    routes_projects.compute_project_task_summary = lambda db, pid: (calls.append(pid), real(db, pid))[1]
    try:
        snapshot()
    finally:
        routes_projects.compute_project_task_summary = real
    assert foreign.id not in calls

    # projeto do próprio PM e chefe continuam a filtrar normalmente
    own_status = next(
        p["status"] for p in api_client.get("/api/projects", headers=pm).json() if p["id"] == str(own.id)
    )
    assert str(own.id) in ids(pm, own_status)
    assert all(str(own.id) not in ids(pm, s) for s in before if s != own_status)
    chefe_status = next(
        p["status"] for p in api_client.get("/api/projects", headers=chefe).json() if p["id"] == str(foreign.id)
    )
    assert chefe_status == "concluido"
    assert str(foreign.id) in ids(chefe, "concluido")
    assert str(foreign.id) not in ids(chefe, "em_curso")


def test_pm_list_order_of_foreign_projects_ignores_redacted_entered_at_and_upac_date(db_session, api_client):
    import datetime as dt

    def foreign(name: str, entered: dt.datetime, upac: str) -> Project:
        p = Project(name=name, lifecycle_status="entregue_cliente", entered_at=entered, upac_connection_date_raw=upac)
        db_session.add(p)
        return p

    zeta = foreign("Zeta Alheio Ordem", dt.datetime(2020, 1, 1), "2020-01-01")
    alfa = foreign("Alfa Alheio Ordem", dt.datetime(2030, 1, 1), "2030-01-01")
    db_session.flush()
    pm = _headers("pm.um.sintetico@example.invalid")

    def order() -> list[str]:
        body = api_client.get("/api/projects", headers=pm).json()
        return [p["id"] for p in body if p["id"] in (str(zeta.id), str(alfa.id))]

    assert order() == [str(alfa.id), str(zeta.id)]  # por nome, não por entered_at/upac
    zeta.entered_at, alfa.entered_at = dt.datetime(2031, 1, 1), dt.datetime(2019, 1, 1)
    zeta.upac_connection_date_raw, alfa.upac_connection_date_raw = None, "2050-01-01"
    db_session.flush()
    assert order() == [str(alfa.id), str(zeta.id)]


def test_chefe_list_order_keeps_entered_at_for_normal_scope(db_session, api_client):
    import datetime as dt

    zeta = Project(name="Zeta Normal Ordem", lifecycle_status="entregue_cliente", entered_at=dt.datetime(2020, 1, 1))
    alfa = Project(name="Alfa Normal Ordem", lifecycle_status="entregue_cliente", entered_at=dt.datetime(2030, 1, 1))
    db_session.add_all([zeta, alfa])
    db_session.flush()
    body = api_client.get("/api/projects", headers=_headers("chefe.sintetico@example.invalid")).json()
    order = [p["id"] for p in body if p["id"] in (str(zeta.id), str(alfa.id))]
    assert order == [str(zeta.id), str(alfa.id)]
