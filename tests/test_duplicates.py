"""Title duplicate scores and REST/MCP integration."""
import json

import pytest

from services.duplicate_service import normalize_title, similarity, title_tokens
from test_mcp_endpoint import MCP_HEADERS, _call_tool, _initialize


@pytest.mark.parametrize("a,b,expected", [
    ("Spareribs Sous Vide: Perfekt gegarte Rippchen", "Spareribs Sous Vide mit BBQ-Sauce", 0.75),
    ("Butter Chicken", "Original Butter Chicken (Murgh Makhni)", 0.9),
    # Not detected: no artificial Hühnchen/Chicken synonyms.
    ("Hühnchen-Tikka-Masala", "Chicken Tikka Masala – Mudderns Interpretation", 0.6),
    ("Gerstensuppe", "Tomatensuppe", 0.0),
    ("Salat", "Nudelsalat auf italienisch", 0.0),
    ("Bolognese", "Lasagne: So wird der Klassiker perfekt", 0.0),
    ("Tzatziki", "tzatziki", 1.0),
    ("Tzatziki", "Tzatziki mit Gurke", 0.9),
    ("Gebratene Leber", "Gebratene Leber Berliner Art", 0.9),
    # Not detected: compounds are not split into artificial tokens.
    ("Kartoffel Gratin", "Feines Kartoffelgratin", 0.0),
])
def test_title_scores(a, b, expected):
    score = similarity(a, b)
    print(f"{a!r} / {b!r}: {score:.2f}")
    assert score == pytest.approx(expected)
    assert similarity(b, a) == pytest.approx(score)


def test_normalize_and_tokens():
    assert normalize_title("Ä Ö Ü ß Crème—BRÛLÉE!") == "a o u ss creme brulee"
    assert title_tokens("Original 2 Eier mit Öl à la Oma") == {"2", "eier", "oma"}
    assert similarity("mit", "und") == 0
    assert similarity("Ei", "Ei mit Spinat") == 0


def _create(client, title, **fields):
    response = client.post("/api/rezepte", json={"titel": title, **fields})
    assert response.status_code == 201, response.text
    return response.json()


def test_similar_rest_routes_and_pairs(client):
    original = _create(client, "Original Butter Chicken (Murgh Makhni)")
    response = client.get("/api/rezepte/aehnlich", params={"titel": "Butter Chicken"})
    assert response.status_code == 200
    assert response.json()["treffer"] == [{
        "id": original["id"], "titel": original["titel"], "slug": original["slug"],
        "kategorie": "", "aehnlichkeit": 0.9,
    }]
    assert client.get("/api/rezepte/aehnlich", params={
        "titel": "Butter Chicken", "exclude_id": original["id"],
    }).json() == {"treffer": []}
    for params in ({}, {"titel": ""}, {"titel": "   "}):
        empty = client.get("/api/rezepte/aehnlich", params=params)
        assert empty.status_code == 200
        assert empty.json() == {"treffer": []}
    second = _create(client, "Butter Chicken")
    pairs = client.get("/api/rezepte/duplikate")
    assert pairs.status_code == 200
    assert pairs.json() == {"paare": [{
        "a": {"id": original["id"], "titel": original["titel"]},
        "b": {"id": second["id"], "titel": second["titel"]}, "aehnlichkeit": 0.9,
    }]}


def _mcp_headers(client, monkeypatch):
    import mcp_server.auth as mcp_auth
    monkeypatch.setattr(mcp_auth, "MCP_API_TOKEN", "test-mcp-token")
    headers = {"Authorization": "Bearer test-mcp-token"}
    response = _initialize(client, headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    return headers


def _tool_data(result):
    assert not result.get("isError"), result
    if "structuredContent" in result:
        structured = result["structuredContent"]
        return structured.get("result", structured)
    blocks = [json.loads(block["text"]) for block in result["content"] if block["type"] == "text"]
    return blocks[0] if len(blocks) == 1 else blocks


def test_mcp_add_checks_duplicates_and_allows_override(client, monkeypatch):
    original = _create(client, "Original Butter Chicken (Murgh Makhni)")
    headers = _mcp_headers(client, monkeypatch)
    payload = {"title": "Butter Chicken", "steps": ["Kochen."]}
    rejected = _call_tool(client, headers, None, 2, "add_recipe", payload)
    assert rejected["isError"] is True
    message = "\n".join(block.get("text", "") for block in rejected["content"])
    assert f"ID {original['id']}" in message
    assert original["titel"] in message
    assert f"http://testserver/rezept/{original['slug']}" in message
    assert "update_recipe" in message and "allow_duplicate=true" in message
    assert client.get("/api/rezepte").json()["total"] == 1
    allowed = _tool_data(_call_tool(client, headers, None, 3, "add_recipe", {
        **payload, "allow_duplicate": True,
    }))
    assert allowed["id"] != original["id"]
    different = _tool_data(_call_tool(client, headers, None, 4, "add_recipe", {
        "title": "Gerstensuppe", "steps": ["Kochen."],
    }))
    assert different["titel"] == "Gerstensuppe"


def test_mcp_search_fields_and_duplicate_tool(client, monkeypatch):
    original = _create(client, "Original Butter Chicken (Murgh Makhni)",
                       beschreibung="x" * 170, zeit_vorb=10, zeit_koch=25)
    second = _create(client, "Butter Chicken")
    headers = _mcp_headers(client, monkeypatch)
    found = _tool_data(_call_tool(client, headers, None, 2, "search_recipes", {
        "query": "Murgh",
    }))
    if isinstance(found, dict):
        found = [found]
    assert found == [{
        "id": original["id"], "titel": original["titel"], "slug": original["slug"],
        "kategorie": "", "tags": [], "beschreibung": "x" * 160 + "…",
        "favorit": False, "bewertung": None, "zeit_gesamt": 35,
    }]
    response = client.post("/mcp", headers={**MCP_HEADERS, **headers}, json={
        "jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {},
    })
    assert response.status_code == 200
    tools = {tool["name"]: tool for tool in response.json()["result"]["tools"]}
    assert tools["find_duplicate_recipes"]["annotations"] == {
        "readOnlyHint": True, "destructiveHint": False,
        "idempotentHint": True, "openWorldHint": False,
    }
    pairs = _tool_data(_call_tool(client, headers, None, 4, "find_duplicate_recipes", {}))
    if isinstance(pairs, dict):
        pairs = [pairs]
    assert pairs == [{
        "a": {"id": original["id"], "titel": original["titel"]},
        "b": {"id": second["id"], "titel": second["titel"]}, "aehnlichkeit": 0.9,
    }]
