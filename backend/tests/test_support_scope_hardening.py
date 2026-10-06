from __future__ import annotations

import datetime as dt

import pytest
from fastapi import HTTPException

from app.api.routes_people import list_people
from app.api.routes_project_data import get_data_history_endpoint
from app.models.calendar import CalendarEvent
from app.models.identity import User
from app.models.inventory import InventoryCatalogHistory, InventoryItem, InventoryLocation, InventoryMovement
from app.models.people import Person
from app.models.project import Project
from app.models.project_data import ProjectDataHistory
from app.models.task import Task
from app.models.workflow import WorkflowStage
from app.security.permissions import (
    AuthContext,
    can_update_process_stage,
    can_view_task,
)
from app.services.dashboard import compute_dashboard_summary
from app.services.planning import get_visible_event, list_calendar_events
from app.services.tasks import visible_tasks_query


def _ctx(person_id, permissions: set[str], delegated=()) -> AuthContext:
    return AuthContext(
        user=User(person_id=person_id, email="scope-test@example.invalid"),
        person_id=person_id,
        role_codes=frozenset(),
        permission_codes=frozenset(permissions),
        delegating_pm_ids=frozenset(delegated),
    )


def _scenario(db_session):
    support = Person(display_name="Pessoa suporte teste", email="scope-support@example.invalid")
    delegated_pm = Person(display_name="Pessoa PM delegadora", email="scope-pm@example.invalid")
    outside_pm = Person(display_name="Pessoa PM externa", email="scope-outside@example.invalid")
    assigned = Person(display_name="Pessoa atribuída", email="scope-assigned@example.invalid")
    db_session.add_all([support, delegated_pm, outside_pm, assigned])
    db_session.flush()
    delegated_project = Project(name="Projeto delegado de teste", pm_person_id=delegated_pm.id, is_active=True)
    outside_project = Project(name="Projeto fora de teste", pm_person_id=outside_pm.id, is_active=True)
    own_project = Project(name="Projeto próprio de teste", pm_person_id=support.id, is_active=True)
    db_session.add_all([delegated_project, outside_project, own_project])
    db_session.flush()
    return support, delegated_pm, outside_pm, assigned, delegated_project, outside_project, own_project


def _support_ctx(support, delegated_pm):
    return _ctx(
        support.id,
        {
            "project.view_delegated",
            "project.view_installation_data",
            "project.view_licensing_data",
            "workflow.update_progress",
            "task.view_own",
            "task.edit_own",
            "calendar.view",
        },
        delegated=(delegated_pm.id,),
    )


def _http_as(api_client, ctx, method, path, **kwargs):
    from app.main import app
    from app.security.current_user import get_auth_context

    app.dependency_overrides[get_auth_context] = lambda: ctx
    try:
        return getattr(api_client, method)(path, **kwargs)
    finally:
        app.dependency_overrides.pop(get_auth_context, None)


def _inventory_scope_rows(db_session, delegated_project, outside_project):
    item = InventoryItem(sku="SCOPE-ITEM", name="Artigo de âmbito", unit="un")
    central = db_session.query(InventoryLocation).filter_by(location_type="central", is_active=True).one()
    own_location = InventoryLocation(
        code="SCOPE-OWN-LOCATION",
        name="Localização do projeto visível",
        location_type="project",
        project_id=delegated_project.id,
    )
    outside_location = InventoryLocation(
        code="SCOPE-OUTSIDE-LOCATION",
        name="Localização do projeto externo",
        location_type="project",
        project_id=outside_project.id,
    )
    db_session.add_all([item, own_location, outside_location])
    db_session.flush()
    db_session.add_all(
        [
            InventoryMovement(
                item_id=item.id,
                movement_type="entrada",
                quantity="1.000",
                project_id=None,
                location_id=central.id,
                reference="movimento central de âmbito",
            ),
            InventoryMovement(
                item_id=item.id,
                movement_type="reserva",
                quantity="2.000",
                project_id=delegated_project.id,
                location_id=own_location.id,
                reference="movimento do projeto visível",
            ),
            InventoryMovement(
                item_id=item.id,
                movement_type="reserva",
                quantity="3.000",
                project_id=outside_project.id,
                location_id=outside_location.id,
                reference="movimento do projeto externo",
            ),
        ]
    )
    db_session.add_all(
        [
            InventoryCatalogHistory(
                entity_type="item",
                entity_id=item.id,
                action="create",
                changes_json="{}",
            ),
            InventoryCatalogHistory(
                entity_type="location",
                entity_id=central.id,
                action="create",
                changes_json="{}",
            ),
            InventoryCatalogHistory(
                entity_type="location",
                entity_id=own_location.id,
                action="create",
                changes_json="{}",
            ),
            InventoryCatalogHistory(
                entity_type="location",
                entity_id=outside_location.id,
                action="create",
                changes_json="{}",
            ),
        ]
    )
    db_session.flush()
    return item, central, own_location, outside_location


