"""`attention` (green|yellow|red) do mapa operacional — regras de negócio,
segurança (scope de projeto), visibilidade de inventário, cobertura de
coordenadas, e resumo. Ver app/services/map.py e docs/DECISIONS.md.
"""
from __future__ import annotations

import datetime as dt
import uuid

from app.models.inventory import InventoryItem, InventoryMovement, MOVEMENT_RESERVA
from app.models.project import Project
from app.models.task import (
    STATUS_BLOCKED,
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_IN_PROGRESS,
    STATUS_TODO,
    TASK_CATEGORY_DOCUMENTATION,
    TASK_CATEGORY_FIELD,
    TASK_CATEGORY_MATERIAL,
    TASK_CATEGORY_WORKFLOW,
    Task,
)


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _fresh_project(db, *, name: str, pm_person_id=None, lat=None, lon=None) -> Project:
    project = Project(
        name=name,
        client_name="Cliente de teste do mapa",
        pm_person_id=pm_person_id,
        lat=lat,
        lon=lon,
        is_active=True,
    )
    db.add(project)
    db.flush()
    return project


def _map_entry(body: dict, project_id) -> dict:
    for entry in body["projects"] + body["projects_without_coordinates"]:
        if entry["id"] == str(project_id):
            return entry
    raise AssertionError(f"Projeto {project_id} não apareceu no payload do mapa.")


# --- Segurança: uma tarefa atribuída a alguém fora do projeto que gere
#     nunca torna esse projeto visível no mapa (scope é sempre
#     visible_projects_query, nunca visible_tasks_query). ---


def test_task_assigned_to_pm_outside_their_projects_never_leaks_project_on_map(db_session, api_client):
    db = db_session
    other_pm_project = _fresh_project(db, name="Projeto de outro PM (mapa)", pm_person_id=None, lat=1.0, lon=1.0)
    from app.models.people import Person

    pm_um_person = db.query(Person).filter(Person.display_name == "PM Sintético Um").one()

    db.add(
        Task(
            project_id=other_pm_project.id,
            title="Tarefa atribuída fora do âmbito do PM",
            category=TASK_CATEGORY_FIELD,
            status=STATUS_TODO,
            assigned_to_person_id=pm_um_person.id,
        )
    )
    db.commit()

    resp = api_client.get("/api/map/data", headers=_headers("pm.um.sintetico@example.invalid"))
    assert resp.status_code == 200
    body = resp.json()
    ids = {p["id"] for p in body["projects"] + body["projects_without_coordinates"]}
    assert str(other_pm_project.id) not in ids


# --- Regras de attention por categoria/estado ---


def test_workflow_task_open_does_not_affect_attention(db_session, api_client):
    db = db_session
    project = _fresh_project(db, name="Workflow aberto (mapa)", lat=2.0, lon=2.0)
    db.add(Task(project_id=project.id, title="Etapa de workflow", category=TASK_CATEGORY_WORKFLOW, status=STATUS_TODO))
    db.commit()
    resp = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid"))
    entry = _map_entry(resp.json(), project.id)
    assert entry["attention"] == "green"
    assert entry["operational_tasks_count"] == 0


def test_documentation_task_open_does_not_affect_attention(db_session, api_client):
    db = db_session
    project = _fresh_project(db, name="Documentação aberta (mapa)", lat=2.1, lon=2.1)
    db.add(
        Task(
            project_id=project.id, title="Fotos por colocar", category=TASK_CATEGORY_DOCUMENTATION, status=STATUS_TODO
        )
    )
    db.commit()
    resp = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid"))
    entry = _map_entry(resp.json(), project.id)
    assert entry["attention"] == "green"


def test_field_task_todo_is_yellow(db_session, api_client):
    db = db_session
    project = _fresh_project(db, name="Field todo (mapa)", lat=2.2, lon=2.2)
    db.add(Task(project_id=project.id, title="Visita de campo", category=TASK_CATEGORY_FIELD, status=STATUS_TODO))
    db.commit()
    resp = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid"))
    entry = _map_entry(resp.json(), project.id)
    assert entry["attention"] == "yellow"
    assert entry["operational_tasks_count"] == 1


def test_material_task_in_progress_is_yellow(db_session, api_client):
    db = db_session
    project = _fresh_project(db, name="Material in_progress (mapa)", lat=2.3, lon=2.3)
    db.add(
        Task(
            project_id=project.id, title="Recolher material", category=TASK_CATEGORY_MATERIAL, status=STATUS_IN_PROGRESS
        )
    )
    db.commit()
    resp = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid"))
    entry = _map_entry(resp.json(), project.id)
    assert entry["attention"] == "yellow"


def test_field_task_overdue_is_red(db_session, api_client):
    db = db_session
    project = _fresh_project(db, name="Field overdue (mapa)", lat=2.4, lon=2.4)
    db.add(
        Task(
            project_id=project.id,
            title="Visita atrasada",
            category=TASK_CATEGORY_FIELD,
            status=STATUS_TODO,
            due_date=dt.date.today() - dt.timedelta(days=3),
        )
    )
    db.commit()
    resp = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid"))
    entry = _map_entry(resp.json(), project.id)
    assert entry["attention"] == "red"
    assert entry["overdue_operational_tasks_count"] == 1


