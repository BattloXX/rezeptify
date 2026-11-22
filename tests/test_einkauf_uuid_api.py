"""UUID shopping API contracts, including sync visibility and alias resolution."""
import time
from uuid import uuid4

import pytest

from db import get_db
from tests.test_einkauf_sync_api import sync
from tests.test_einkauf_sync import op


BASE = '/api/einkauf/eintraege'


def add(client, *items, liste=None):
    response = client.post(BASE, json={"liste": liste, "eintraege": list(items)})
    assert response.status_code == 201, response.text
    return response.json()["eintraege"]


def test_uuid_crud_and_sync(client):
    baseline = sync(client)["seq"]
    row = add(client, {"name": "Kartoffeln", "menge": 2, "einheit": "kg", "notiz": "festkochend"})[0]
    assert row["manuell"] is True and row["notiz"] == 'festkochend'
    changes = sync(client, baseline)
    assert [entry["uuid"] for entry in changes["eintraege"]] == [row["uuid"]]
    path = f'{BASE}/{row["uuid"]}'
    updated = client.patch(path, json={"name": "Bio Kartoffeln", "notiz": None, "menge": 3, "erledigt": True})
    assert updated.status_code == 200
    assert (updated.json()["menge"], updated.json()["einheit"], updated.json()["notiz"]) == (3, 'kg', None)
    assert client.get(BASE).json()["eintraege"] == []
    assert client.get(BASE, params={"erledigte": True}).json()["eintraege"][0]["erledigt"] is True
    changes = sync(client, changes["seq"])
    assert changes["eintraege"][0]["name"] == 'Bio Kartoffeln'
    assert changes["eintraege"][0]["erledigt"] is True
    assert client.delete(path).json() == {"ok": True}
    assert sync(client, changes["seq"])["eintraege"][0]["geloescht"] is True
    assert client.get(BASE, params={"erledigte": True}).json()["eintraege"] == []
    assert client.delete(path).status_code == 404
    assert client.patch(path, json={"name": "Alt"}).status_code == 404


@pytest.mark.parametrize('ident', [str(uuid4()), 'invalid'])
def test_unknown_uuid(client, ident):
    assert client.patch(f'{BASE}/{ident}', json={"erledigt": True}).status_code == 404
    assert client.delete(f'{BASE}/{ident}').status_code == 404


def test_merge_and_alias(client):
    rows = add(client, {"name": "Milch", "menge": 1, "einheit": "l"},
               {"name": " milch ", "menge": 500, "einheit": "ml"},
               {"name": "Milch", "menge": 1, "einheit": "Dose"})
    assert rows[0]["uuid"] == rows[1]["uuid"] != rows[2]["uuid"]
    assert rows[1]["zusammengefuehrt"] is True
    assert (rows[1]["menge"], rows[1]["einheit"]) == (1.5, 'l')
    alias = sync(client)["aliase"][0]["alt"]
    assert client.patch(f'{BASE}/{alias}', json={"notiz": "kalt"}).json()["uuid"] == rows[0]["uuid"]
    assert client.delete(f'{BASE}/{alias}').json() == {"ok": True}
    assert client.patch(f'{BASE}/{alias}', json={"erledigt": True}).status_code == 404
    assert client.delete(f'{BASE}/{alias}').status_code == 404


@pytest.mark.parametrize('items', [[], [{}] * 101, None, {}, [None], [{}], [{"name": ""}],
    [{"name": " "}], [{"name": 3}], [{"name": "x" * 256}], [{"name": "x", "menge": "2"}],
    [{"name": "x", "einheit": "x" * 33}], [{"name": "x", "notiz": "x" * 256}],
    [{"name": "x", "menge_text": "x" * 65}], [{"name": "x", "erledigt": True}]])
def test_add_validation(client, items):
    baseline = sync(client)["seq"]
    response = client.post(BASE, json={"eintraege": items})
    assert response.status_code == 400, response.text
    assert sync(client, baseline)["eintraege"] == []


@pytest.mark.parametrize('body', [{}, {"name": None}, {"name": " "}, {"menge": True},
    {"erledigt": "ja"}, {"notiz": 12}, {"menge_text": "x" * 65}, {"herkunft": []},
    {"name": "Zurückrollen", "menge": "kaputt"}])
def test_patch_validation_is_atomic(client, body):
    row = add(client, {"name": "Milch"})[0]
    baseline = sync(client)["seq"]
    assert client.patch(f'{BASE}/{row["uuid"]}', json=body).status_code == 400
    assert sync(client, baseline)["eintraege"] == []
    assert client.get(BASE).json()["eintraege"][0]["name"] == 'Milch'


