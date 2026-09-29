"""Regression tests for Basic and MCP Bearer authentication."""
import base64


def _basic_header(password: str) -> dict[str, str]:
    encoded = base64.b64encode(f"family:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def test_correct_mcp_bearer_token_is_accepted(client, monkeypatch):
    import auth

    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "test-secret")
    monkeypatch.setattr(auth, "MCP_API_TOKEN", "test-mcp-token")

    assert client.get("/api/kategorien", headers={
        "Authorization": "Bearer test-mcp-token"
    }).status_code == 200


def test_wrong_mcp_bearer_token_is_rejected(client, monkeypatch):
    import auth

    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "MCP_API_TOKEN", "test-mcp-token")

    assert client.get("/api/kategorien", headers={
        "Authorization": "Bearer wrong-token"
    }).status_code == 401


def test_basic_auth_still_works_with_mcp_token_enabled(client, monkeypatch):
    import auth

    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "test-secret")
    monkeypatch.setattr(auth, "MCP_API_TOKEN", "test-mcp-token")

    assert client.get("/api/kategorien", headers=_basic_header("test-secret")).status_code == 200


def test_empty_mcp_token_does_not_bypass_basic_auth(client, monkeypatch):
    import auth

    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "test-secret")
    monkeypatch.setattr(auth, "MCP_API_TOKEN", "")

    assert client.get("/api/kategorien", headers={
        "Authorization": "Bearer ignored-token"
    }).status_code == 401
    assert client.get("/api/kategorien", headers=_basic_header("test-secret")).status_code == 200