def test_material_task_urgent_is_red(db_session, api_client):
    db = db_session
    project = _fresh_project(db, name="Material urgente (mapa)", lat=2.5, lon=2.5)
    db.add(
        Task(
            project_id=project.id,
            title="Material urgente",
            category=TASK_CATEGORY_MATERIAL,
            status=STATUS_TODO,
            priority="urgent",
        )
    )
    db.commit()
    resp = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid"))
    entry = _map_entry(resp.json(), project.id)
    assert entry["attention"] == "red"
    assert entry["urgent_operational_tasks_count"] == 1


def test_field_task_blocked_is_red(db_session, api_client):
    db = db_session
    project = _fresh_project(db, name="Field bloqueado (mapa)", lat=2.6, lon=2.6)
    db.add(Task(project_id=project.id, title="Bloqueado", category=TASK_CATEGORY_FIELD, status=STATUS_BLOCKED))
    db.commit()
    resp = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid"))
    entry = _map_entry(resp.json(), project.id)
    assert entry["attention"] == "red"
    assert entry["blocked_operational_tasks_count"] == 1


def test_field_task_done_does_not_count(db_session, api_client):
    db = db_session
    project = _fresh_project(db, name="Field concluído (mapa)", lat=2.7, lon=2.7)
    db.add(
        Task(
            project_id=project.id,
            title="Feito",
            category=TASK_CATEGORY_FIELD,
            status=STATUS_DONE,
            completed_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    db.commit()
    resp = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid"))
    entry = _map_entry(resp.json(), project.id)
    assert entry["attention"] == "green"
    assert entry["operational_tasks_count"] == 0


def test_material_task_cancelled_does_not_count(db_session, api_client):
    db = db_session
    project = _fresh_project(db, name="Material cancelado (mapa)", lat=2.8, lon=2.8)
    db.add(Task(project_id=project.id, title="Cancelado", category=TASK_CATEGORY_MATERIAL, status=STATUS_CANCELLED))
    db.commit()
    resp = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid"))
    entry = _map_entry(resp.json(), project.id)
    assert entry["attention"] == "green"


def test_next_operational_task_is_deterministic_by_due_date(db_session, api_client):
    db = db_session
    project = _fresh_project(db, name="Próxima tarefa (mapa)", lat=2.9, lon=2.9)
    later = Task(
        project_id=project.id,
        title="Mais tarde",
        category=TASK_CATEGORY_FIELD,
        status=STATUS_TODO,
        due_date=dt.date.today() + dt.timedelta(days=10),
    )
    sooner = Task(
        project_id=project.id,
        title="Mais cedo",
        category=TASK_CATEGORY_MATERIAL,
        status=STATUS_TODO,
        due_date=dt.date.today() + dt.timedelta(days=2),
    )
    db.add_all([later, sooner])
    db.commit()
    resp = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid"))
    entry = _map_entry(resp.json(), project.id)
    assert entry["next_operational_task"]["title"] == "Mais cedo"


# --- Inventário: visível/escondido, nunca falso "false" quando sem permissão ---


def test_material_on_site_is_yellow_only_with_inventory_view(db_session, api_client):
    db = db_session
    project = _fresh_project(db, name="Material físico (mapa)", lat=3.0, lon=3.0)
    item = InventoryItem(sku=f"SKU-{uuid.uuid4().hex[:8]}", name="Cabo de teste do mapa", unit="m")
    db.add(item)
    db.flush()
    db.add(
        InventoryMovement(
            item_id=item.id,
            movement_type=MOVEMENT_RESERVA,
            quantity=10,
            project_id=project.id,
        )
    )
    db.commit()

    resp_chefe = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid"))
    entry_chefe = _map_entry(resp_chefe.json(), project.id)
    assert entry_chefe["material_visible"] is True
    assert entry_chefe["has_material_on_site"] is True
    assert entry_chefe["material_sku_count"] == 1
    assert entry_chefe["attention"] == "yellow"

    resp_comercial = api_client.get("/api/map/data", headers=_headers("comercial.sintetico@example.invalid"))
    entry_comercial = _map_entry(resp_comercial.json(), project.id)
    assert entry_comercial["material_visible"] is False
    assert entry_comercial["has_material_on_site"] is None  # nunca `false` — sem permissão, não "sabemos que não há"
    assert entry_comercial["material_sku_count"] is None
    # Material escondido nunca torna o pin amarelo para quem não pode vê-lo.
    assert entry_comercial["attention"] == "green"


def test_two_skus_never_cancel_each_other_out(db_session, api_client):
    db = db_session
    project = _fresh_project(db, name="Dois SKUs (mapa)", lat=3.1, lon=3.1)
    item_a = InventoryItem(sku=f"SKU-A-{uuid.uuid4().hex[:8]}", name="Módulos de teste", unit="un")
    item_b = InventoryItem(sku=f"SKU-B-{uuid.uuid4().hex[:8]}", name="Conectores de teste", unit="un")
    db.add_all([item_a, item_b])
    db.flush()
    db.add(InventoryMovement(item_id=item_a.id, movement_type=MOVEMENT_RESERVA, quantity=5, project_id=project.id))
    db.add(InventoryMovement(item_id=item_b.id, movement_type=MOVEMENT_RESERVA, quantity=3, project_id=project.id))
    db.commit()

    resp = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid"))
    entry = _map_entry(resp.json(), project.id)
    assert entry["has_material_on_site"] is True
    assert entry["material_sku_count"] == 2


# --- Coordenadas: cobertura vs. estado operacional ---


def test_project_without_coordinates_is_unmapped_but_in_summary(db_session, api_client):
    db = db_session
    project = _fresh_project(db, name="Sem coordenadas (mapa)", lat=None, lon=None)
    db.commit()
    resp = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid"))
    body = resp.json()
    names_unmapped = {p["name"] for p in body["projects_without_coordinates"]}
    names_mapped = {p["name"] for p in body["projects"]}
    assert project.name in names_unmapped
    assert project.name not in names_mapped
    assert body["summary"]["unmapped_projects"] >= 1
    assert body["summary"]["visible_active_projects"] >= body["summary"]["mapped_projects"]


# --- Performance: número de queries do endpoint não cresce com o número
#     de projetos (ver docs/DECISIONS.md — nunca uma query por projeto). ---


def test_map_data_query_count_does_not_grow_with_project_count(db_session, api_client):
    from sqlalchemy import event

    from app.db import engine

    def _count_queries() -> int:
        counter = {"n": 0}

        def _on_execute(*_args, **_kwargs):
            counter["n"] += 1

        event.listen(engine, "before_cursor_execute", _on_execute)
        try:
            resp = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid"))
            assert resp.status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", _on_execute)
        return counter["n"]

    baseline = _count_queries()

    # Acrescenta 15 projetos novos, cada um com uma tarefa operacional e um
    # movimento de inventário — o número de queries do endpoint não deve
    # crescer proporcionalmente a isto (nunca uma query por projeto).
    db = db_session
    item = InventoryItem(sku=f"SKU-BULK-{uuid.uuid4().hex[:8]}", name="Item para teste de volume", unit="un")
    db.add(item)
    db.flush()
    for i in range(15):
        project = _fresh_project(db, name=f"Projeto de volume {i}", lat=10.0 + i, lon=10.0 + i)
        db.add(Task(project_id=project.id, title="Tarefa de campo", category=TASK_CATEGORY_FIELD, status=STATUS_TODO))
        db.add(
            InventoryMovement(item_id=item.id, movement_type=MOVEMENT_RESERVA, quantity=1, project_id=project.id)
        )
    db.commit()

    after_bulk = _count_queries()

    # Tolerância generosa (não exatamente igual, mas nunca ~15 queries a
    # mais) — o objetivo é "bounded query count", não um número exato.
    assert after_bulk <= baseline + 3, (
        f"Número de queries cresceu de {baseline} para {after_bulk} ao acrescentar 15 projetos "
        "— indica uma query por projeto (N+1)."
    )


# --- Seed sintético: os 5 cenários do mapa (ver
#     app/migration/seed_dev.py:seed_sample_projects, docs/DECISIONS.md
#     D-058) ficam demonstráveis logo depois de `python -m
#     app.migration.seed_dev`, sem precisar de nenhum passo manual. ---


def test_seed_covers_the_five_map_scenarios(api_client):
    resp = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid"))
    assert resp.status_code == 200
    body = resp.json()
    by_name = {p["name"]: p for p in body["projects"]}

    green = by_name["Instalação Sintética F — PM Legado"]
    assert green["attention"] == "green"

    yellow_field = by_name["Instalação Sintética A — Início Próximo"]
    assert yellow_field["attention"] == "yellow"
    assert yellow_field["operational_tasks_count"] >= 1
    assert yellow_field["has_material_on_site"] is False

    red = by_name["Instalação Sintética B — Atrasada"]
    assert red["attention"] == "red"
    assert red["overdue_operational_tasks_count"] >= 1

    yellow_material = by_name["Instalação Sintética de Demonstração"]
    assert yellow_material["attention"] == "yellow"
    assert yellow_material["operational_tasks_count"] == 0  # amarelo só por material
    assert yellow_material["has_material_on_site"] is True

    unmapped_names = {p["name"] for p in body["projects_without_coordinates"]}
    assert "Instalação Sintética Incompleta" in unmapped_names


def test_summary_counts_and_percentages_are_consistent(db_session, api_client):
    resp = api_client.get("/api/map/data", headers=_headers("chefe.sintetico@example.invalid"))
    body = resp.json()
    summary = body["summary"]
    total = summary["visible_active_projects"]
    assert total == len(body["projects"]) + len(body["projects_without_coordinates"])
    assert summary["mapped_projects"] == len(body["projects"])
    assert summary["green_projects"] + summary["yellow_projects"] + summary["red_projects"] == total
    if total:
        assert summary["map_coverage_percent"] == round(100 * summary["mapped_projects"] / total, 1)
        assert summary["operational_clean_percent"] == round(100 * summary["green_projects"] / total, 1)
