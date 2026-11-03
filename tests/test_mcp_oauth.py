"""MariaDB-backed OAuth 2.1 integration tests for the remote MCP endpoint."""
import asyncio
import hashlib
from collections import defaultdict, deque

from urllib.parse import parse_qs, urlparse


REDIRECT_URI = "http://connector.test/callback"
VERIFIER = "a" * 43
CHALLENGE = "ZtNPunH49FD35FWYhT5Tv8I7vRKQJ8uxMaL0_9eHjNA"


def _enable_oauth(monkeypatch):
    import mcp_server.auth as mcp_auth
    import routes.mcp_auth as login
    monkeypatch.setattr(login, "_attempts", defaultdict(deque))
    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")
    monkeypatch.setattr(login, "AUTH_PASSWORD", "test-secret")
    monkeypatch.setattr(login, "MCP_LOGIN_PASSWORD", "test-mcp-login")


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


def _authorize_and_login(client, client_info, password="test-mcp-login", resource="http://testserver/mcp"):
    params = {
        "client_id": client_info["client_id"], "redirect_uri": REDIRECT_URI,
        "response_type": "code", "code_challenge": CHALLENGE,
        "code_challenge_method": "S256", "state": "csrf-state",
    }
    if resource is not None:
        params["resource"] = resource
    response = client.get("/authorize", params=params, follow_redirects=False)
    assert response.status_code == 302
    pending = parse_qs(urlparse(response.headers["location"]).query)["pending"][0]
    response = client.post("/mcp/login", data={"pending": pending, "password": password}, follow_redirects=False)
    return response


def _exchange(client, client_info, code, verifier=VERIFIER, resource="http://testserver/mcp"):
    data = {
        "grant_type": "authorization_code", "client_id": client_info["client_id"],
        "code": code, "redirect_uri": REDIRECT_URI, "code_verifier": verifier,
    }
    if resource is not None:
        data["resource"] = resource
    return client.post("/token", data=data)


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


def test_mcp_login_falls_back_to_auth_password(client, monkeypatch):
    _enable_oauth(monkeypatch)
    import routes.mcp_auth as login
    monkeypatch.setattr(login, "MCP_LOGIN_PASSWORD", "")
    registered = _register(client)

    assert _authorize_and_login(client, registered, password="test-secret").status_code == 302


def test_empty_effective_mcp_password_rejects_login(client, monkeypatch):
    _enable_oauth(monkeypatch)
    import routes.mcp_auth as login
    monkeypatch.setattr(login, "MCP_LOGIN_PASSWORD", "")
    monkeypatch.setattr(login, "AUTH_PASSWORD", "")
    registered = _register(client)

    response = _authorize_and_login(client, registered, password="")
    assert response.status_code == 200
    assert "Anmeldung nicht möglich" in response.text


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
    from db import get_db
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE mcp_oauth_tokens SET rotated_at=UTC_TIMESTAMP() - INTERVAL 10 MINUTE WHERE token_hash=%s",
                        (hashlib.sha256(tokens["refresh_token"].encode()).hexdigest(),))
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


def _tokens(client, registered, resource="http://testserver/mcp"):
    login = _authorize_and_login(client, registered, resource=resource)
    assert login.status_code == 302
    code = parse_qs(urlparse(login.headers["location"]).query)["code"][0]
    response = _exchange(client, registered, code, resource=resource)
    assert response.status_code == 200
    return response.json()


def _refresh(client, registered, token):
    return client.post("/token", data={"grant_type": "refresh_token",
        "client_id": registered["client_id"], "refresh_token": token})


def _assert_mcp_access(client, token):
    response = client.post("/mcp", headers={"Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream"}, json={"jsonrpc": "2.0", "id": 1,
        "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"}}})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "result" in response.json()


def test_access_token_lifetime_is_24h(client, monkeypatch):
    _enable_oauth(monkeypatch)
    assert _tokens(client, _register(client))["expires_in"] == 86400


