"""MVP de demonstração (D-051): extensões aditivas da API usadas pela UI
nova, flag DEMO_MODE, e o seed de demonstração local.

Tudo contra os dados sintéticos de app/migration/seed_dev.py (e, nos
testes do seed demo, app/migration/seed_demo.py dentro da transação
isolada de `db_session`, desfeita no fim de cada teste).
"""
from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from app.cli.demo import main as demo_main
from app.config import Settings
from app.migration.seed_demo import (
    DEMO_MARKER_PROJECT_NAME,
    DEMO_PROJECTS,
    DemoSeedNotAllowedError,
    assert_demo_allowed_environment,
    seed_demo_data,
)
from app.models.identity import User
from app.models.project import Project
from app.security.project_fields import PM_EDITABLE_PROJECT_FIELDS
from app.utils.timezones import today_lisbon, week_range_lisbon

CHEFE = {"X-Dev-User-Email": "chefe.sintetico@example.invalid"}
PM = {"X-Dev-User-Email": "pm.um.sintetico@example.invalid"}
COMERCIAL = {"X-Dev-User-Email": "comercial.sintetico@example.invalid"}


# --- /health e /me ---------------------------------------------------------


def test_health_reports_demo_flags(api_client):
    body = api_client.get("/health").json()
    assert body["demo_mode"] is False  # DEMO_MODE não definido nos testes
    assert body["dev_login_available"] is True  # APP_ENV=test, AUTH_ENABLED=false


def test_me_includes_display_name_and_role_labels(api_client):
    body = api_client.get("/me", headers=CHEFE).json()
    assert body["display_name"] == "Chefe Sintético"
    assert body["role_labels"] == ["Chefe de Operações"]


# --- DEMO_MODE nunca aceite em staging/produção ------------------------------


def _hardened_kwargs(app_env: str, **overrides) -> dict:
    base = dict(
        app_env=app_env,
        auth_enabled=True,
        secret_key="a-real-secret-value",
        database_url="postgresql+psycopg://user:pass@host:5432/op_pm",
        entra_tenant_id="11111111-1111-1111-1111-111111111111",
        entra_client_id="22222222-2222-2222-2222-222222222222",
        entra_required_scope="access_as_user",
        cors_allowed_origins="https://op-pm.example.invalid",
    )
    base.update(overrides)
    return base


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_demo_mode_blocks_startup_in_hardened_envs(app_env):
    with pytest.raises(ValidationError, match="DEMO_MODE"):
        Settings(**_hardened_kwargs(app_env, demo_mode=True))


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_hardened_envs_start_without_demo_mode(app_env):
    assert Settings(**_hardened_kwargs(app_env)).demo_mode is False


def test_demo_mode_allowed_in_local():
    assert Settings(app_env="local", demo_mode=True).demo_mode is True


# --- Dashboard: fotografias pendentes e resumo da semana ---------------------


def test_dashboard_reports_projects_with_photos_pending(api_client):
    body = api_client.get("/api/dashboard/summary", headers=CHEFE).json()
    names = {p["name"] for p in body["projects_photos_pending"]}
    assert "Instalação Sintética C — Fotos Pendentes" in names
    # Projeto sem visita/comissionamento concluído nunca gera o aviso.
    assert "Instalação Sintética A — Início Próximo" not in names


def test_dashboard_photos_pending_respects_pm_scope(api_client):
    body = api_client.get("/api/dashboard/summary", headers=PM).json()
    project_ids = {p["id"] for p in body["projects_photos_pending"]}
    visible_ids = {p["id"] for p in api_client.get("/api/projects", headers=PM).json()}
    assert project_ids <= visible_ids


def test_dashboard_week_overview_covers_the_lisbon_week(api_client):
    body = api_client.get("/api/dashboard/summary", headers=CHEFE).json()
    week_start, week_end = week_range_lisbon()
    days = body["week_overview"]
    assert [d["date"] for d in days] == [
        (week_start + dt.timedelta(days=i)).isoformat() for i in range(7)
    ]
    assert days[-1]["date"] == week_end.isoformat()
    # Mesma regra de "pendente esta semana" — as contagens diárias somam o total.
    assert sum(d["tasks_due_count"] for d in days) == len(body["tasks_due_this_week"])
    # A ausência sintética em curso (PM Um) conta hoje.
    today = next(d for d in days if d["date"] == today_lisbon().isoformat())
    assert today["people_absent_count"] >= 1


def test_dashboard_week_overview_counts_completed_tasks(api_client):
    # A tarefa de comissionamento do projeto C foi concluída pelo seed "agora".
    body = api_client.get("/api/dashboard/summary", headers=CHEFE).json()
    assert sum(d["tasks_completed_count"] for d in body["week_overview"]) >= 1


# --- Projetos: filtros e permissões efetivas ---------------------------------


def test_projects_filter_by_derived_status(api_client):
    body = api_client.get("/api/projects?status=em_curso", headers=CHEFE).json()
    assert body, "o seed tem projetos em curso"
    assert all(p["status"] == "em_curso" for p in body)
    names = {p["name"] for p in body}
    assert "Instalação Sintética B — Atrasada" in names


