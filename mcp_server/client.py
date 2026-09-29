"""HTTP client for a running Rezeptify instance."""
import json
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

    async def list_categories(self) -> list[str]:
        response = await self._client.get("/api/kategorien")
        self._raise_for_status(response)
        return response.json()

    async def list_tags(self) -> list[str]:
        response = await self._client.get("/api/tags")
        self._raise_for_status(response)
        return response.json()
