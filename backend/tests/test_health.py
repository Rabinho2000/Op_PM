from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_ok_and_integrations_disabled():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    # Fase 0: nenhuma integração real deve estar ativa por omissão.
    assert body["integrations"] == {
        "graph_enabled": False,
        "clickup_enabled": False,
        "financial_enabled": False,
        "claude_enabled": False,
    }


def test_me_requires_dev_header():
    client = TestClient(app)
    resp = client.get("/me")
    assert resp.status_code == 401


def test_me_returns_roles_and_permissions_for_seeded_pm():
    client = TestClient(app)
    resp = client.get("/me", headers={"X-Dev-User-Email": "pm.um.sintetico@example.invalid"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "pm.um.sintetico@example.invalid"
    assert "project_manager" in body["roles"]
    assert "project.edit_own_progress" in body["permissions"]
    assert "project.edit_all" not in body["permissions"]