def test_data_history_filters_each_type_and_denies_explicit_forbidden_type(db_session):
    support, delegated_pm, _, _, delegated_project, _, _ = _scenario(db_session)
    support_ctx = _support_ctx(support, delegated_pm)
    db_session.add_all(
        [
            ProjectDataHistory(project_id=delegated_project.id, entity_type="installation", field_name="a", source="ui"),
            ProjectDataHistory(project_id=delegated_project.id, entity_type="licensing", field_name="b", source="ui"),
            ProjectDataHistory(project_id=delegated_project.id, entity_type="communication", field_name="c", source="ui"),
        ]
    )
    db_session.flush()

    visible = get_data_history_endpoint(delegated_project.id, entity_type=None, db=db_session, ctx=support_ctx)
    assert {entry.entity_type for entry in visible} == {"installation", "licensing"}

    with pytest.raises(HTTPException) as denied:
        get_data_history_endpoint(
            delegated_project.id, entity_type="communication", db=db_session, ctx=support_ctx
        )
    assert denied.value.status_code == 403


def test_pm_data_history_still_includes_all_types(db_session):
    _, delegated_pm, _, _, delegated_project, _, _ = _scenario(db_session)
    pm_ctx = _ctx(
        delegated_pm.id,
        {
            "project.view_own",
            "project.view_installation_data",
            "project.view_licensing_data",
            "project.view_communication_data",
        },
    )
    db_session.add_all(
        [
            ProjectDataHistory(project_id=delegated_project.id, entity_type=kind, field_name=kind, source="ui")
            for kind in ("installation", "licensing", "communication")
        ]
    )
    db_session.flush()
    visible = get_data_history_endpoint(delegated_project.id, entity_type=None, db=db_session, ctx=pm_ctx)
    assert {entry.entity_type for entry in visible} == {"installation", "licensing", "communication"}


def test_delegated_only_calendar_scope_covers_projects_and_assigned_unscoped_events(db_session):
    support, delegated_pm, _, assigned, delegated_project, outside_project, _ = _scenario(db_session)
    support_ctx = _support_ctx(support, delegated_pm)
    now = dt.datetime.now(dt.timezone.utc)
    events = [
        CalendarEvent(title="Projeto delegado", starts_at=now, ends_at=now + dt.timedelta(hours=1), project_id=delegated_project.id),
        CalendarEvent(title="Projeto fora", starts_at=now, ends_at=now + dt.timedelta(hours=1), project_id=outside_project.id),
        CalendarEvent(title="Sem projeto atribuído", starts_at=now, ends_at=now + dt.timedelta(hours=1), assigned_to_person_id=support.id),
        CalendarEvent(title="Sem projeto de terceiro", starts_at=now, ends_at=now + dt.timedelta(hours=1), assigned_to_person_id=assigned.id),
        CalendarEvent(title="Sem projeto sem participante", starts_at=now, ends_at=now + dt.timedelta(hours=1)),
    ]
    db_session.add_all(events)
    db_session.flush()

    visible = list_calendar_events(db_session, support_ctx)
    assert {event.title for event in visible} == {"Projeto delegado", "Sem projeto atribuído"}
    assert get_visible_event(db_session, support_ctx, events[0].id) is not None
    assert get_visible_event(db_session, support_ctx, events[1].id) is None
    assert get_visible_event(db_session, support_ctx, events[2].id) is not None
    assert get_visible_event(db_session, support_ctx, events[3].id) is None
    assert get_visible_event(db_session, support_ctx, events[4].id) is None


