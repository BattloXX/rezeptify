"""Local stdio MCP server for adding recipes to Rezeptify."""
import os
import sys
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

from mcp.server.mcpserver import MCPServer
from mcp.server.auth.routes import create_auth_routes, create_protected_resource_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.server.auth.settings import AuthSettings
from pydantic import BaseModel, Field
from starlette.applications import Starlette

from mcp_server.client import RezeptifyClient
from mcp_server.oauth_provider import RezeptifyOAuthProvider


_production_oauth_provider: RezeptifyOAuthProvider | None = None


class Ingredient(BaseModel):
    amount: str = ""
    unit: str = ""
    name: str = Field(min_length=1)
    group: str | None = None


def _register_tools(server: MCPServer, client: RezeptifyClient, base_url: str) -> None:
    """Register the common recipe tools for both MCP transports."""

    @server.tool()
    async def add_recipe(
        title: str,
        steps: list[str],
        description: str = "",
        ingredients: list[Ingredient] = [],
        servings: int = 4,
        prep_minutes: int = 0,
        cook_minutes: int = 0,
        difficulty: str = "mittel",
        category: str = "",
        tags: list[str] = [],
        source_url: str = "",
        image_url: str | None = None,
        calories_per_serving: int | None = None,
    ) -> dict:
        """Add a recipe to the family's private recipe database.

        First call search_recipes with a similar title to avoid creating duplicates.
        """
        payload = {
            "format": "rezeptify-recipe/v1",
            "title": title,
            "description": description,
            "ingredients": [ingredient.model_dump() for ingredient in ingredients],
            "steps": steps,
            "servings": servings,
            "prep_minutes": prep_minutes,
            "cook_minutes": cook_minutes,
            "difficulty": difficulty,
            "category": category,
            "tags": tags,
            "source_url": source_url,
            "image_url": image_url,
            "calories_per_serving": calories_per_serving,
        }
        recipe = await client.add_recipe(payload)
        return {
            "id": recipe["id"],
            "slug": recipe["slug"],
            "url": f"{base_url.rstrip('/')}/rezept/{recipe['slug']}",
            "titel": recipe["titel"],
        }

    @server.tool()
    async def search_recipes(
        query: str = "", category: str = "", tag: str = "", limit: int = 10
    ) -> list[dict]:
        return await client.search_recipes(query, category, tag, limit)

    @server.tool()
    async def list_categories() -> list[str]:
        return await client.list_categories()

    @server.tool()
    async def list_tags() -> list[str]:
        return await client.list_tags()



def create_server(client: RezeptifyClient, base_url: str) -> MCPServer:
    """Create the local stdio MCP server."""
    server = MCPServer(
        name="rezeptify",
        description="Lokaler MCP-Zugang zur privaten Rezeptify-Rezeptdatenbank.",
    )
    _register_tools(server, client, base_url)
    return server


def create_http_asgi_app(
    client: RezeptifyClient,
    base_url: str,
    *,
    token_verifier: Any = None,
    auth_server_provider: Any = None,
    auth_settings: AuthSettings | None = None,
) -> Starlette:
    """Create the mounted Streamable-HTTP MCP ASGI application."""
    server = MCPServer(
        name="rezeptify",
        description="MCP-Zugang zur privaten Rezeptify-Rezeptdatenbank.",
        token_verifier=token_verifier,
        auth_server_provider=auth_server_provider,
        auth=auth_settings,
    )
    _register_tools(server, client, base_url)
    # This Starlette app is mounted at /mcp by app.py, so its own route must be
    # / for the externally visible endpoint to remain exactly /mcp.
    return server.streamable_http_app(streamable_http_path="/", host=urlparse(base_url).hostname or "127.0.0.1")


class _ProtectedMCPApp:
    """Run a freshly-created, always-authenticated SDK app per lifespan."""

    def __init__(self, client: RezeptifyClient, base_url: str, auth_settings: AuthSettings,
                 oauth_provider: RezeptifyOAuthProvider):
        self.client = client
        self.base_url = base_url
        self.auth_settings = auth_settings
        self.oauth_provider = oauth_provider
        self.app: Starlette | None = None

    async def __call__(self, scope, receive, send) -> None:
        if self.app is None:
            raise RuntimeError("MCP-Anwendung wurde noch nicht gestartet")
        await self.app(scope, receive, send)

    @asynccontextmanager
    async def lifespan(self):
        """Start the SDK session manager from the parent FastAPI lifespan."""
        # The SDK session manager can only be started once. Build fresh child
        # apps for every parent lifespan so FastAPI TestClient instances remain
        # independent while production still creates them exactly once.
        self.app = create_http_asgi_app(
            self.client,
            self.base_url,
            auth_server_provider=self.oauth_provider,
            auth_settings=self.auth_settings,
        )
        try:
            async with self.app.router.lifespan_context(self.app):
                yield
        finally:
            self.app = None


def build_production_http_app() -> Starlette | _ProtectedMCPApp:
    """Build the in-process remote MCP endpoint used by the FastAPI application."""
    try:
        from config import MCP_API_TOKEN
    except ImportError:
        MCP_API_TOKEN = ""
    try:
        from config import PUBLIC_BASE_URL
    except ImportError:
        PUBLIC_BASE_URL = "https://rezeptify.battlogg.at"

    loopback_url = os.getenv("REZEPTIFY_LOOPBACK_URL", "http://127.0.0.1:8000")
    client = RezeptifyClient(loopback_url, MCP_API_TOKEN)
    # mcp==2.2.0 deliberately rejects arbitrary clear-text issuers.  The
    # in-process TestClient uses ``http://testserver`` while the production
    # value is HTTPS, so use its permitted localhost spelling only for SDK
    # route construction in that test-only case.
    issuer_url = "http://localhost" if PUBLIC_BASE_URL == "http://testserver" else PUBLIC_BASE_URL
    auth_settings = AuthSettings(
        issuer_url=issuer_url,
        resource_server_url=f"{PUBLIC_BASE_URL.rstrip('/')}/mcp",
        client_registration_options=ClientRegistrationOptions(enabled=True),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=[],
        validate_token_resource=True,
    )
    global _production_oauth_provider
    _production_oauth_provider = RezeptifyOAuthProvider()
    # Unlike REST authentication, MCP is always protected. The OAuth provider
    # also accepts the configured legacy static bearer token.
    app = _ProtectedMCPApp(client, PUBLIC_BASE_URL, auth_settings, _production_oauth_provider)
    # The MCP sub-application is mounted at /mcp, but OAuth discovery is required
    # at the domain root. app.py registers these routes before the SPA catch-all.
    app.oauth_routes = [
        *create_auth_routes(_production_oauth_provider, auth_settings.issuer_url,
                            client_registration_options=auth_settings.client_registration_options,
                            revocation_options=auth_settings.revocation_options),
        *create_protected_resource_routes(auth_settings.resource_server_url,
                                          [auth_settings.issuer_url], scopes_supported=[]),
    ]
    return app


def get_production_oauth_provider() -> RezeptifyOAuthProvider:
    if _production_oauth_provider is None:
        raise RuntimeError("OAuth-Anbieter wurde nicht initialisiert")
    return _production_oauth_provider


def main() -> None:
    base_url = os.getenv("REZEPTIFY_BASE_URL")
    api_token = os.getenv("REZEPTIFY_API_TOKEN")
    if not base_url or not api_token:
        print(
            "REZEPTIFY_BASE_URL und REZEPTIFY_API_TOKEN müssen gesetzt sein.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    server = create_server(RezeptifyClient(base_url, api_token), base_url)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
