"""Public REST mode keeps administration, Claude costs and MCP access protected."""
import json
from types import SimpleNamespace

import pytest


def _count(table):
    from db import get_db
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
            return cur.fetchone()["n"]


@pytest.fixture()
def claude_search(monkeypatch):
    from routes import ai
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text='[{"titel":"Pasta"}]')],
                               stop_reason="end_turn")

    monkeypatch.setattr(ai, "check_api_key", lambda: None)
    monkeypatch.setattr(ai, "get_claude", lambda: SimpleNamespace(
        messages=SimpleNamespace(create=create)))
    return calls


def test_browser_update_disabled_without_password(client, monkeypatch):
    import config
    from routes import system
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "", raising=False)
    monkeypatch.setattr(config, "AUTH_PASSWORD", "")
    monkeypatch.setattr(system, "latest_release_version", lambda: pytest.fail("update check ran"))
    monkeypatch.setattr(system, "run_update", lambda *_: pytest.fail("update ran"))
    response = client.post("/api/system/update", json={"passwort": ""})
    assert response.status_code == 403
    assert response.json()["detail"] == "Update im Browser ist deaktiviert (ADMIN_PASSWORD in config.py setzen)"
    assert _count("system_updates") == 0


def test_browser_update_uses_admin_password(client, monkeypatch):
    import config
    from routes import system
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "admin-secret", raising=False)
    monkeypatch.setattr(config, "AUTH_PASSWORD", "")
    monkeypatch.setattr(system, "latest_release_version", lambda: "2.4.0")
    monkeypatch.setattr(system, "run_update", lambda *_: None)
    assert client.post("/api/system/update", json={"passwort": "wrong"}).status_code == 403
    assert _count("system_updates") == 0
    assert client.post("/api/system/update", json={"passwort": "admin-secret"}).status_code == 200
    assert _count("system_updates") == 1


@pytest.mark.parametrize("enabled", [False, True])
def test_public_config_reads_runtime_settings(client, monkeypatch, enabled):
    import auth
    import config
    from routes import system
    monkeypatch.setattr(auth, "AUTH_ENABLED", enabled)
    monkeypatch.setattr(config, "AUTH_PASSWORD", "family-secret")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "", raising=False)
    response = client.get("/api/config")
    assert response.status_code == 200
    assert response.json() == {"auth_enabled": enabled, "version": system._app_version(),
                               "update_im_browser": True}
    monkeypatch.setattr(config, "AUTH_PASSWORD", "")
    assert client.get("/api/config").json()["update_im_browser"] is False
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "admin-secret")
    assert client.get("/api/config").json()["update_im_browser"] is True


@pytest.mark.parametrize("name", ["ADMIN_PASSWORD", "MCP_API_TOKEN", "MCP_LOGIN_PASSWORD"])
def test_new_secrets_are_redacted(monkeypatch, name):
    import config
    from routes import system
    monkeypatch.setattr(config, name, "unique-secret-value", raising=False)
    assert system._redact_secrets("failure: unique-secret-value") == "failure: [REDACTED]"


def test_ki_per_ip_limit_and_shared_endpoint_quota(client, monkeypatch, claude_search):
    import config
    import request_utils
    monkeypatch.setattr(config, "KI_LIMIT_PRO_IP_STUNDE", 2, raising=False)
    monkeypatch.setattr(config, "KI_LIMIT_GESAMT_TAG", 0, raising=False)
    monkeypatch.setattr(request_utils, "TRUSTED_PROXIES", {"testclient"})
    for _ in range(2):
        assert client.post("/api/rezept-suche", json={"query": "Pasta"}).status_code == 200
    blocked = client.post("/api/rezept-suche", json={"query": "Pasta"})
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "3600"
    assert blocked.json()["detail"] == "KI-Limit erreicht, bitte später erneut versuchen"
    import routes.ai as ai_routes
    from services.http_guard import SafeResponse
    import httpx
    monkeypatch.setattr(ai_routes, "safe_get", lambda url, **kw: SafeResponse(
        200, httpx.Headers(), b"<html>Rezept</html>", url, "utf-8"))
    assert client.post("/api/analysiere-url", json={"url": "https://example.test"}).status_code == 429
    assert client.post("/api/analysiere-bild", files={
        "file": ("recipe.jpg", b"image", "image/jpeg")}).status_code == 429
    assert client.post("/api/rezept-suche", json={"query": "Pasta"},
                       headers={"X-Real-IP": "192.0.2.2"}).status_code == 200
    assert len(claude_search) == 3
    assert _count("ki_nutzung") == 3