def test_calendar_scope_for_other_roles_keeps_unscoped_events_visible(db_session):
    support, delegated_pm, _, _, delegated_project, _, _ = _scenario(db_session)
    now = dt.datetime.now(dt.timezone.utc)
    unscoped = CalendarEvent(
        title="Evento interno", starts_at=now, ends_at=now + dt.timedelta(hours=1)
    )
    project_event = CalendarEvent(
        title="Evento projeto", starts_at=now, ends_at=now + dt.timedelta(hours=1), project_id=delegated_project.id
    )
    db_session.add_all([unscoped, project_event])
    db_session.flush()
    other_ctx = _ctx(support.id, {"calendar.view"})
    assert {event.title for event in list_calendar_events(db_session, other_ctx)} == {"Evento interno"}
    assert get_visible_event(db_session, other_ctx, unscoped.id) is not None


def test_composed_project_scopes_are_additive_for_tasks_and_process_stages(db_session):
    support, delegated_pm, _, assigned, delegated_project, outside_project, own_project = _scenario(db_session)
    support_ctx = _support_ctx(support, delegated_pm)
    support_pm_ctx = _ctx(
        support.id,
        set(support_ctx.permission_codes)
        | {
            "project.view_own",
            "project.edit_own_progress",
            "task.view_all",
            "task.edit_own",
        },
        delegated=(delegated_pm.id,),
    )
    support_chief_ctx = _ctx(
        support.id,
        set(support_ctx.permission_codes)
        | {"project.view_all", "project.edit_all", "task.view_all", "task.edit_all"},
        delegated=(delegated_pm.id,),
    )
    delegated_task = Task(project_id=delegated_project.id, title="Tarefa delegada", created_by_person_id=assigned.id)
    outside_task = Task(project_id=outside_project.id, title="Tarefa externa", created_by_person_id=assigned.id)
    assigned_outside = Task(
        project_id=outside_project.id,
        title="Tarefa atribuída ao suporte",
        created_by_person_id=assigned.id,
        assigned_to_person_id=support.id,
    )
    db_session.add_all([delegated_task, outside_task, assigned_outside])
    db_session.flush()

    assert can_view_task(support_ctx, delegated_task) is True
    assert can_view_task(support_ctx, assigned_outside) is False
    assert {task.id for task in visible_tasks_query(db_session, support_ctx).all()} == {delegated_task.id}
    pm_visible = {task.id for task in visible_tasks_query(db_session, support_pm_ctx).all()}
    assert {delegated_task.id, outside_task.id, assigned_outside.id} <= pm_visible
    chief_visible = {task.id for task in visible_tasks_query(db_session, support_chief_ctx).all()}
    assert {delegated_task.id, outside_task.id, assigned_outside.id} <= chief_visible

    support_stage = WorkflowStage(code="support-scope", title="Suporte", responsible_rule="support_delegate")
    pm_stage = WorkflowStage(code="pm-scope", title="PM", responsible_rule="pm")
    assert can_update_process_stage(support_ctx, delegated_project, support_stage) is True
    assert can_update_process_stage(support_ctx, delegated_project, pm_stage) is False
    assert can_update_process_stage(support_pm_ctx, own_project, pm_stage) is True
    assert can_update_process_stage(support_pm_ctx, delegated_project, support_stage) is True
    assert can_update_process_stage(support_pm_ctx, delegated_project, pm_stage) is False
    assert can_update_process_stage(support_chief_ctx, delegated_project, pm_stage) is True


