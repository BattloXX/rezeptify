import json

import httpx
import pytest

from mcp_server.client import RezeptifyClient


def _payload() -> dict:
    return {
        "format": "rezeptify-recipe/v1",
        "title": "Tomatensuppe",
        "description": "Einfach und gut.",
        "ingredients": [{"amount": "800", "unit": "g", "name": "Tomaten", "group": None}],
        "steps": ["Kochen.", "Pürieren."],
        "servings": 4,
        "prep_minutes": 5,
        "cook_minutes": 20,
        "difficulty": "leicht",
        "category": "Suppen",
        "tags": ["vegetarisch"],
        "source_url": "",
        "image_url": None,
        "calories_per_serving": None,
    }


@pytest.mark.asyncio
async def test_add_recipe_validates_creates_and_attaches_image():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/analysiere-bild":
            assert request.method == "POST"
            assert request.headers["content-type"].startswith("multipart/form-data")
            assert 'name="file"' in request.content.decode()
            assert 'filename="recipe.json"' in request.content.decode()
            assert json.dumps(_payload()).encode() in request.content
            return httpx.Response(200, json={**_payload(), "downloaded_image": "tomate.jpg"})
        if request.url.path == "/api/rezepte":
            assert request.method == "POST"
            assert json.loads(request.content) == {**_payload(), "downloaded_image": "tomate.jpg"}
            return httpx.Response(201, json={"id": 42, "slug": "tomatensuppe-42", "titel": "Tomatensuppe"})
        assert request.method == "POST"
        assert request.url.path == "/api/rezepte/42/bilder/attach"
        assert json.loads(request.content) == {"dateiname": "tomate.jpg", "ist_haupt": True}
        return httpx.Response(200, json={"ok": True})

    client = RezeptifyClient("https://rezeptify.example", "secret", transport=httpx.MockTransport(handler))
    try:
        assert await client.add_recipe(_payload()) == {
            "id": 42, "slug": "tomatensuppe-42", "titel": "Tomatensuppe"
        }
    finally:
        await client.aclose()

    assert [request.url.path for request in requests] == [
        "/api/analysiere-bild", "/api/rezepte", "/api/rezepte/42/bilder/attach"
    ]
    assert all(request.headers["authorization"] == "Bearer secret" for request in requests)


@pytest.mark.asyncio
async def test_add_recipe_skips_attachment_without_downloaded_image():
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/analysiere-bild":
            return httpx.Response(200, json=_payload())
        return httpx.Response(201, json={"id": 3, "slug": "tomatensuppe-3", "titel": "Tomatensuppe"})

    client = RezeptifyClient("https://rezeptify.example", "secret", transport=httpx.MockTransport(handler))
    try:
        await client.add_recipe(_payload())
    finally:
        await client.aclose()
    assert paths == ["/api/analysiere-bild", "/api/rezepte"]


@pytest.mark.asyncio
async def test_add_recipe_surfaces_structured_validation_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "Ungültige Rezeptdatei: title fehlt"})

    client = RezeptifyClient("https://rezeptify.example", "secret", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(RuntimeError, match="Ungültige Rezeptdatei: title fehlt"):
            await client.add_recipe(_payload())
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_search_categories_and_tags_use_expected_endpoints_and_shapes():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/rezepte":
            return httpx.Response(200, json={"items": [{
                "id": 1, "titel": "Suppe", "slug": "suppe-1", "kategorie": "Suppen",
                "tags": ["warm"], "beschreibung": "nicht weitergeben",
            }]})
        if request.url.path == "/api/kategorien":
            return httpx.Response(200, json=["Suppen", "Desserts"])
        return httpx.Response(200, json=["warm", "schnell"])

    client = RezeptifyClient("https://rezeptify.example", "secret", transport=httpx.MockTransport(handler))
    try:
        assert await client.search_recipes("suppe", "Suppen", "warm", 5) == [{
            "id": 1, "titel": "Suppe", "slug": "suppe-1", "kategorie": "Suppen", "tags": ["warm"]
        }]
        assert await client.list_categories() == ["Suppen", "Desserts"]
        assert await client.list_tags() == ["warm", "schnell"]
    finally:
        await client.aclose()

    assert [(r.method, r.url.path) for r in requests] == [
        ("GET", "/api/rezepte"), ("GET", "/api/kategorien"), ("GET", "/api/tags")
    ]
    assert dict(requests[0].url.params) == {
        "suche": "suppe", "kategorie": "Suppen", "tag": "warm", "limit": "5"
    }
