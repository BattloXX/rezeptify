"""Multiple shopping lists, cross-list moves and MCP list-name selection."""
import json
from uuid import uuid4

import pytest

from db import get_db
from tests.test_einkauf_sync_api import sync
from tests.test_einkauf_uuid_api import add, BASE
from tests.test_mcp_endpoint import _call_tool

LISTS = '/api/einkauf/listen'


def create(client, name='Markt'):
    response = client.post(LISTS, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def test_list_crud_standard_and_archive_rules(client):
    standard = sync(client)["liste"]
    other = create(client)
    assert other["offen"] == 0 and not other["ist_standard"]
    assert client.post(LISTS, json={"name": "mArKt"}).status_code == 409
    assert client.patch(f'{LISTS}/{standard}', json={"archiviert": True}).status_code == 400
    assert client.delete(f'{LISTS}/{other["uuid"]}').status_code == 400
    response = client.patch(f'{LISTS}/{other["uuid"]}', json={"ist_standard": True, "name": "Wochenmarkt"})
    assert response.status_code == 200
    assert sync(client)["liste"] == other["uuid"]
    rows = client.get(LISTS).json()["listen"]
    assert sum(row["ist_standard"] for row in rows) == 1
    assert client.patch(f'{LISTS}/{standard}', json={"archiviert": True}).status_code == 200
    assert len(client.get(LISTS).json()["listen"]) == 1
    assert len(client.get(LISTS, params={"archivierte": True}).json()["listen"]) == 2
    assert client.patch(f'{LISTS}/{standard}', json={"ist_standard": True}).status_code == 400
    assert client.delete(f'{LISTS}/{standard}').json() == {"ok": True}
    assert client.delete(f'{LISTS}/{standard}').status_code == 404


@pytest.mark.parametrize('body', [{}, {"name": ""}, {"name": " "}, {"name": "x" * 121},
    {"name": None}, {"name": 12}, {"name": "Gut", "archiviert": False}])
def test_list_create_validation(client, body):
    assert client.post(LISTS, json=body).status_code == 400


@pytest.mark.parametrize('body', [{}, {"archiviert": 1}, {"ist_standard": False},
    {"ist_standard": "ja"}, {"name": "x" * 121}, {"laden_id": True}, {"fremd": 1}])
def test_list_patch_validation(client, body):
    ident = sync(client)["liste"]
    assert client.patch(f'{LISTS}/{ident}', json=body).status_code == 400


def test_archive_names_and_unarchive_collision(client):
    row = create(client)
    path = f'{LISTS}/{row["uuid"]}'
    assert client.patch(path, json={"archiviert": True}).status_code == 200
    create(client)
    assert client.patch(path, json={"archiviert": False}).status_code == 409
    assert client.patch(path, json={"archiviert": False, "name": "Markt 2"}).status_code == 200


def test_move_preserves_data_and_changes_both_sequences(client):
    source = sync(client)["liste"]
    target = create(client)["uuid"]
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM einkauf_kategorien WHERE aktiv=1 LIMIT 1")
            category = cur.fetchone()["id"]
    original = add(client, {"name": "Milch", "menge": 2, "einheit": "l", "notiz": "Bio", "kategorie_id": category})[0]
    # Origins are written through sync, as with a recipe.
    from tests.test_einkauf_sync import op
    ident = str(uuid4())
    sync(client, ops=[op('anlegen', ident, {"name": "Mehl", "menge": 500, "einheit": "g",
        "herkunft": [{"rezept_id": 7, "rezept_titel": "Brot"}], "notiz": "fein", "kategorie_id": category})])
    before = sync(client)["seq"]
    result = client.post(f'{BASE}/{ident}/verschieben', json={"ziel_liste": target})
    assert result.status_code == 200, result.text
    new_id = result.json()["uuid"]
    assert new_id != ident
    old = sync(client, before)
    new = sync(client, liste=target)
    assert old["seq"] > before and old["eintraege"][0]["geloescht"]
    assert new["seq"] > 0 and new["eintraege"][0]["uuid"] == new_id
    moved = new["eintraege"][0]
    assert moved["herkunft"] == [{"rezept_id": 7, "rezept_titel": "Brot"}]
    assert (moved["menge"], moved["einheit"], moved["notiz"], moved["kategorie_id"]) == (500, 'g', 'fein', category)
    assert client.post(f'{BASE}/{original["uuid"]}/verschieben', json={"ziel_liste": source}).status_code == 400
    assert client.post(f'{BASE}/{original["uuid"]}/verschieben', json={"ziel_liste": str(uuid4())}).status_code == 404
    assert client.patch(f'{BASE}/{new_id}', params={"liste": source}, json={"erledigt": True}).status_code == 404
    assert client.delete(f'{BASE}/{new_id}', params={"liste": source}).status_code == 404


def test_delete_archived_list_removes_entries_ops_and_aliases(client):
    target = create(client)["uuid"]
    add(client, {"name": "Brot"}, {"name": "Brot"}, liste=target)
    assert sync(client, liste=target)["aliase"]
    assert client.patch(f'{LISTS}/{target}', json={"archiviert": True}).status_code == 200
    assert client.delete(f'{LISTS}/{target}').status_code == 200
    with get_db() as conn:
        with conn.cursor() as cur:
            for table in ('einkaufsliste_eintraege', 'einkauf_ops', 'einkauf_aliase'):
                cur.execute(f'SELECT COUNT(*) AS n FROM {table} WHERE liste_uuid=%s', (target,))
                assert cur.fetchone()["n"] == 0


def test_recipe_and_week_plan_in_named_list_skip_pantry(client):
    target = create(client)["uuid"]
    recipe = client.post('/api/rezepte', json={"titel": "Brot", "portionen": 2,
        "zutaten": [{"name": "Dinkelmehl", "menge": "500", "einheit": "g"}, {"name": "Salz", "menge": "1", "einheit": "TL"}],
        "zubereitung": "Backen"}).json()
    result = client.post(f'/api/rezepte/{recipe["id"]}/zu-einkaufsliste', json={"portionen": 4, "liste": target})
    assert result.status_code == 200, result.text
    assert [row["name"] for row in result.json()["eintraege"]] == ['Dinkelmehl']
    assert result.json()["vorrat"][0]["name"] == 'Salz'
    client.post('/api/wochenplan', json={"rezept_id": recipe["id"], "datum": "2026-11-22"})
    result = client.post('/api/wochenplan/einkaufsliste', json={"von": "2026-11-22", "bis": "2026-11-22", "liste": target})
    assert result.status_code == 200, result.text
    assert client.get(BASE).json()["eintraege"] == []
    row = client.get(BASE, params={"liste": target}).json()["eintraege"][0]
    assert (row["menge"], row["einheit"]) == (1500, 'g')


def test_mcp_list_names_and_read_only_catalog(client):
    create(client, 'Wochenmarkt')
    headers = {"Authorization": "Bearer test-mcp-token"}
    def call(name, args):
        return _call_tool(client, headers, None, 1, name, args)
    catalog = call('list_shopping_lists', {})
    assert not catalog.get('isError'), catalog
    assert 'Wochenmarkt' in json.dumps(catalog, ensure_ascii=False)
    added = call('add_to_shopping_list', {"text": "2 l Milch", "list_name": "wOCHENMARKT"})
    assert not added.get('isError'), added
    listed = call('get_shopping_list', {"list_name": "Wochenmarkt"})
    assert 'Milch' in json.dumps(listed, ensure_ascii=False)
    assert client.get(BASE).json()["eintraege"] == []
    unknown = call('get_shopping_list', {"list_name": "Fehlt"})
    assert unknown.get('isError') and 'Wochenmarkt' in json.dumps(unknown, ensure_ascii=False)
