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
        if request.url.path == "/api/rezepte/aehnlich":
            assert request.method == "GET"
            assert request.url.params["titel"] == "Tomatensuppe"
            return httpx.Response(200, json={"treffer": []})
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
        "/api/rezepte/aehnlich", "/api/analysiere-bild", "/api/rezepte", "/api/rezepte/42/bilder/attach"
    ]
    assert all(request.headers["authorization"] == "Bearer secret" for request in requests)


@pytest.mark.asyncio
async def test_add_recipe_skips_attachment_without_downloaded_image():
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/rezepte/aehnlich":
            assert request.method == "GET"
            assert request.url.params["titel"] == "Tomatensuppe"
            return httpx.Response(200, json={"treffer": []})
        if request.url.path == "/api/analysiere-bild":
            return httpx.Response(200, json=_payload())
        return httpx.Response(201, json={"id": 3, "slug": "tomatensuppe-3", "titel": "Tomatensuppe"})

    client = RezeptifyClient("https://rezeptify.example", "secret", transport=httpx.MockTransport(handler))
    try:
        await client.add_recipe(_payload())
    finally:
        await client.aclose()
    assert paths == ["/api/rezepte/aehnlich", "/api/analysiere-bild", "/api/rezepte"]


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
                "tags": ["warm"], "beschreibung": "x" * 170,
                "favorit": 1, "bewertung": 5, "zeit_vorb": 10, "zeit_koch": 20,
            }]})
        if request.url.path == "/api/kategorien":
            return httpx.Response(200, json=["Suppen", "Desserts"])
        return httpx.Response(200, json=["warm", "schnell"])

    client = RezeptifyClient("https://rezeptify.example", "secret", transport=httpx.MockTransport(handler))
    try:
        assert await client.search_recipes("suppe", "Suppen", "warm", 5) == [{
            "id": 1, "titel": "Suppe", "slug": "suppe-1", "kategorie": "Suppen", "tags": ["warm"],
            "beschreibung": "x" * 160 + "…", "favorit": True, "bewertung": 5, "zeit_gesamt": 30,
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


@pytest.mark.asyncio
async def test_add_recipe_rejects_duplicate_before_any_post():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/api/rezepte/aehnlich"
        return httpx.Response(200, json={"treffer": [{
            "id": 7, "titel": "Tomatensuppe", "slug": "tomatensuppe-7",
        }]})

    client = RezeptifyClient("https://rezeptify.example", "secret", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(RuntimeError) as exc:
            await client.add_recipe(_payload())
        assert "ID 7: Tomatensuppe" in str(exc.value)
        assert "https://rezeptify.example/rezept/tomatensuppe-7" in str(exc.value)
        assert "update_recipe" in str(exc.value)
        assert "allow_duplicate=true" in str(exc.value)
    finally:
        await client.aclose()
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("allow_duplicate,unavailable", [(True, None), (False, 404), (False, "network")])
async def test_add_recipe_override_or_unavailable_check_still_creates(allow_duplicate, unavailable):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path == "/api/rezepte/aehnlich":
            if unavailable == "network":
                raise httpx.ConnectError("offline", request=request)
            return httpx.Response(unavailable, json={"detail": "Not found"})
        assert request.method == "POST"
        if request.url.path == "/api/analysiere-bild":
            return httpx.Response(200, json=_payload())
        assert request.url.path == "/api/rezepte"
        return httpx.Response(200, json={"id": 8})

    client = RezeptifyClient("https://rezeptify.example", "secret", transport=httpx.MockTransport(handler))
    try:
        assert await client.add_recipe(_payload(), allow_duplicate=allow_duplicate) == {"id": 8}
    finally:
        await client.aclose()
    assert paths == ([] if allow_duplicate else ["/api/rezepte/aehnlich"]) + [
        "/api/analysiere-bild", "/api/rezepte",
    ]


@pytest.mark.asyncio
async def test_search_handles_empty_and_short_descriptions_and_missing_times():
    def handler(request):
        return httpx.Response(200, json={"items": [
            {"beschreibung": None, "zeit_vorb": None, "zeit_koch": None},
            {"beschreibung": "kurz", "zeit_koch": 12},
            {"beschreibung": "x" * 160},
        ]})

    client = RezeptifyClient("https://rezeptify.example", "secret", transport=httpx.MockTransport(handler))
    try:
        results = await client.search_recipes()
    finally:
        await client.aclose()
    assert [r["beschreibung"] for r in results] == ["", "kurz", "x" * 160]
    assert [r["zeit_gesamt"] for r in results] == [0, 12, 0]
    assert all(r["favorit"] is False and r["bewertung"] is None for r in results)


def _shopping_row():
    return {"id": 42, "uuid": "7e33a52f-2517-4fd8-9ba7-6a9eb2275e7e", "name": "Milch",
            "menge": 2, "einheit": "l", "menge_text": None, "notiz": "Bio", "erledigt": False,
            "herkunft": [{"rezept_titel": "Pudding"}, {"rezept_titel": "Pudding"}]}


@pytest.mark.asyncio
async def test_shopping_client_crud_maps_fields_and_uuid():
    requests = []
    row = _shopping_row()
    ident = row["uuid"]
    expected = {"id": ident, "name": "Milch", "quantity": 2, "unit": "l",
                "quantity_text": None, "note": "Bio", "done": False, "recipes": ["Pudding"]}

    def handler(request):
        requests.append(request)
        assert request.headers["authorization"] == 'Bearer secret'
        if request.method == 'GET':
            return httpx.Response(200, json={"eintraege": [row]})
        if request.method == 'PATCH':
            assert json.loads(request.content) == {"erledigt": True, "notiz": None, "menge": 0}
            return httpx.Response(200, json={**row, "erledigt": True, "notiz": None, "menge": 0})
        if request.method == 'DELETE':
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith('erledigte-loeschen'):
            assert json.loads(request.content) == {"liste": None}
            return httpx.Response(200, json={"geloescht": 1})
        assert json.loads(request.content) == {"liste": None, "eintraege": [
            {"name": "Milch", "menge": 2, "einheit": "l", "notiz": "Bio"},
        ]}
        return httpx.Response(201, json={"eintraege": [row]})

    client = RezeptifyClient("https://rezeptify.example", "secret", transport=httpx.MockTransport(handler))
    try:
        assert await client.get_shopping_list(False) == [expected]
        assert await client.get_shopping_list(True) == [expected]
        assert await client.add_shopping_items([{"name": "Milch", "quantity": 2, "unit": "l", "note": "Bio"}]) == [expected]
        assert await client.update_shopping_item(ident, done=True, note=None, quantity=0) == {
            **expected, "done": True, "note": None, "quantity": 0,
        }
        assert await client.remove_shopping_item(ident) == {"ok": True}
        assert await client.clear_done_shopping_items() == {"geloescht": 1}
    finally:
        await client.aclose()
    assert [(r.method, r.url.path) for r in requests] == [
        ('GET', '/api/einkauf/eintraege'), ('GET', '/api/einkauf/eintraege'),
        ('POST', '/api/einkauf/eintraege'), ('PATCH', f'/api/einkauf/eintraege/{ident}'),
        ('DELETE', f'/api/einkauf/eintraege/{ident}'), ('POST', '/api/einkauf/erledigte-loeschen'),
    ]
    assert dict(requests[0].url.params) == {"erledigte": "false"}
    assert dict(requests[1].url.params) == {"erledigte": "true"}


@pytest.mark.asyncio
@pytest.mark.parametrize('servings', [None, 6])
async def test_add_recipe_to_shopping_list_uses_requested_or_recipe_servings(servings):
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == 'GET':
            assert request.url.path == '/api/rezepte/7'
            return httpx.Response(200, json={"portionen": 4})
        assert request.url.path == '/api/rezepte/7/zu-einkaufsliste'
        assert json.loads(request.content) == {"portionen": 4 if servings is None else servings}
        return httpx.Response(200, json={"eintraege": [_shopping_row()]})

    client = RezeptifyClient("https://rezeptify.example", "secret", transport=httpx.MockTransport(handler))
    try:
        items = await client.add_recipe_to_shopping_list(7, servings)
        assert items[0]["id"] == _shopping_row()["uuid"]
        assert items[0]["recipes"] == ['Pudding']
    finally:
        await client.aclose()
    assert len(requests) == (2 if servings is None else 1)


@pytest.mark.asyncio
async def test_add_week_plan_to_shopping_list_reads_resulting_items():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == 'POST':
            assert request.url.path == '/api/wochenplan/einkaufsliste'
            assert json.loads(request.content) == {"von": "2026-11-21", "bis": "2026-11-27"}
            return httpx.Response(200, json={"anzahl": 1})
        assert request.url.path == '/api/einkauf/eintraege'
        return httpx.Response(200, json={"eintraege": [_shopping_row()]})

    client = RezeptifyClient("https://rezeptify.example", "secret", transport=httpx.MockTransport(handler))
    try:
        items = await client.add_week_plan_to_shopping_list('2026-11-21', '2026-11-27')
        assert items[0]["name"] == 'Milch' and items[0]["quantity"] == 2
    finally:
        await client.aclose()
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('method,args,kwargs', [
    ('get_shopping_list', [False], {}), ('add_shopping_items', [[{"name": "Brot"}]], {}),
    ('update_shopping_item', ['missing'], {"done": True}), ('remove_shopping_item', ['missing'], {}),
    ('clear_done_shopping_items', [], {}), ('add_recipe_to_shopping_list', [7, 4], {}),
    ('add_recipe_to_shopping_list', [7, None], {}),
    ('add_week_plan_to_shopping_list', ['2026-11-21', '2026-11-27'], {}),
])
async def test_shopping_client_surfaces_api_errors(method, args, kwargs):
    client = RezeptifyClient("https://rezeptify.example", "secret", transport=httpx.MockTransport(
        lambda request: httpx.Response(404, json={"detail": "Nicht gefunden"})))
    try:
        with pytest.raises(RuntimeError, match='404: Nicht gefunden'):
            await getattr(client, method)(*args, **kwargs)
    finally:
        await client.aclose()
