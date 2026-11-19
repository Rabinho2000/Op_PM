"""`PermissionDenied` -> 403 (handler único), `require_permission` e
`get_visible_project_or_404` (Fase 2, secção 5, itens 1 e 2).

O corpo `{"detail": ...}` dos 403 e 404 é o que o frontend mostra: estes testes
fixam o texto exato de cada variante.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import PROJECT_NOT_FOUND
from app.models.identity import User
from app.models.project import Project
from app.security.current_user import get_auth_context
from app.security.guards import (
    permission_denied_handler,
    permission_denied_message,
    require_permission,
)
from app.security.perm import Perm
from app.security.permissions import AuthContext, PermissionDenied, can_view_project, load_auth_context
from app.services.projects import get_visible_project, visible_projects_query


def _ctx(*perms: Perm) -> AuthContext:
    person_id = uuid.uuid4()
    return AuthContext(
        user=User(person_id=person_id, email="guardas@example.invalid"),
        person_id=person_id,
        role_codes=frozenset(),
        permission_codes=frozenset(perms),
    )


def _client(ctx: AuthContext) -> TestClient:
    app = FastAPI()
    app.add_exception_handler(PermissionDenied, permission_denied_handler)
    app.dependency_overrides[get_auth_context] = lambda: ctx

    @app.get("/require")
    def require_endpoint(ctx: AuthContext = Depends(require_permission(Perm.PROJECT_DELETE))):
        return {"ok": True}

    @app.get("/require-detail")
    def require_detail(
        ctx: AuthContext = Depends(require_permission(Perm.PROJECT_DELETE, detail="Sem permissão para apagar."))
    ):
        return {"ok": True}

    @app.get("/require-reason")
    def require_reason(
        ctx: AuthContext = Depends(
            require_permission(Perm.INVENTORY_VIEW, detail="Sem permissão", with_reason=True)
        )
    ):
        return {"ok": True}

    @app.get("/any-of")
    def any_of(
        ctx: AuthContext = Depends(require_permission(Perm.CALENDAR_VIEW, Perm.MAP_VIEW, detail="Sem acesso."))
    ):
        return {"person": str(ctx.person_id)}

    @app.get("/raised")
    def raised(ctx: AuthContext = Depends(get_auth_context)):
        ctx.require(Perm.PROJECT_RESTORE)

    @app.get("/raised-route-message", dependencies=[Depends(permission_denied_message("Sem permissão para restaurar."))])
    def raised_route_message(ctx: AuthContext = Depends(get_auth_context)):
        ctx.require(Perm.PROJECT_RESTORE)

    @app.get(
        "/raised-route-reason",
        dependencies=[Depends(permission_denied_message("Sem permissão para editar", with_reason=True))],
    )
    def raised_route_reason(ctx: AuthContext = Depends(get_auth_context)):
        raise PermissionDenied(f"{Perm.PROJECT_EDIT_ALL}|{Perm.PROJECT_EDIT_OWN_PROGRESS}")

    @app.get("/raised-explicit", dependencies=[Depends(permission_denied_message("Mensagem da rota"))])
    def raised_explicit(ctx: AuthContext = Depends(get_auth_context)):
        raise PermissionDenied(Perm.PROJECT_RESTORE, detail="Mensagem explícita")

    return TestClient(app)


def test_permission_denied_default_body():
    response = _client(_ctx()).get("/raised")
    assert response.status_code == 403
    assert response.json() == {"detail": "Permissão em falta: project.restore"}


def test_permission_denied_route_message_replaces_the_default():
    response = _client(_ctx()).get("/raised-route-message")
    assert response.status_code == 403
    assert response.json() == {"detail": "Sem permissão para restaurar."}


def test_permission_denied_route_message_with_reason_keeps_the_legacy_format():
    response = _client(_ctx()).get("/raised-route-reason")
    assert response.status_code == 403
    assert response.json() == {
        "detail": "Sem permissão para editar: Permissão em falta: project.edit_all|project.edit_own_progress"
    }


def test_explicit_detail_wins_over_the_route_message():
    assert _client(_ctx()).get("/raised-explicit").json() == {"detail": "Mensagem explícita"}


def test_require_permission_allows_and_returns_the_context():
    ctx = _ctx(Perm.PROJECT_DELETE)
    response = _client(ctx).get("/require")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_require_permission_default_and_custom_detail():
    client = _client(_ctx())
    assert client.get("/require").json() == {"detail": "Permissão em falta: project.delete"}
    assert client.get("/require-detail").json() == {"detail": "Sem permissão para apagar."}
    assert client.get("/require-reason").json() == {"detail": "Sem permissão: Permissão em falta: inventory.view"}
    assert client.get("/require-reason").status_code == 403


def test_require_permission_with_several_permissions_needs_only_one():
    assert _client(_ctx(Perm.MAP_VIEW)).get("/any-of").status_code == 200
    assert _client(_ctx(Perm.CALENDAR_VIEW)).get("/any-of").status_code == 200
    denied = _client(_ctx(Perm.TASK_VIEW_ALL)).get("/any-of")
    assert denied.status_code == 403
    assert denied.json() == {"detail": "Sem acesso."}


def test_require_permission_needs_at_least_one_permission():
    with pytest.raises(ValueError):
        require_permission()


def test_has_permission_accepts_perm_and_the_plain_string():
    ctx = _ctx(Perm.MAP_VIEW)
    assert ctx.has_permission(Perm.MAP_VIEW)
    assert "map.view" in ctx.permission_codes
    assert not ctx.has_permission(Perm.PROJECT_DELETE)


# --- integração com a aplicação real ----------------------------------------

ADMIN = "admin.sintetico@example.invalid"
CHEFE = "chefe.sintetico@example.invalid"
PM = "pm.um.sintetico@example.invalid"
COMERCIAL = "comercial.sintetico@example.invalid"


def _headers(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


@pytest.mark.parametrize(
    "method, path, body, expected",
    [
        ("delete", "/api/projects/{pid}", {"reason": "x"}, "Sem permissão para apagar projetos."),
        ("post", "/api/projects/{pid}/restore", None, "Sem permissão para restaurar projetos."),
        ("get", "/api/projects/deleted", None, "Sem permissão para ver projetos apagados."),
        ("post", "/api/holidays", {"date": "2026-06-13", "name": "x", "scope": "municipal"},
         "Sem permissão para gerir feriados: Permissão em falta: holiday.manage"),
        ("post", "/api/suppliers", {"name": "X"}, "Sem permissão para criar fornecedores."),
        ("post", "/api/installers", {"name": "X"}, "Sem permissão para gerir instaladores e equipas."),
        ("get", "/api/migration/import-batches", None, "Sem permissão para ver dados de migração."),
        ("get", "/api/inventory/categories", None, "Sem permissão: Permissão em falta: inventory.view"),
        ("get", "/api/support-delegations", None, "Permissão em falta: admin.manage_users"),
    ],
)
def test_real_routes_keep_the_403_body(api_client, db_session, method, path, body, expected):
    project = db_session.query(Project).filter(Project.deleted_at.is_(None)).first()
    url = path.format(pid=project.id)
    kwargs = {"json": body} if body is not None else {}
    response = api_client.request(method.upper(), url, headers=_headers(COMERCIAL), **kwargs)
    assert response.status_code == 403, response.text
    assert response.json() == {"detail": expected}


def test_inventory_403_body_has_the_legacy_format(api_client):
    response = api_client.post(
        "/api/inventory/items",
        headers=_headers(COMERCIAL),
        json={"name": "x", "unit": "un", "category": "outro"},
    )
    assert response.status_code == 403, response.text
    assert response.json() == {"detail": "Sem permissão: Permissão em falta: inventory.manage_catalog"}


# --- get_visible_project_or_404 --------------------------------------------


def test_visible_project_dependency_returns_404_for_unknown_and_deleted_projects(api_client, db_session):
    unknown = api_client.get(f"/api/projects/{uuid.uuid4()}/installation-data", headers=_headers(ADMIN))
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": PROJECT_NOT_FOUND}

    project = db_session.query(Project).filter(Project.deleted_at.is_(None)).first()
    ok = api_client.get(f"/api/projects/{project.id}/installation-data", headers=_headers(ADMIN))
    assert ok.status_code == 200, ok.text

    import datetime as dt

    project.deleted_at = dt.datetime.now(dt.timezone.utc)
    db_session.flush()
    gone = api_client.get(f"/api/projects/{project.id}/installation-data", headers=_headers(ADMIN))
    assert gone.status_code == 404
    assert gone.json() == {"detail": PROJECT_NOT_FOUND}


def test_visible_project_dependency_hides_projects_outside_the_scope(api_client, db_session):
    """Um PM só vê os seus projetos: os dos outros dão 404 (nunca 403)."""
    pm_user = db_session.query(User).filter(User.email == PM).one()
    others = (
        db_session.query(Project)
        .filter(Project.deleted_at.is_(None), Project.pm_person_id != pm_user.person_id)
        .all()
    )
    assert others, "o seed devia ter projetos de outros PMs"
    response = api_client.get(f"/api/projects/{others[0].id}/installation-data", headers=_headers(PM))
    assert response.status_code == 404
    assert response.json() == {"detail": PROJECT_NOT_FOUND}


def test_visible_project_dependency_runs_before_the_permission_checks_of_the_route(api_client, db_session):
    """404 antes de 403: quem não vê o projeto nunca descobre se ele existe."""
    response = api_client.get(f"/api/projects/{uuid.uuid4()}/inventory", headers=_headers(COMERCIAL))
    assert response.status_code == 404
    assert response.json() == {"detail": PROJECT_NOT_FOUND}


def test_visible_projects_query_and_can_view_project_agree(db_session):
    """O inventário usava `can_view_project` e as restantes rotas a query SQL de
    visibilidade; a dependência única usa a query, por isso as duas têm de coincidir
    para todos os utilizadores do seed (o inventário mudou de uma para a outra)."""
    projects = db_session.query(Project).all()
    users = db_session.query(User).all()
    assert projects and users
    for user in users:
        ctx = load_auth_context(db_session, user)
        for project in projects:
            visible = get_visible_project(db_session, ctx, project.id) is not None
            assert visible == can_view_project(ctx, project), (user.email, project.name)
        assert {p.id for p in visible_projects_query(db_session, ctx).all()} == {
            p.id for p in projects if can_view_project(ctx, p)
        }