def test_delegated_only_people_include_self_delegating_pms_and_assignees(db_session):
    support, delegated_pm, outside_pm, assigned, delegated_project, outside_project, _ = _scenario(db_session)
    support_ctx = _support_ctx(support, delegated_pm)
    db_session.add_all(
        [
            Task(project_id=delegated_project.id, title="Tarefa no âmbito", assigned_to_person_id=assigned.id),
            Task(project_id=outside_project.id, title="Tarefa fora", assigned_to_person_id=outside_pm.id),
        ]
    )
    db_session.flush()
    people = list_people(db_session, support_ctx)
    assert {person.id for person in people} == {support.id, delegated_pm.id, assigned.id}


def test_people_http_pm_scope_is_limited_and_redacts_email(db_session, api_client):
    _, delegated_pm, outside_pm, assigned, delegated_project, outside_project, _ = _scenario(db_session)
    db_session.add_all(
        [
            Task(project_id=delegated_project.id, title="Tarefa visível", assigned_to_person_id=assigned.id),
            Task(project_id=outside_project.id, title="Tarefa externa", assigned_to_person_id=outside_pm.id),
        ]
    )
    db_session.flush()
    pm_ctx = _ctx(delegated_pm.id, {"project.view_own"})

    response = _http_as(api_client, pm_ctx, "get", "/api/people")

    assert response.status_code == 200, response.text
    rows = response.json()
    assert {row["id"] for row in rows} == {str(delegated_pm.id), str(assigned.id)}
    assert all(row["email"] is None for row in rows)


def test_people_http_support_plus_pm_is_union_and_redacts_email(db_session, api_client):
    support, delegated_pm, outside_pm, assigned, delegated_project, outside_project, _ = _scenario(db_session)
    db_session.add_all(
        [
            Task(project_id=delegated_project.id, title="Tarefa visível", assigned_to_person_id=assigned.id),
            Task(project_id=outside_project.id, title="Tarefa externa", assigned_to_person_id=outside_pm.id),
        ]
    )
    db_session.flush()
    support_ctx = _support_ctx(support, delegated_pm)
    support_pm_ctx = _ctx(
        support.id,
        set(support_ctx.permission_codes) | {"project.view_own"},
        delegated=(delegated_pm.id,),
    )

    response = _http_as(api_client, support_pm_ctx, "get", "/api/people")

    assert response.status_code == 200, response.text
    rows = response.json()
    assert {row["id"] for row in rows} == {str(support.id), str(delegated_pm.id), str(assigned.id)}
    assert all(row["email"] is None for row in rows)


def test_people_http_global_roles_return_email(db_session, api_client):
    support, delegated_pm, outside_pm, assigned, *_ = _scenario(db_session)
    expected = {
        str(person.id): person.email
        for person in (support, delegated_pm, outside_pm, assigned)
    }

    for email in (
        "chefe.sintetico@example.invalid",
        "admin.sintetico@example.invalid",
        # O papel Comercial é a consulta global de leitura no catálogo sintético.
        "comercial.sintetico@example.invalid",
    ):
        response = api_client.get("/api/people", headers={"X-Dev-User-Email": email})
        assert response.status_code == 200, response.text
        by_id = {row["id"]: row for row in response.json()}
        assert set(expected) <= set(by_id)
        assert {person_id: by_id[person_id]["email"] for person_id in expected} == expected


def test_inventory_http_filters_project_scope_but_keeps_central_and_catalog_items(db_session, api_client):
    _, delegated_pm, _, _, delegated_project, outside_project, _ = _scenario(db_session)
    item, central, own_location, outside_location = _inventory_scope_rows(
        db_session, delegated_project, outside_project
    )
    pm_ctx = _ctx(delegated_pm.id, {"inventory.view", "project.view_own"})

    movements = _http_as(api_client, pm_ctx, "get", "/api/inventory/movements")
    locations = _http_as(api_client, pm_ctx, "get", "/api/inventory/locations")
    history = _http_as(api_client, pm_ctx, "get", "/api/inventory/catalog-history")

    assert movements.status_code == 200, movements.text
    assert {row["project_id"] for row in movements.json()} == {None, str(delegated_project.id)}
    assert str(outside_project.id) not in {row["project_id"] for row in movements.json()}
    assert locations.status_code == 200, locations.text
    assert {row["id"] for row in locations.json()} == {str(central.id), str(own_location.id)}
    assert history.status_code == 200, history.text
    assert {
        (row["entity_type"], row["entity_id"])
        for row in history.json()
    } == {
        ("item", str(item.id)),
        ("location", str(central.id)),
        ("location", str(own_location.id)),
    }
    assert str(outside_location.id) not in {row["entity_id"] for row in history.json()}


