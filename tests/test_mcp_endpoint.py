"""Integration tests for the mounted Streamable-HTTP MCP endpoint."""
import json
import logging

from fastapi.testclient import TestClient


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
MCP_HEADERS = {"Accept": "application/json, text/event-stream",
               "MCP-Protocol-Version": "2025-06-18"}


def _initialize(client, headers=None):
    return client.post("/mcp", json=INITIALIZE_REQUEST, headers={
        **MCP_HEADERS, **(headers or {}),
    })


def _sse_result(response):
    if response.headers["content-type"].split(";", 1)[0] == "application/json":
        return response.json()["result"]
    assert response.headers["content-type"].startswith("text/event-stream")
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
    assert response.headers["content-type"].startswith("application/json")
    assert _sse_result(response)["serverInfo"]["name"] == "rezeptify"
    assert b"<html" not in response.content.lower()


def test_mounted_mcp_registers_recipe_read_and_update_tools(client, monkeypatch):
    import mcp_server.auth as mcp_auth

    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")
    initialized = _initialize(client, {"Authorization": "Bearer test-mcp-token"})
    session_id = initialized.headers.get("mcp-session-id")
    response = client.post("/mcp", headers={
        **MCP_HEADERS,
        "Authorization": "Bearer test-mcp-token",
        **({"mcp-session-id": session_id} if session_id else {}),
    }, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

    assert response.status_code == 200
    names = {tool["name"] for tool in _sse_result(response)["tools"]}
    assert {"get_recipe", "update_recipe"} <= names


def test_rest_api_remains_public_when_rest_auth_is_disabled(client):
    response = client.get("/api/kategorien")

    assert response.status_code == 200


def test_tools_list_has_annotations(client, monkeypatch):
    import mcp_server.auth as mcp_auth

    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")
    headers = {"Authorization": "Bearer test-mcp-token"}
    initialized = _initialize(client, headers)
    session_id = initialized.headers.get("mcp-session-id")
    response = client.post("/mcp", headers={
        **MCP_HEADERS, **headers,
        **({"mcp-session-id": session_id} if session_id else {}),
    }, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

    assert response.status_code == 200
    tools = {tool["name"]: tool for tool in _sse_result(response)["tools"]}
    assert tools["search_recipes"]["annotations"]["readOnlyHint"] is True
    assert tools["add_recipe"]["annotations"]["readOnlyHint"] is False
    for name, tool in tools.items():
        assert tool["description"].strip(), name
        assert tool["annotations"] == {
            "readOnlyHint": name not in {"add_recipe", "update_recipe"},
            "destructiveHint": False,
            "idempotentHint": name != "add_recipe",
            "openWorldHint": False,
        }


def test_search_recipes_limit_is_clamped(client, monkeypatch):
    import mcp_server.auth as mcp_auth

    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")
    for request_id, limit in enumerate((500, 0), start=1):
        result = _call_tool(client, {"Authorization": "Bearer test-mcp-token"},
                            None, request_id, "search_recipes", {"limit": limit})

        assert not result.get("isError"), result


def test_mcp_logs_rejected_request(client, monkeypatch, caplog):
    import mcp_server.auth as mcp_auth

    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")
    caplog.set_level(logging.DEBUG, logger="mcp_server.server")

    assert _initialize(client).status_code == 401
    warnings = [record.getMessage() for record in caplog.records
                if record.name == "mcp_server.server" and record.levelno == logging.WARNING]
    assert any("-> 401" in message and "auth=none" in message for message in warnings)
    assert "test-mcp-token" not in caplog.text

    caplog.clear()
    assert _initialize(client, {"Authorization": "Bearer wrong-token"}).status_code == 401
    warnings = [record.getMessage() for record in caplog.records
                if record.name == "mcp_server.server" and record.levelno == logging.WARNING]
    assert any("-> 401" in message and "auth=bearer" in message for message in warnings)
    assert "wrong-token" not in caplog.text
    assert "test-mcp-token" not in caplog.text


def test_tool_success_is_logged(client, monkeypatch, caplog):
    import mcp_server.auth as mcp_auth

    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")
    caplog.set_level(logging.INFO, logger="mcp_server.server")
    result = _call_tool(client, {"Authorization": "Bearer test-mcp-token"},
                        None, 1, "list_categories", {})

    assert not result.get("isError"), result
    assert any(record.name == "mcp_server.server" and record.levelno == logging.INFO
               and "MCP-Tool list_categories ok" in record.getMessage()
               for record in caplog.records)


def _call_tool(client, headers, session_id, request_id, name, arguments):
    response = client.post("/mcp", headers={
        **MCP_HEADERS, **headers,
        **({"mcp-session-id": session_id} if session_id else {}),
    }, json={"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
             "params": {"name": name, "arguments": arguments}})
    assert response.status_code == 200
    return _sse_result(response)


def test_tools_call_without_initialize_session(client, monkeypatch):
    import mcp_server.auth as mcp_auth

    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")
    result = _call_tool(client, {"Authorization": "Bearer test-mcp-token"},
                        None, 1, "list_categories", {})

    assert not result.get("isError"), result
    assert "Hauptgericht" in json.dumps(result)


def test_stale_session_id_is_not_rejected(client, monkeypatch):
    import mcp_server.auth as mcp_auth

    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")
    result = _call_tool(client, {"Authorization": "Bearer test-mcp-token"},
                        "deadbeef-unknown", 1, "list_categories", {})

    assert not result.get("isError"), result
    assert "Hauptgericht" in json.dumps(result)


def test_request_survives_app_restart(monkeypatch):
    from app import app
    import mcp_server.auth as mcp_auth

    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")
    headers = {"Authorization": "Bearer test-mcp-token"}
    with TestClient(app, raise_server_exceptions=False) as first_client:
        initialized = _initialize(first_client, headers)
        assert initialized.status_code == 200
        session_id = initialized.headers.get("mcp-session-id")

    with TestClient(app, raise_server_exceptions=False) as restarted_client:
        result = _call_tool(restarted_client, headers, session_id, 2, "list_categories", {})

    assert not result.get("isError"), result
    assert "Hauptgericht" in json.dumps(result)


def test_mcp_responds_with_json(client, monkeypatch):
    import mcp_server.auth as mcp_auth

    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")
    response = _initialize(client, {"Authorization": "Bearer test-mcp-token"})

    assert response.status_code == 200
    assert response.headers["content-type"].split(";", 1)[0] == "application/json"
    assert _sse_result(response)["serverInfo"]["name"] == "rezeptify"


def test_tools_execute_end_to_end_against_rest_api(client, monkeypatch):
    """Regression: tools must reach the REST API in-process, not via a guessed port."""
    import auth
    import mcp_server.auth as mcp_auth

    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")
    headers = {"Authorization": "Bearer test-mcp-token"}
    session_id = _initialize(client, headers).headers.get("mcp-session-id")

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
    session_id = _initialize(client, headers).headers.get("mcp-session-id")
    result = _call_tool(client, headers, session_id, 2, "list_tags", {})
    assert not result.get("isError"), result