def test_batch_validation_rolls_back_merges(client):
    row = add(client, {"name": "Milch", "menge": 1})[0]
    baseline = sync(client)["seq"]
    assert client.post(BASE, json={"eintraege": [{"name": "Milch", "menge": 2}, {"name": ""}]}).status_code == 400
    assert sync(client, baseline)["eintraege"] == []
    assert sync(client)["aliase"] == []
    assert client.get(BASE).json()["eintraege"][0]["menge"] == row["menge"]


def test_lists_sorting_and_cleanup(client):
    other = str(uuid4())
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO einkaufslisten (uuid,name) VALUES (%s,'Andere')", (other,))
    first, second = add(client, {"name": "Brot"}, {"name": "Salz"})
    foreign = add(client, {"name": "Privat"}, liste=other)[0]
    client.patch(f'{BASE}/{first["uuid"]}', json={"erledigt": True})
    client.patch(f'{BASE}/{foreign["uuid"]}', json={"erledigt": True})
    assert [r["uuid"] for r in client.get(BASE, params={"erledigte": True}).json()["eintraege"]] == [second["uuid"], first["uuid"]]
    assert client.get(BASE, params={"erledigte": False}).json()["eintraege"][0]["uuid"] == second["uuid"]
    baseline = sync(client)["seq"]
    assert client.post('/api/einkauf/erledigte-loeschen', json={"liste": None}).json() == {"geloescht": 1}
    assert sync(client, baseline)["eintraege"][0]["geloescht"] is True
    assert client.post('/api/einkauf/erledigte-loeschen', json={}).json() == {"geloescht": 0}
    assert client.get(BASE, params={"liste": other, "erledigte": True}).json()["eintraege"][0]["uuid"] == foreign["uuid"]
    assert client.post('/api/einkauf/erledigte-loeschen', json={"liste": other}).json() == {"geloescht": 1}


@pytest.mark.parametrize('liste', [str(uuid4()), 'invalid', 12])
def test_unknown_list(client, liste):
    assert client.get(BASE, params={"liste": liste}).status_code == 404
    assert client.post(BASE, json={"liste": liste, "eintraege": [{"name": "Brot"}]}).status_code == 404
    assert client.post('/api/einkauf/erledigte-loeschen', json={"liste": liste}).status_code == 404


def test_patch_observes_future_client_clock_and_preserves_amount_fields(client):
    row = add(client, {"name": "Salz", "menge": 1, "einheit": "g"})[0]
    newer = op('status_setzen', row["uuid"], {"erledigt": True})
    newer["hlc"] = f'{int(time.time() * 1000) + 3600000:013d}-0000-client'
    sync(client, ops=[newer])
    result = client.patch(f'{BASE}/{row["uuid"]}', json={"erledigt": False, "menge_text": "nach Bedarf", "menge": None})
    assert result.status_code == 200
    assert result.json()["erledigt"] is False and result.json()["menge"] is None
    assert result.json()["einheit"] == 'g' and result.json()["menge_text"] == 'nach Bedarf'


def test_uuid_routes_require_auth(client, monkeypatch):
    import auth
    monkeypatch.setattr(auth, 'AUTH_ENABLED', True)
    assert client.get(BASE).status_code == 401
    assert client.post(BASE, json={"eintraege": [{"name": "Brot"}]}).status_code == 401
    assert client.patch(f'{BASE}/{uuid4()}', json={"erledigt": True}).status_code == 401
    assert client.delete(f'{BASE}/{uuid4()}').status_code == 401
    assert client.post('/api/einkauf/erledigte-loeschen', json={}).status_code == 401


def test_free_text_add(client):
    response = client.post(BASE, json={"text": "• 1,5 l Milch\n2 kg Kartoffeln (Bio, regional); Brot, Eier 10 Stk"})
    assert response.status_code == 201, response.text
    rows = response.json()["eintraege"]
    assert [row["name"] for row in rows] == ["Milch", "Kartoffeln", "Brot", "Eier"]
    assert (rows[0]["menge"], rows[0]["einheit"]) == (1.5, "l")
    assert rows[1]["notiz"] == "Bio, regional"
    assert rows[3]["menge"] == 10
    merged = client.post(BASE, json={"text": "500ml Milch"}).json()["eintraege"][0]
    assert merged["uuid"] == rows[0]["uuid"] and merged["menge"] == 2


@pytest.mark.parametrize('body', [{"text": ""}, {"text": " ; "}, {"text": None}, {"text": 12},
    {"text": "x" * 2001}, {"text": "Brot", "eintraege": []}, {"text": "(Bio)"},
    {"text": ";".join(f"Artikel {i}" for i in range(101))}])
def test_free_text_validation(client, body):
    assert client.post(BASE, json=body).status_code == 400
    assert client.get(BASE).json()["eintraege"] == []
