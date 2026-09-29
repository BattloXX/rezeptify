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


def test_rest_api_remains_public_when_rest_auth_is_disabled(client):
    response = client.get("/api/kategorien")

    assert response.status_code == 200
