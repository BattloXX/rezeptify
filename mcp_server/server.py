"""Local stdio MCP server for adding recipes to Rezeptify."""
import functools
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.auth.routes import create_auth_routes, create_protected_resource_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.server.auth.settings import AuthSettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_server.client import DuplicateRecipeError, RezeptifyClient
from mcp_server.oauth_provider import RezeptifyOAuthProvider


_production_oauth_provider: RezeptifyOAuthProvider | None = None

logger = logging.getLogger(__name__)


def _logged(fn):
    """Log tool duration on success and failures with a readable message."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        started = time.monotonic()
        try:
            result = await fn(*args, **kwargs)
            logger.info("MCP-Tool %s ok in %.0f ms", fn.__name__,
                        (time.monotonic() - started) * 1000)
            return result
        except DuplicateRecipeError as exc:
            logger.info("MCP-Tool %s: ähnliches Rezept vorhanden", fn.__name__)
            raise ToolError(str(exc)) from exc
        except Exception as exc:
            logger.exception("MCP-Tool %s fehlgeschlagen", fn.__name__)
            raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc
    return wrapper


class Ingredient(BaseModel):
    amount: str = ""
    unit: str = ""
    name: str = Field(min_length=1)
    group: str | None = None


def _register_tools(server: MCPServer, client: RezeptifyClient, base_url: str) -> None:
    """Register the common recipe tools for both MCP transports."""

    @server.tool(annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
    @_logged
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
        allow_duplicate: bool = False,
    ) -> dict:
        """Add a recipe to the family's private recipe database.

        Similar titles are rejected with existing recipe IDs and URLs. Use
        update_recipe to change one, or allow_duplicate=true to create it anyway.
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
        recipe = await client.add_recipe(payload, allow_duplicate=allow_duplicate)
        return {
            "id": recipe["id"],
            "slug": recipe["slug"],
            "url": f"{base_url.rstrip('/')}/rezept/{recipe['slug']}",
            "titel": recipe["titel"],
        }

    @server.tool(annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    @_logged
    async def search_recipes(
        query: str = "", category: str = "", tag: str = "", limit: int = 10
    ) -> list[dict]:
        """Search titles, descriptions, categories, tags and ingredients.

        All search words must occur (AND). Optional category and tag filters apply.
        Return id, titel, slug, kategorie, tags, beschreibung (160 characters,
        then … if truncated), favorit, bewertung and zeit_gesamt in minutes.
        The limit is clamped to 1..200.
        """
        limit = max(1, min(limit, 200))
        return await client.search_recipes(query, category, tag, limit)

    @server.tool(annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    @_logged
    async def find_duplicate_recipes() -> list[dict]:
        """List title-based duplicate candidates; nothing is deleted or merged.

        Return pairs a and b (id, titel) with their aehnlichkeit score.
        """
        return await client.find_duplicate_recipes()

    @server.tool(annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    @_logged
    async def get_recipe(recipe_id: int) -> dict:
        """Read a complete recipe before changing it.

        First call search_recipes to find the recipe ID, then call this tool
        before update_recipe so existing content is preserved intentionally.
        """
        recipe = await client.get_recipe(recipe_id)
        recipe["url"] = f"{base_url.rstrip('/')}/rezept/{recipe['slug']}"
        return recipe

    @server.tool(annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    @_logged
    async def update_recipe(
        recipe_id: int,
        title: str | None = None,
        steps: list[str] | None = None,
        description: str | None = None,
        ingredients: list[Ingredient] | None = None,
        servings: int | None = None,
        prep_minutes: int | None = None,
        cook_minutes: int | None = None,
        difficulty: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        source_url: str | None = None,
        calories_per_serving: int | None = None,
        image_url: str | None = None,
    ) -> dict:
        """Partially update one family recipe without deleting it.

        First use search_recipes to find recipe_id and get_recipe to inspect it.
        Pass only fields that should change; None keeps a field unchanged, while
        empty ingredients or tags lists deliberately clear those fields. This
        tool cannot delete recipes or change rating, favorite, or existing images;
        image_url can only add a new main image.
        """
        recipe = await client.update_recipe(
            recipe_id,
            title=title,
            steps=steps,
            description=description,
            ingredients=[ingredient.model_dump() for ingredient in ingredients]
            if ingredients is not None else None,
            servings=servings,
            prep_minutes=prep_minutes,
            cook_minutes=cook_minutes,
            difficulty=difficulty,
            category=category,
            tags=tags,
            source_url=source_url,
            calories_per_serving=calories_per_serving,
            image_url=image_url,
        )
        recipe["url"] = f"{base_url.rstrip('/')}/rezept/{recipe['slug']}"
        return recipe

    @server.tool(annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    @_logged
    async def list_categories() -> list[str]:
        """List available recipe categories for searching and organizing recipes."""
        return await client.list_categories()

    @server.tool(annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    @_logged
    async def list_tags() -> list[str]:
        """List available recipe tags for searching and labeling recipes."""
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
    # Stateless requests work across multiple workers and restarts without
    # depending on in-memory sessions or their idle timeout.
    return server.streamable_http_app(streamable_http_path="/", host=urlparse(base_url).hostname or "127.0.0.1", stateless_http=True, json_response=True)


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
        if scope["type"] != "http":
            if self.app is None:
                raise RuntimeError("MCP-Anwendung wurde noch nicht gestartet")
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        auth_kind = "bearer" if request.headers.get("authorization", "").lower().startswith("bearer ") else "none"
        has_session_id = "mcp-session-id" in request.headers
        user_agent = request.headers.get("user-agent", "")

        async def logged_send(message):
            if message["type"] == "http.response.start":
                status = message["status"]
                log = logger.warning if status >= 400 else logger.debug
                log("MCP %s %s -> %s (auth=%s, session=%s, ua=%s)",
                    request.method, request.url.path, status, auth_kind,
                    has_session_id, user_agent[:80])
            await send(message)

        if self.app is None:
            await JSONResponse({"error": "mcp_unavailable"}, status_code=503)(scope, receive, logged_send)
            return
        await self.app(scope, receive, logged_send)

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


async def _call_rest_app(scope, receive, send) -> None:
    from app import app as rest_app  # resolved lazily: app.py imports this module
    scope = {**scope, "rezeptify_internal": True}
    await rest_app(scope, receive, send)


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

    loopback_url = os.getenv("REZEPTIFY_LOOPBACK_URL")
    if loopback_url:
        client = RezeptifyClient(loopback_url, MCP_API_TOKEN, public_base_url=PUBLIC_BASE_URL)
    else:
        # Call the REST API inside this process: no dependency on the port the
        # process manager (CloudPanel/systemd) happens to bind.
        client = RezeptifyClient("http://rezeptify.internal", MCP_API_TOKEN,
                                 transport=httpx.ASGITransport(app=_call_rest_app),
                                 public_base_url=PUBLIC_BASE_URL)
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
