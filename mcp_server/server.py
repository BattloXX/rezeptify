"""Local stdio MCP server for adding recipes to Rezeptify."""
import os
import sys

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from mcp_server.client import RezeptifyClient


class Ingredient(BaseModel):
    amount: str = ""
    unit: str = ""
    name: str = Field(min_length=1)
    group: str | None = None


def create_server(client: RezeptifyClient, base_url: str) -> MCPServer:
    server = MCPServer(
        name="rezeptify",
        description="Lokaler MCP-Zugang zur privaten Rezeptify-Rezeptdatenbank.",
    )

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

    return server


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
