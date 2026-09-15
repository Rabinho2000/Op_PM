"""Indicadores do dashboard inicial — calculados a partir de dados reais
(nunca hardcoded), respeitando a visibilidade de cada perfil. Usa os
projetos/tarefas/ausências sintéticos plantados por
app/migration/seed_dev.py (ver docstrings lá para o cenário de cada um).
"""
from __future__ import annotations

from app.models.project import Project
from app.models.task import Task
from app.utils.timezones import week_range_lisbon


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def test_unauthenticated_request_is_rejected(api_client):
    resp = api_client.get("/api/dashboard/summary")
    assert resp.status_code == 401


def test_chefe_sees_company_wide_scope(api_client):
    resp = api_client.get("/api/dashboard/summary", headers=_headers("chefe.sintetico@example.invalid"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"] == "all"
    assert body["active_projects_count"] >= 7  # 8 seedados, 1 inativo


def test_pm_sees_only_own_scope(api_client):
    resp = api_client.get("/api/dashboard/summary", headers=_headers("pm.um.sintetico@example.invalid"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"] == "own"
    project_names = {p["name"] for p in body["projects_without_pm"]}
    # O PM Um nunca vê "Instalação Sintética Incompleta" (não é o PM dela).
    assert "Instalação Sintética Incompleta" not in project_names


def test_week_uses_europe_lisbon_timezone(api_client):
    resp = api_client.get("/api/dashboard/summary", headers=_headers("chefe.sintetico@example.invalid"))
    body = resp.json()
    expected_start, expected_end = week_range_lisbon()
    assert body["week_start"] == expected_start.isoformat()
    assert body["week_end"] == expected_end.isoformat()


def test_overdue_task_from_seed_is_reported(api_client):
    resp = api_client.get("/api/dashboard/summary", headers=_headers("chefe.sintetico@example.invalid"))
    titles = {(t["project_name"], t["title"]) for t in resp.json()["overdue_tasks"]}
    assert ("Instalação Sintética B — Atrasada", "Preparação da instalação") in titles


def test_project_starting_within_30_days_is_reported(api_client):
    resp = api_client.get("/api/dashboard/summary", headers=_headers("chefe.sintetico@example.invalid"))
    names = {p["name"] for p in resp.json()["projects_starting_next_30_days"]}
    assert "Instalação Sintética A — Início Próximo" in names


def test_projects_without_pm_reported_and_excludes_inactive(api_client):
    resp = api_client.get("/api/dashboard/summary", headers=_headers("chefe.sintetico@example.invalid"))
    names = {p["name"] for p in resp.json()["projects_without_pm"]}
    assert "Instalação Sintética Incompleta" in names
    assert "Instalação Sintética E — Sem PM Atribuído" in names
    # Projeto inativo nunca conta, mesmo sem PM.
    assert "Instalação Sintética H — Inativa" not in names


def test_tasks_of_inactive_projects_never_appear_in_operational_lists(api_client):
    """Regressão: 'Instalação Sintética H — Inativa' tem a checklist
    padrão de tarefas semeada (para testar que projetos inativos nunca
    aparecem no dashboard mesmo com dados associados), mas nunca deve
    gerar 'visitas pendentes'/'comissionamentos pendentes' fantasma."""
    resp = api_client.get("/api/dashboard/summary", headers=_headers("chefe.sintetico@example.invalid"))
    body = resp.json()
    for bucket in ("pending_technical_visits", "pending_commissioning", "overdue_tasks", "tasks_due_this_week", "urgent_tasks"):
        assert all("Inativa" not in t["project_name"] for t in body[bucket]), bucket


def test_urgent_task_from_seed_is_reported(api_client):
    resp = api_client.get("/api/dashboard/summary", headers=_headers("chefe.sintetico@example.invalid"))
    titles = {t["title"] for t in resp.json()["urgent_tasks"]}
    assert "Resolver reclamação urgente do cliente sintético" in titles


def test_cancelled_absence_never_appears_in_dashboard(api_client):
    resp = api_client.get("/api/dashboard/summary", headers=_headers("chefe.sintetico@example.invalid"))
    body = resp.json()
    # A única ausência sintética de "Financeiro Sintético" está cancelada
    # (ver app/migration/seed_dev.py:seed_absences) — nunca deve aparecer.
    all_people = {a["person_display_name"] for a in body["current_absences"] + body["upcoming_absences"]}
    assert "Financeiro Sintético" not in all_people


def test_upcoming_birthday_today_is_reported(api_client):
    resp = api_client.get("/api/dashboard/summary", headers=_headers("chefe.sintetico@example.invalid"))
    names = {b["person_display_name"] for b in resp.json()["upcoming_birthdays"]}
    assert "Comercial Sintético" in names  # seed: aniversário == hoje


def test_pm_without_absence_view_all_only_sees_own_birthday(api_client):
    resp = api_client.get("/api/dashboard/summary", headers=_headers("pm.um.sintetico@example.invalid"))
    names = {b["person_display_name"] for b in resp.json()["upcoming_birthdays"]}
    # PM Um faz anos há 10 dias (fora da janela) — a própria lista fica
    # vazia; nunca deve conter o aniversário de outra pessoa.
    assert "Comercial Sintético" not in names
    assert "Chefe Sintético" not in names


def test_photos_pending_warning_task_type_marks_dashboard_project(db_session, api_client):
    """Não é um indicador dedicado no dashboard — mas confirma que o
    projeto sintético 'Fotos Pendentes' (visita técnica e comissionamento
    concluídos, fotos por colocar) aparece corretamente marcado na lista
    de projetos (ver test_project_task_summary.py para o detalhe)."""
    db = db_session
    project = db.query(Project).filter(Project.name.like("%Fotos Pendentes%")).one()
    open_photo_tasks = (
        db_session.query(Task)
        .filter(Task.project_id == project.id, Task.task_type == "fotos_drive", Task.status != "done")
        .count()
    )
    assert open_photo_tasks == 1
