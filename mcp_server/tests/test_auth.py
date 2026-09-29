import pytest

import mcp_server.auth as auth
from mcp_server.auth import StaticBearerTokenVerifier
from mcp.server.auth.provider import AccessToken


@pytest.mark.asyncio
async def test_correct_token_returns_access_token(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "MCP_API_TOKEN", "test-mcp-token")

    token = await StaticBearerTokenVerifier().verify_token("test-mcp-token")

    assert isinstance(token, AccessToken)
    assert token.token == "test-mcp-token"
    assert token.client_id == "rezeptify-mcp-static"
    assert token.scopes == []


@pytest.mark.asyncio
async def test_wrong_token_is_rejected(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "MCP_API_TOKEN", "test-mcp-token")

    assert await StaticBearerTokenVerifier().verify_token("wrong-token") is None


@pytest.mark.asyncio
async def test_auth_disabled_rejects_even_the_correct_token(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    monkeypatch.setattr(auth, "MCP_API_TOKEN", "test-mcp-token")

    assert await StaticBearerTokenVerifier().verify_token("test-mcp-token") is None


@pytest.mark.asyncio
async def test_empty_token_never_authorizes(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "MCP_API_TOKEN", "")

    assert await StaticBearerTokenVerifier().verify_token("anything") is None
