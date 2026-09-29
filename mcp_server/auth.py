"""Bearer-token verification for the remote MCP transport."""
import secrets

from mcp.server.auth.provider import AccessToken, TokenVerifier

try:
    from config import MCP_API_TOKEN, AUTH_ENABLED
except ImportError:
    MCP_API_TOKEN = ""
    AUTH_ENABLED = False


class StaticBearerTokenVerifier(TokenVerifier):
    """Verify Rezeptify's existing static MCP token at request time."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if not AUTH_ENABLED or not MCP_API_TOKEN:
            return None
        if not secrets.compare_digest(token.encode(), MCP_API_TOKEN.encode()):
            return None
        return AccessToken(token=token, client_id="rezeptify-mcp-static", scopes=[])
