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


def _rest_recipe() -> dict:
    return {
        "id": 7,
        "slug": "alte-suppe-7",
        "titel": "Alte Suppe",
        "beschreibung": "Bewährtes Rezept.",
        "zutaten": [{"gruppe": "Gemüse"}, {"menge": "2", "einheit": "Stk", "name": "Karotten", "gruppe": None}],
        "zubereitung": "Schneiden.\n\nKochen.",
        "portionen": 4,
        "zeit_vorb": 10,
        "zeit_koch": 20,
        "schwierigkeit": "leicht",
        "kategorie": "Suppen",
        "tags": ["warm"],
        "quelle_url": "https://example.test/quelle",
        "quelle_typ": "import",
        "quelldatei": "original.pdf",
        "kalorien_pro_portion": 180,
        "schritte_quelle": "auto",
        "bewertung": 5,
        "favorit": True,
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


@pytest.mark.asyncio
async def test_get_recipe_maps_full_rest_recipe_to_mcp_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/rezepte/7"
        return httpx.Response(200, json=_rest_recipe())

    client = RezeptifyClient("https://rezeptify.example", "secret", transport=httpx.MockTransport(handler))
    try:
        recipe = await client.get_recipe(7)
    finally:
        await client.aclose()

    assert recipe == {
        "id": 7, "slug": "alte-suppe-7", "url": "https://rezeptify.example/rezept/alte-suppe-7",
        "title": "Alte Suppe", "description": "Bewährtes Rezept.",
        "ingredients": [{"amount": "2", "unit": "Stk", "name": "Karotten", "group": "Gemüse"}],
        "steps": ["Schneiden.", "Kochen."], "servings": 4, "prep_minutes": 10,
        "cook_minutes": 20, "difficulty": "leicht", "category": "Suppen", "tags": ["warm"],
        "source_url": "https://example.test/quelle", "calories_per_serving": 180,
    }


@pytest.mark.asyncio
async def test_update_recipe_merges_full_put_preserves_provenance_and_refreshes_auto_steps():
    requests = []
    updated = {**_rest_recipe(), "titel": "Neue Suppe", "slug": "neue-suppe-7", "tags": []}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=_rest_recipe())
        if request.method == "PUT":
            assert request.url.path == "/api/rezepte/7"
            assert json.loads(request.content) == {
                "titel": "Neue Suppe", "beschreibung": "Bewährtes Rezept.",
                "zutaten": [{"gruppe": "Gemüse"}, {"menge": "2", "einheit": "Stk", "name": "Karotten", "gruppe": None}],
                "zubereitung": "Neu kochen.", "portionen": 4, "zeit_vorb": 10, "zeit_koch": 20,
                "schwierigkeit": "leicht", "kategorie": "Suppen", "tags": [],
                "quelle_url": "https://example.test/quelle", "quelle_typ": "import",
                "quelldatei": "original.pdf", "kalorien_pro_portion": 180,
            }
            return httpx.Response(200, json={**updated, "zubereitung": "Neu kochen."})
        assert request.method == "POST"
        assert request.url.path == "/api/rezepte/7/schritte/auto"
        return httpx.Response(200, json={"ok": True})

    client = RezeptifyClient("https://rezeptify.example", "secret", transport=httpx.MockTransport(handler))
    try:
        result = await client.update_recipe(7, title="Neue Suppe", steps=["Neu kochen."], tags=[])
    finally:
        await client.aclose()

    assert result["slug"] == "neue-suppe-7"
    assert result["url"] == "https://rezeptify.example/rezept/neue-suppe-7"
    assert result["tags"] == []
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/api/rezepte/7"), ("PUT", "/api/rezepte/7"),
        ("POST", "/api/rezepte/7/schritte/auto"),
    ]


@pytest.mark.asyncio
async def test_update_recipe_can_clear_ingredients_and_add_a_main_image():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=_rest_recipe())
        if request.method == "PUT":
            assert json.loads(request.content)["zutaten"] == []
            return httpx.Response(200, json={**_rest_recipe(), "zutaten": []})
        if request.url.path == "/api/bilder/from-url":
            assert json.loads(request.content) == {"url": "https://images.example/suppe.jpg"}
            return httpx.Response(200, json={"dateiname": "suppe.jpg"})
        assert request.url.path == "/api/rezepte/7/bilder/attach"
        assert json.loads(request.content) == {"dateiname": "suppe.jpg", "ist_haupt": True}
        return httpx.Response(200, json={"ok": True})

    client = RezeptifyClient("https://rezeptify.example", "secret", transport=httpx.MockTransport(handler))
    try:
        result = await client.update_recipe(7, ingredients=[], image_url="https://images.example/suppe.jpg")
    finally:
        await client.aclose()

    assert result["ingredients"] == []
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/api/rezepte/7"), ("PUT", "/api/rezepte/7"),
        ("POST", "/api/bilder/from-url"), ("POST", "/api/rezepte/7/bilder/attach"),
    ]


@pytest.mark.asyncio
async def test_update_recipe_surfaces_not_found_and_validation_details():
    responses = iter([
        httpx.Response(404, json={"detail": "Rezept nicht gefunden"}),
        httpx.Response(200, json=_rest_recipe()),
        httpx.Response(422, json={"detail": "titel darf nicht leer sein"}),
    ])

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    client = RezeptifyClient("https://rezeptify.example", "secret", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(RuntimeError, match="404: Rezept nicht gefunden"):
            await client.update_recipe(404, title="Unwichtig")
        with pytest.raises(RuntimeError, match="422: titel darf nicht leer sein"):
            await client.update_recipe(7, title="")
    finally:
        await client.aclose()


def test_group_fields_round_trip_through_marker_rows():
    ingredients = [
        {"amount": "3", "unit": "EL", "name": "Pfeffer", "group": "Rub"},
        {"amount": "1", "unit": "EL", "name": "Salz", "group": "Rub"},
        {"amount": "2", "unit": "kg", "name": "Rinderbrust", "group": None},
    ]
    rows = RezeptifyClient._rows_from_ingredients(ingredients)
    assert [row.get("gruppe") for row in rows] == ["Rub", None, None, None]
    assert [row.get("name") for row in rows] == [None, "Pfeffer", "Salz", "Rinderbrust"]
    assert RezeptifyClient._ingredients_from_rows(rows)[:2] == ingredients[:2]