def test_inventory_http_project_view_all_keeps_external_rows_visible(db_session, api_client):
    support, _, _, _, delegated_project, outside_project, _ = _scenario(db_session)
    item, central, own_location, outside_location = _inventory_scope_rows(
        db_session, delegated_project, outside_project
    )
    chief_ctx = _ctx(support.id, {"inventory.view", "project.view_all"})

    movements = _http_as(api_client, chief_ctx, "get", "/api/inventory/movements")
    locations = _http_as(api_client, chief_ctx, "get", "/api/inventory/locations")
    history = _http_as(api_client, chief_ctx, "get", "/api/inventory/catalog-history")

    assert movements.status_code == 200, movements.text
    assert {row["project_id"] for row in movements.json()} >= {
        str(delegated_project.id),
        str(outside_project.id),
    }
    assert locations.status_code == 200, locations.text
    assert {row["id"] for row in locations.json()} >= {str(central.id), str(own_location.id), str(outside_location.id)}
    assert history.status_code == 200, history.text
    assert ("item", str(item.id)) in {
        (row["entity_type"], row["entity_id"])
        for row in history.json()
    }
    assert str(outside_location.id) in {row["entity_id"] for row in history.json()}


def test_delegated_calendar_event_http_individual_scope_and_writes_are_denied(db_session, api_client):
    support, delegated_pm, _, _, _, outside_project, _ = _scenario(db_session)
    now = dt.datetime.now(dt.timezone.utc)
    outside_event = CalendarEvent(
        title="Evento fora do âmbito",
        starts_at=now,
        ends_at=now + dt.timedelta(hours=1),
        project_id=outside_project.id,
    )
    db_session.add(outside_event)
    db_session.flush()
    support_ctx = _support_ctx(support, delegated_pm)

    detail = _http_as(api_client, support_ctx, "get", f"/api/planning/events/{outside_event.id}")
    create = _http_as(
        api_client,
        support_ctx,
        "post",
        "/api/planning/events",
        json={
            "title": "Evento não permitido",
            "starts_at": now.isoformat(),
            "ends_at": (now + dt.timedelta(hours=1)).isoformat(),
            "project_id": None,
            "task_id": None,
            "assigned_to_person_id": str(support.id),
        },
    )
    update = _http_as(
        api_client,
        support_ctx,
        "patch",
        f"/api/planning/events/{outside_event.id}",
        json={"title": "Tentativa de alteração"},
    )
    cancel = _http_as(api_client, support_ctx, "post", f"/api/planning/events/{outside_event.id}/cancel")
    delegation = _http_as(
        api_client,
        support_ctx,
        "put",
        "/api/support-delegations",
        json={"pm_person_id": str(delegated_pm.id), "support_person_id": str(support.id)},
    )

    assert detail.status_code == 404
    assert create.status_code == 403
    assert update.status_code == 403
    assert cancel.status_code == 403
    assert delegation.status_code == 403


def test_delegated_only_user_cannot_list_global_installers(db_session, api_client):
    support, delegated_pm, _, _, _, _, _ = _scenario(db_session)
    from app.main import app
    from app.security.current_user import get_auth_context

    app.dependency_overrides[get_auth_context] = lambda: _support_ctx(support, delegated_pm)
    try:
        response = api_client.get("/api/installers")
    finally:
        app.dependency_overrides.pop(get_auth_context, None)
    assert response.status_code == 403


def test_delegated_dashboard_reports_delegated_scope(db_session):
    support, delegated_pm, _, _, delegated_project, _, _ = _scenario(db_session)
    summary = compute_dashboard_summary(db_session, _support_ctx(support, delegated_pm))
    assert summary.scope == "delegated"
    assert summary.active_projects_count == 1
    assert {item.id for item in summary.projects_starting_next_30_days} == set()