def test_ki_global_limit_across_ips(client, monkeypatch, claude_search):
    import config
    import request_utils
    monkeypatch.setattr(config, "KI_LIMIT_PRO_IP_STUNDE", 0, raising=False)
    monkeypatch.setattr(config, "KI_LIMIT_GESAMT_TAG", 2, raising=False)
    monkeypatch.setattr(request_utils, "TRUSTED_PROXIES", {"testclient"})
    for ip, expected in [("192.0.2.1", 200), ("192.0.2.2", 200), ("192.0.2.3", 429)]:
        response = client.post("/api/rezept-suche", json={"query": "Pasta"},
                               headers={"X-Real-IP": ip})
        assert response.status_code == expected
    assert response.headers["Retry-After"] == "3600"
    assert len(claude_search) == 2
    assert _count("ki_nutzung") == 2


def test_json_import_does_not_use_ki_quota(client, monkeypatch, tmp_path):
    import config
    from routes import ai
    monkeypatch.setattr(config, "KI_LIMIT_PRO_IP_STUNDE", 1, raising=False)
    monkeypatch.setattr(config, "KI_LIMIT_GESAMT_TAG", 1, raising=False)
    monkeypatch.setattr(ai, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(ai, "check_api_key", lambda: pytest.fail("JSON called Claude"))
    recipe = {"format": "rezeptify-recipe/v1", "title": "Pasta", "steps": ["Kochen"]}
    for _ in range(2):
        response = client.post("/api/analysiere-bild", files={
            "file": ("recipe.json", json.dumps(recipe).encode(), "application/json")})
        assert response.status_code == 200
    assert _count("ki_nutzung") == 0


def test_internal_mcp_bridge_without_rest_token(client, monkeypatch):
    import auth
    import mcp_server.auth as mcp_auth
    from tests.test_mcp_endpoint import MCP_HEADERS
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "MCP_API_TOKEN", "")
    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")
    response = client.post("/mcp", headers={
        **MCP_HEADERS, "Authorization": "Bearer test-mcp-token",
    }, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "list_categories", "arguments": {}}})
    assert response.status_code == 200
    assert response.headers["content-type"].split(";", 1)[0] == "application/json"
    result = response.json()["result"]
    assert not result.get("isError"), result
    assert "Hauptgericht" in json.dumps(result)
    assert client.get("/api/kategorien", headers={"rezeptify_internal": "true"}).status_code == 401


def test_cors_settings_restrict_origins():
    import config
    from app import _cors_settings
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.testclient import TestClient
    settings = _cors_settings([config.PUBLIC_BASE_URL])
    assert settings["allow_credentials"] is True
    assert _cors_settings(["*"])["allow_credentials"] is False
    cors_app = FastAPI()
    cors_app.add_middleware(CORSMiddleware, **settings, allow_methods=["*"])
    with TestClient(cors_app) as cors_client:
        for origin, allowed in [("https://foreign.example", False), (config.PUBLIC_BASE_URL, True)]:
            for method in ("GET", "OPTIONS"):
                response = cors_client.request(method, "/", headers={
                    "Origin": origin, "Access-Control-Request-Method": "GET"})
                assert ("access-control-allow-origin" in response.headers) is allowed
                if allowed:
                    assert response.headers["access-control-allow-origin"] == config.PUBLIC_BASE_URL


def test_malformed_basic_header_is_ignored_in_public_mode(client):
    response = client.get("/api/kategorien", headers={"Authorization": "Basic c3RhbGU="})
    assert response.status_code == 200


def test_rest_401_has_no_basic_challenge(client, monkeypatch):
    import auth
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "test-secret")
    for headers in ({}, {"Authorization": "Basic c3RhbGU="}, {"Authorization": "Basic Ondyb25n"}):
        response = client.get("/api/kategorien", headers=headers)
        assert response.status_code == 401
        assert "www-authenticate" not in response.headers
    ok = client.get("/api/kategorien", headers={"Authorization": "Basic OnRlc3Qtc2VjcmV0"})
    assert ok.status_code == 200