def test_projects_reject_unknown_status(api_client):
    resp = api_client.get("/api/projects?status=qualquer", headers=CHEFE)
    assert resp.status_code == 400


def test_projects_filter_by_start_date_range(api_client):
    today = dt.date.today()
    resp = api_client.get(
        f"/api/projects?start_from={today.isoformat()}&start_to={(today + dt.timedelta(days=30)).isoformat()}",
        headers=CHEFE,
    )
    names = {p["name"] for p in resp.json()}
    assert "Instalação Sintética A — Início Próximo" in names
    assert "Instalação Sintética B — Atrasada" not in names
    assert all(p["start_date"] is not None for p in resp.json())


def test_editable_fields_reflect_permissions(api_client):
    chefe_view = api_client.get("/api/projects", headers=CHEFE).json()
    demo = next(p for p in chefe_view if p["name"] == "Instalação Sintética de Demonstração")
    assert "name" in demo["editable_fields"] and "pm_person_id" in demo["editable_fields"]
    assert demo["can_manage_tasks"] is True

    pm_view = api_client.get(f"/api/projects/{demo['id']}", headers=PM).json()
    assert set(pm_view["editable_fields"]) == set(PM_EDITABLE_PROJECT_FIELDS)
    assert pm_view["can_manage_tasks"] is True

    comercial_view = api_client.get(f"/api/projects/{demo['id']}", headers=COMERCIAL).json()
    assert comercial_view["editable_fields"] == []
    assert comercial_view["can_manage_tasks"] is False


# --- Tarefas: filtro de prioridade e can_edit --------------------------------


def test_tasks_filter_by_priority(api_client):
    body = api_client.get("/api/tasks?priority=urgent", headers=CHEFE).json()
    assert body
    assert all(t["priority"] == "urgent" for t in body)


def test_task_can_edit_flag(api_client):
    chefe_tasks = api_client.get("/api/tasks", headers=CHEFE).json()
    assert all(t["can_edit"] for t in chefe_tasks)
    comercial_tasks = api_client.get("/api/tasks", headers=COMERCIAL).json()
    assert comercial_tasks and not any(t["can_edit"] for t in comercial_tasks)


# --- Ausências: can_cancel ---------------------------------------------------


def test_absence_can_cancel_flag(api_client):
    chefe_view = api_client.get("/api/absences", headers=CHEFE).json()
    for absence in chefe_view:
        assert absence["can_cancel"] is (absence["status"] == "aprovada")

    pm_view = api_client.get("/api/absences", headers=PM).json()
    assert pm_view
    assert all(a["can_cancel"] for a in pm_view if a["status"] == "aprovada")


# --- Seed de demonstração ------------------------------------------------------


@pytest.mark.parametrize("app_env", ["test", "staging", "production"])
def test_demo_seed_only_allowed_in_local(app_env):
    with pytest.raises(DemoSeedNotAllowedError, match="APP_ENV=local"):
        assert_demo_allowed_environment(app_env)


def test_demo_seed_allowed_in_local():
    assert_demo_allowed_environment("local")  # não levanta


def test_demo_cli_refuses_outside_local(capsys):
    # A suite corre com APP_ENV=test — o comando recusa antes de tocar na base.
    assert demo_main(["setup"]) == 1
    assert "APP_ENV=local" in capsys.readouterr().err


def test_demo_seed_adds_synthetic_projects_idempotently(db_session):
    users_before = db_session.query(User).count()
    projects_before = db_session.query(Project).count()

    assert seed_demo_data(db_session) is True
    assert db_session.query(Project).count() == projects_before + len(DEMO_PROJECTS)
    assert db_session.query(User).count() == users_before  # nunca cria contas de login

    assert seed_demo_data(db_session) is False  # segunda vez não faz nada
    assert db_session.query(Project).count() == projects_before + len(DEMO_PROJECTS)

    marker = db_session.query(Project).filter(Project.name == DEMO_MARKER_PROJECT_NAME).one()
    assert marker.client_email.endswith("@example.invalid")
    emails = [p.client_email for p in db_session.query(Project).all() if p.client_email]
    assert all(e.endswith(".invalid") for e in emails)


def test_demo_seed_feeds_every_dashboard_indicator(api_client, db_session):
    seed_demo_data(db_session)
    db_session.commit()
    body = api_client.get("/api/dashboard/summary", headers=CHEFE).json()
    for key in (
        "projects_starting_next_30_days",
        "overdue_tasks",
        "pending_technical_visits",
        "pending_commissioning",
        "projects_without_pm",
        "projects_missing_data",
        "current_absences",
        "upcoming_absences",
        "upcoming_birthdays",
        "urgent_tasks",
        "projects_photos_pending",
    ):
        assert body[key], key
    assert body["active_projects_count"] >= 7 + len(DEMO_PROJECTS)
