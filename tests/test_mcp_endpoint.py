"""Integration tests for the mounted Streamable-HTTP MCP endpoint."""
import json


INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "rezeptify-test", "version": "1.0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def _initialize(client, headers=None):
    return client.post("/mcp", json=INITIALIZE_REQUEST, headers={
        **MCP_HEADERS, **(headers or {}),
    })


def _sse_result(response):
    data_line = next(line for line in response.text.splitlines() if line.startswith("data: "))
    return json.loads(data_line.removeprefix("data: "))["result"]


def test_mcp_rejects_missing_and_wrong_bearer_token(client, monkeypatch):
    import mcp_server.auth as mcp_auth

    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")

    missing = _initialize(client)
    wrong = _initialize(client, {"Authorization": "Bearer wrong-token"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json()["error"] == "invalid_token"


def test_mcp_accepts_correct_bearer_token(client, monkeypatch):
    import mcp_server.auth as mcp_auth

    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")

    response = _initialize(client, {"Authorization": "Bearer test-mcp-token"})

    assert response.status_code == 200
    assert _sse_result(response)["serverInfo"]["name"] == "rezeptify"


def test_mcp_requires_credentials_when_rest_auth_is_disabled(client, monkeypatch):
    import mcp_server.auth as mcp_auth

    monkeypatch.setattr(mcp_auth, "AUTH_ENABLED", False, raising=False)
    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "")
    assert _initialize(client).status_code == 401


def test_static_token_works_when_rest_auth_is_disabled(client, monkeypatch):
    import mcp_server.auth as mcp_auth

    monkeypatch.setattr(mcp_auth, "AUTH_ENABLED", False, raising=False)
    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")

    assert _initialize(client, {"Authorization": "Bearer test-mcp-token"}).status_code == 200


def test_mcp_does_not_fall_through_to_spa(client, monkeypatch):
    import mcp_server.auth as mcp_auth

    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")
    response = _initialize(client, {"Authorization": "Bearer test-mcp-token"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: message" in response.text
    assert b"<html" not in response.content.lower()


def test_mounted_mcp_registers_recipe_read_and_update_tools(client, monkeypatch):
    import mcp_server.auth as mcp_auth

    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")
    initialized = _initialize(client, {"Authorization": "Bearer test-mcp-token"})
    session_id = initialized.headers["mcp-session-id"]
    response = client.post("/mcp", headers={
        **MCP_HEADERS,
        "Authorization": "Bearer test-mcp-token",
        "mcp-session-id": session_id,
    }, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

    assert response.status_code == 200
    names = {tool["name"] for tool in _sse_result(response)["tools"]}
    assert {"get_recipe", "update_recipe"} <= names


def test_rest_api_remains_public_when_rest_auth_is_disabled(client):
    response = client.get("/api/kategorien")

    assert response.status_code == 200


def _call_tool(client, headers, session_id, request_id, name, arguments):
    response = client.post("/mcp", headers={
        **MCP_HEADERS, **headers, "mcp-session-id": session_id,
    }, json={"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
             "params": {"name": name, "arguments": arguments}})
    assert response.status_code == 200
    return _sse_result(response)


def test_tools_execute_end_to_end_against_rest_api(client, monkeypatch):
    """Regression: tools must reach the REST API in-process, not via a guessed port."""
    import auth
    import mcp_server.auth as mcp_auth

    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")
    headers = {"Authorization": "Bearer test-mcp-token"}
    session_id = _initialize(client, headers).headers["mcp-session-id"]

    categories = _call_tool(client, headers, session_id, 2, "list_categories", {})
    assert not categories.get("isError")

    created = _call_tool(client, headers, session_id, 3, "add_recipe", {
        "title": "Testbrisket", "steps": ["Rub auftragen.", "Lange garen."],
        "ingredients": [
            {"amount": "2", "unit": "kg", "name": "Rinderbrust", "group": "Hauptzutat"},
            {"amount": "", "unit": "", "name": "Butterflocken"},
        ],
        "category": "Fleisch", "tags": ["BBQ"], "servings": 10, "difficulty": "schwer",
    })
    assert not created.get("isError"), created
    found = _call_tool(client, headers, session_id, 4, "search_recipes", {"query": "Testbrisket"})
    assert not found.get("isError"), found
    assert "Testbrisket" in json.dumps(found)


def test_tools_work_when_rest_auth_is_enabled(client, monkeypatch):
    import auth
    import mcp_server.auth as mcp_auth
    import mcp_server.server as server_module

    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "family-secret")
    monkeypatch.setattr(auth, "MCP_API_TOKEN", "test-mcp-token")
    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")
    headers = {"Authorization": "Bearer test-mcp-token"}
    session_id = _initialize(client, headers).headers["mcp-session-id"]
    result = _call_tool(client, headers, session_id, 2, "list_tags", {})
    assert not result.get("isError"), result
