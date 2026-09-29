"""MariaDB-backed OAuth 2.1 integration tests for the remote MCP endpoint."""
from urllib.parse import parse_qs, urlparse


REDIRECT_URI = "http://connector.test/callback"
VERIFIER = "a" * 43
CHALLENGE = "ZtNPunH49FD35FWYhT5Tv8I7vRKQJ8uxMaL0_9eHjNA"


def _enable_oauth(monkeypatch):
    import mcp_server.auth as mcp_auth
    import routes.mcp_auth as login
    monkeypatch.setattr(mcp_auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")
    monkeypatch.setattr(login, "AUTH_ENABLED", True)
    monkeypatch.setattr(login, "AUTH_PASSWORD", "test-secret")


def _register(client):
    response = client.post("/register", json={
        "redirect_uris": [REDIRECT_URI],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "client_name": "OAuth-Test",
    })
    assert response.status_code == 201
    return response.json()


def _authorize_and_login(client, client_info, password="test-secret"):
    response = client.get("/authorize", params={
        "client_id": client_info["client_id"], "redirect_uri": REDIRECT_URI,
        "response_type": "code", "code_challenge": CHALLENGE,
        "code_challenge_method": "S256", "state": "csrf-state", "resource": "http://testserver/mcp",
    }, follow_redirects=False)
    assert response.status_code == 302
    pending = parse_qs(urlparse(response.headers["location"]).query)["pending"][0]
    response = client.post("/mcp/login", data={"pending": pending, "password": password}, follow_redirects=False)
    return response


def _exchange(client, client_info, code, verifier=VERIFIER):
    return client.post("/token", data={
        "grant_type": "authorization_code", "client_id": client_info["client_id"],
        "code": code, "redirect_uri": REDIRECT_URI, "code_verifier": verifier,
        "resource": "http://testserver/mcp",
    })


def test_dcr_round_trip(client, monkeypatch):
    _enable_oauth(monkeypatch)
    registered = _register(client)
    from mcp_server.server import get_production_oauth_provider
    stored = __import__("asyncio").run(get_production_oauth_provider().get_client(registered["client_id"]))
    assert stored is not None
    assert stored.client_id == registered["client_id"]
    assert str(stored.redirect_uris[0]) == REDIRECT_URI


def test_authorization_code_pkce_flow_and_mcp_access(client, monkeypatch):
    _enable_oauth(monkeypatch)
    registered = _register(client)
    login = _authorize_and_login(client, registered)
    assert login.status_code == 302
    callback = parse_qs(urlparse(login.headers["location"]).query)
    assert callback["state"] == ["csrf-state"]
    tokens = _exchange(client, registered, callback["code"][0]).json()
    assert tokens["token_type"] == "Bearer"
    response = client.post("/mcp", headers={"Authorization": f"Bearer {tokens['access_token']}",
        "Accept": "application/json, text/event-stream"}, json={"jsonrpc":"2.0","id":1,"method":"initialize",
        "params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1"}}})
    assert response.status_code == 200


def test_expired_replayed_and_wrong_pkce_codes_are_rejected(client, monkeypatch):
    _enable_oauth(monkeypatch)
    registered = _register(client)
    login = _authorize_and_login(client, registered)
    code = parse_qs(urlparse(login.headers["location"]).query)["code"][0]
    assert _exchange(client, registered, code, "wrong" * 11).json()["error"] == "invalid_grant"
    tokens = _exchange(client, registered, code).json()
    assert "access_token" in tokens
    assert _exchange(client, registered, code).json()["error"] == "invalid_grant"

    login = _authorize_and_login(client, registered)
    expired = parse_qs(urlparse(login.headers["location"]).query)["code"][0]
    from db import get_db
    import hashlib
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE mcp_oauth_auth_codes SET expires_at=DATE_SUB(UTC_TIMESTAMP(), INTERVAL 1 SECOND) WHERE code_hash=%s", (hashlib.sha256(expired.encode()).hexdigest(),))
    assert _exchange(client, registered, expired).json()["error"] == "invalid_grant"


def test_refresh_rotation_and_revocation(client, monkeypatch):
    _enable_oauth(monkeypatch)
    registered = _register(client)
    code = parse_qs(urlparse(_authorize_and_login(client, registered).headers["location"]).query)["code"][0]
    tokens = _exchange(client, registered, code).json()
    refreshed = client.post("/token", data={"grant_type":"refresh_token", "client_id":registered["client_id"],
        "refresh_token":tokens["refresh_token"]}).json()
    assert refreshed["refresh_token"] != tokens["refresh_token"]
    assert client.post("/token", data={"grant_type":"refresh_token", "client_id":registered["client_id"],
        "refresh_token":tokens["refresh_token"]}).json()["error"] == "invalid_grant"
    # mcp 2.2.0's revocation request model requires the optional field to be
    # present even for a public (``none``) client.
    assert client.post("/revoke", data={"token": refreshed["access_token"], "client_id": registered["client_id"], "client_secret": ""}).status_code == 200
    from mcp_server.server import get_production_oauth_provider
    assert __import__("asyncio").run(get_production_oauth_provider().load_access_token(refreshed["access_token"])) is None


def test_wrong_login_does_not_leak_and_static_token_and_discovery_work(client, monkeypatch):
    _enable_oauth(monkeypatch)
    registered = _register(client)
    wrong = _authorize_and_login(client, registered, password="wrong")
    assert wrong.status_code == 200
    assert "not possible" not in wrong.text.lower()
    assert "Anmeldung nicht möglich" in wrong.text
    for path in ("/.well-known/oauth-authorization-server", "/.well-known/oauth-protected-resource/mcp"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert b"<html" not in response.content.lower()
    response = client.post("/mcp", headers={"Authorization":"Bearer test-mcp-token", "Accept":"application/json, text/event-stream"},
        json={"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1"}}})
    assert response.status_code == 200