def test_refresh_reuse_within_grace_period_succeeds(client, monkeypatch):
    from db import get_db
    _enable_oauth(monkeypatch)
    registered = _register(client)
    tokens = _tokens(client, registered)
    first = _refresh(client, registered, tokens["refresh_token"])
    assert first.status_code == 200
    token_hash = hashlib.sha256(tokens["refresh_token"].encode()).hexdigest()
    with get_db() as conn:
        with conn.cursor() as cur:
            # A retry must preserve the original grace deadline.
            cur.execute("UPDATE mcp_oauth_tokens SET rotated_at=UTC_TIMESTAMP() - INTERVAL 60 SECOND WHERE token_hash=%s", (token_hash,))
            cur.execute("SELECT rotated_at FROM mcp_oauth_tokens WHERE token_hash=%s", (token_hash,))
            rotated_at = cur.fetchone()["rotated_at"]
    second = _refresh(client, registered, tokens["refresh_token"])
    assert second.status_code == 200
    assert first.json()["access_token"] != second.json()["access_token"]
    assert first.json()["refresh_token"] != second.json()["refresh_token"]
    for pair in (tokens, first.json(), second.json()):
        _assert_mcp_access(client, pair["access_token"])
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT rotated_at FROM mcp_oauth_tokens WHERE token_hash=%s", (token_hash,))
            assert cur.fetchone()["rotated_at"] == rotated_at
            cur.execute("SELECT TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), expires_at) AS remaining FROM mcp_oauth_tokens WHERE token_hash=%s",
                        (hashlib.sha256(second.json()["refresh_token"].encode()).hexdigest(),))
            assert 90 * 86400 - 30 <= cur.fetchone()["remaining"] <= 90 * 86400


def test_refresh_reuse_after_grace_period_fails(client, monkeypatch):
    from db import get_db
    _enable_oauth(monkeypatch)
    registered = _register(client)
    tokens = _tokens(client, registered)
    assert _refresh(client, registered, tokens["refresh_token"]).status_code == 200
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE mcp_oauth_tokens SET rotated_at=UTC_TIMESTAMP() - INTERVAL 10 MINUTE WHERE token_hash=%s",
                        (hashlib.sha256(tokens["refresh_token"].encode()).hexdigest(),))
    response = _refresh(client, registered, tokens["refresh_token"])
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_revoked_refresh_token_has_no_grace(client, monkeypatch):
    from db import get_db
    _enable_oauth(monkeypatch)
    registered = _register(client)
    tokens = _tokens(client, registered)
    # Explicit revocation also cancels an already running grace period.
    assert _refresh(client, registered, tokens["refresh_token"]).status_code == 200
    assert client.post("/revoke", data={"token": tokens["refresh_token"],
        "client_id": registered["client_id"], "client_secret": ""}).status_code == 200
    response = _refresh(client, registered, tokens["refresh_token"])
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT revoked, rotated_at FROM mcp_oauth_tokens WHERE token_hash=%s",
                        (hashlib.sha256(tokens["refresh_token"].encode()).hexdigest(),))
            assert cur.fetchone() == {"revoked": 1, "rotated_at": None}


def test_authorization_without_resource_parameter_works(client, monkeypatch):
    _enable_oauth(monkeypatch)
    tokens = _tokens(client, _register(client), resource=None)
    _assert_mcp_access(client, tokens["access_token"])


def test_legacy_token_with_null_resource_is_accepted(client, monkeypatch):
    from db import get_db
    _enable_oauth(monkeypatch)
    registered = _register(client)
    login = _authorize_and_login(client, registered)
    code = parse_qs(urlparse(login.headers["location"]).query)["code"][0]
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE mcp_oauth_auth_codes SET resource=NULL")
    response = _exchange(client, registered, code, resource=None)
    assert response.status_code == 200
    tokens = response.json()
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE mcp_oauth_tokens SET resource=NULL")
    _assert_mcp_access(client, tokens["access_token"])
    refreshed = _refresh(client, registered, tokens["refresh_token"])
    assert refreshed.status_code == 200
    _assert_mcp_access(client, refreshed.json()["access_token"])


