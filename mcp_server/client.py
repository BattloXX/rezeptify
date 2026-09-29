"""HTTP client for a running Rezeptify instance."""
import json
import re
from typing import Any

import httpx


class RezeptifyClient:
    """Small authenticated wrapper around the Rezeptify REST API."""

    def __init__(
        self,
        base_url: str,
        api_token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=20.0,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return json.dumps(detail, ensure_ascii=False)
        return response.text or f"HTTP {response.status_code}"

    @classmethod
    def _raise_for_status(cls, response: httpx.Response) -> None:
        if response.is_error:
            raise RuntimeError(
                f"Rezeptify API antwortete mit {response.status_code}: {cls._error_detail(response)}"
            )

    async def add_recipe(self, payload: dict) -> dict:
        """Validate structured JSON, create it, and attach a downloaded image."""
        analysis = await self._client.post(
            "/api/analysiere-bild",
            files={"file": ("recipe.json", json.dumps(payload).encode("utf-8"), "application/json")},
        )
        self._raise_for_status(analysis)
        imported = analysis.json()

        created_response = await self._client.post("/api/rezepte", json=imported)
        self._raise_for_status(created_response)
        created = created_response.json()

        if imported.get("downloaded_image"):
            attached = await self._client.post(
                f"/api/rezepte/{created['id']}/bilder/attach",
                json={"dateiname": imported["downloaded_image"], "ist_haupt": True},
            )
            self._raise_for_status(attached)
        return created

    async def search_recipes(
        self, query: str = "", category: str = "", tag: str = "", limit: int = 10
    ) -> list[dict]:
        params: dict[str, Any] = {}
        if query:
            params["suche"] = query
        if category:
            params["kategorie"] = category
        if tag:
            params["tag"] = tag
        if limit != 10:
            params["limit"] = limit
        response = await self._client.get("/api/rezepte", params=params)
        self._raise_for_status(response)
        return [
            {key: item.get(key) for key in ("id", "titel", "slug", "kategorie", "tags")}
            for item in response.json()["items"]
        ]

    @staticmethod
    def _steps_from_instructions(instructions: str | None) -> list[str]:
        """Convert Rezeptify's paragraph-separated instructions back to steps."""
        cleaned = (instructions or "").strip()
        if not cleaned:
            return []
        blocks = [block.strip() for block in re.split(r"\n\s*\n+", cleaned) if block.strip()]
        return blocks if len(blocks) > 1 else [cleaned]

    def _recipe_shape(self, recipe: dict) -> dict:
        """Map the REST representation to the English MCP recipe shape."""
        return {
            "id": recipe["id"],
            "slug": recipe["slug"],
            "url": f"{self.base_url}/rezept/{recipe['slug']}",
            "title": recipe.get("titel") or "",
            "description": recipe.get("beschreibung") or "",
            "ingredients": [
                {
                    "amount": ingredient.get("menge") or "",
                    "unit": ingredient.get("einheit") or "",
                    "name": ingredient.get("name") or "",
                    "group": ingredient.get("gruppe"),
                }
                for ingredient in (recipe.get("zutaten") or [])
            ],
            "steps": self._steps_from_instructions(recipe.get("zubereitung")),
            "servings": recipe.get("portionen"),
            "prep_minutes": recipe.get("zeit_vorb"),
            "cook_minutes": recipe.get("zeit_koch"),
            "difficulty": recipe.get("schwierigkeit"),
            "category": recipe.get("kategorie") or "",
            "tags": recipe.get("tags") or [],
            "source_url": recipe.get("quelle_url") or "",
            "calories_per_serving": recipe.get("kalorien_pro_portion"),
        }

    async def _get_recipe_raw(self, recipe_id: int) -> dict:
        response = await self._client.get(f"/api/rezepte/{recipe_id}")
        self._raise_for_status(response)
        return response.json()

    async def get_recipe(self, recipe_id: int) -> dict:
        """Return an MCP-shaped full recipe record."""
        return self._recipe_shape(await self._get_recipe_raw(recipe_id))

    async def update_recipe(
        self,
        recipe_id: int,
        *,
        title: str | None = None,
        steps: list[str] | None = None,
        description: str | None = None,
        ingredients: list[dict] | None = None,
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
        """Merge partial MCP fields into Rezeptify's full replacement PUT model."""
        existing = await self._get_recipe_raw(recipe_id)
        payload = {
            "titel": existing.get("titel") or "",
            "beschreibung": existing.get("beschreibung") or "",
            "zutaten": existing.get("zutaten") or [],
            "zubereitung": existing.get("zubereitung") or "",
            "portionen": existing.get("portionen"),
            "zeit_vorb": existing.get("zeit_vorb"),
            "zeit_koch": existing.get("zeit_koch"),
            "schwierigkeit": existing.get("schwierigkeit"),
            "kategorie": existing.get("kategorie") or "",
            "tags": existing.get("tags") or [],
            "quelle_url": existing.get("quelle_url") or "",
            # PUT replaces all columns: preserve fields that MCP intentionally
            # does not expose instead of silently changing recipe provenance.
            "quelle_typ": existing.get("quelle_typ") or "manuell",
            "quelldatei": existing.get("quelldatei"),
            "kalorien_pro_portion": existing.get("kalorien_pro_portion"),
        }
        if title is not None:
            payload["titel"] = title
        if steps is not None:
            payload["zubereitung"] = "\n\n".join(steps)
        if description is not None:
            payload["beschreibung"] = description
        if ingredients is not None:
            payload["zutaten"] = [
                {
                    "menge": ingredient.get("amount") or "",
                    "einheit": ingredient.get("unit") or "",
                    "name": ingredient.get("name") or "",
                    "gruppe": ingredient.get("group"),
                }
                for ingredient in ingredients
            ]
        for value, key in (
            (servings, "portionen"), (prep_minutes, "zeit_vorb"),
            (cook_minutes, "zeit_koch"), (difficulty, "schwierigkeit"),
            (category, "kategorie"), (tags, "tags"),
            (source_url, "quelle_url"), (calories_per_serving, "kalorien_pro_portion"),
        ):
            if value is not None:
                payload[key] = value

        response = await self._client.put(f"/api/rezepte/{recipe_id}", json=payload)
        self._raise_for_status(response)
        updated = response.json()

        # An automatic Kochmodus mirror would otherwise retain stale paragraphs.
        # Never overwrite a family member's manually edited cooking steps.
        if steps is not None and existing.get("schritte_quelle") == "auto":
            auto_steps = await self._client.post(f"/api/rezepte/{recipe_id}/schritte/auto")
            self._raise_for_status(auto_steps)

        if image_url is not None:
            downloaded = await self._client.post("/api/bilder/from-url", json={"url": image_url})
            self._raise_for_status(downloaded)
            attached = await self._client.post(
                f"/api/rezepte/{recipe_id}/bilder/attach",
                json={"dateiname": downloaded.json()["dateiname"], "ist_haupt": True},
            )
            self._raise_for_status(attached)
        return self._recipe_shape(updated)

    async def list_categories(self) -> list[str]:
        response = await self._client.get("/api/kategorien")
        self._raise_for_status(response)
        return response.json()

    async def list_tags(self) -> list[str]:
        response = await self._client.get("/api/tags")
        self._raise_for_status(response)
        return response.json()