def test_cleanup_removes_expired_rows(client, monkeypatch):
    from db import get_db
    from mcp_server.server import get_production_oauth_provider
    _enable_oauth(monkeypatch)
    registered = _register(client)
    tokens = _tokens(client, registered)
    assert _refresh(client, registered, tokens["refresh_token"]).status_code == 200
    login = _authorize_and_login(client, registered)
    assert login.status_code == 302
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO mcp_oauth_pending
                (pending_id,client_id,redirect_uri,code_challenge,expires_at)
                VALUES ('expired',%s,%s,%s,UTC_TIMESTAMP() - INTERVAL 1 SECOND),
                       ('valid',%s,%s,%s,UTC_TIMESTAMP() + INTERVAL 1 DAY)""",
                (registered["client_id"], REDIRECT_URI, CHALLENGE) * 2)
            cur.execute("""INSERT INTO mcp_oauth_auth_codes
                (code_hash,client_id,redirect_uri,code_challenge,expires_at)
                VALUES ('expired',%s,%s,%s,UTC_TIMESTAMP() - INTERVAL 1 SECOND)""",
                (registered["client_id"], REDIRECT_URI, CHALLENGE))
            for name, expires, revoked, rotated, created in (
                ("expired", -2, 0, None, 0),
                ("recently_expired", 0, 0, None, 0),
                ("old_revoked", 1, 1, None, -2),
                ("old_rotated", 1, 1, -2, -2),
                ("recently_rotated", 1, 1, 0, -2),
                ("recently_revoked", 1, 1, None, 0),
            ):
                cur.execute("""INSERT INTO mcp_oauth_tokens
                    (token_hash,token_type,client_id,expires_at,revoked,rotated_at,erstellt_am)
                    VALUES (%s,'refresh',%s,UTC_TIMESTAMP() + INTERVAL %s DAY,%s,
                        IF(%s IS NULL,NULL,UTC_TIMESTAMP() + INTERVAL %s DAY),UTC_TIMESTAMP() + INTERVAL %s DAY)""",
                    (name, registered["client_id"], expires, revoked, rotated, rotated, created))
            cur.execute("UPDATE mcp_oauth_tokens SET expires_at=UTC_TIMESTAMP() - INTERVAL 1 HOUR WHERE token_hash='recently_expired'")
            # An old access token linked to a rotated refresh remains usable.
            cur.execute("UPDATE mcp_oauth_tokens SET erstellt_am=UTC_TIMESTAMP() - INTERVAL 2 DAY WHERE token_hash=%s",
                        (hashlib.sha256(tokens["access_token"].encode()).hexdigest(),))
    provider = get_production_oauth_provider()
    asyncio.run(provider._run(provider.cleanup_expired))
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pending_id FROM mcp_oauth_pending")
            assert [row["pending_id"] for row in cur.fetchall()] == ["valid"]
            cur.execute("SELECT code_hash FROM mcp_oauth_auth_codes")
            codes = cur.fetchall()
            assert len(codes) == 1 and codes[0]["code_hash"] != "expired"
            cur.execute("SELECT token_hash FROM mcp_oauth_tokens")
            remaining = {row["token_hash"] for row in cur.fetchall()}
            assert not remaining.intersection({"expired", "old_revoked", "old_rotated"})
            assert {"recently_expired", "recently_rotated", "recently_revoked"} <= remaining
            assert len(remaining) == 7
    _assert_mcp_access(client, tokens["access_token"])


def test_login_rate_limit_uses_forwarded_ip(client, monkeypatch):
    import routes.mcp_auth as login
    from starlette.requests import Request
    _enable_oauth(monkeypatch)
    request = Request({"type": "http", "client": ("testclient", 123),
        "headers": [(b"x-real-ip", b"10.0.0.1")]})
    assert login._client_ip(request) == "testclient"
    monkeypatch.setattr(login, "TRUSTED_PROXIES", login.TRUSTED_PROXIES | {"testclient"})
    registered = _register(client)
    response = client.get("/authorize", params={"client_id": registered["client_id"],
        "redirect_uri": REDIRECT_URI, "response_type": "code", "code_challenge": CHALLENGE,
        "code_challenge_method": "S256"}, follow_redirects=False)
    pending = parse_qs(urlparse(response.headers["location"]).query)["pending"][0]
    for _ in range(5):
        response = client.post("/mcp/login", headers={"X-Real-IP": "10.0.0.1"},
            data={"pending": pending, "password": "wrong"}, follow_redirects=False)
        assert "Anmeldung nicht möglich" in response.text
    response = client.post("/mcp/login", headers={"X-Real-IP": "10.0.0.1"},
        data={"pending": pending, "password": "test-mcp-login"}, follow_redirects=False)
    assert response.status_code == 200
    assert "Anmeldung nicht möglich" in response.text
    response = client.post("/mcp/login", headers={"X-Real-IP": "10.0.0.2"},
        data={"pending": pending, "password": "test-mcp-login"}, follow_redirects=False)
    assert response.status_code == 302
    assert len(login._attempts["__global__"]) == 5
    assert "10.0.0.2" not in login._attempts
