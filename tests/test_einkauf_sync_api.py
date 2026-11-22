"""HTTP contracts for sync clients and legacy shopping-list writers."""
import time
from uuid import uuid4

import pytest

from db import get_db
from services.einkauf_sync import parse_hlc, rang_initial
from tests.test_einkauf_sync import op


def sync(client, seit=0, ops=None, **body):
    response = client.post('/api/einkauf/sync', json={"liste": None, "seit": seit, "hlc": None, "ops": ops or [], **body})
    assert response.status_code == 200, response.text
    return response.json()


def test_empty_sync_and_list_catalog(client):
    result = sync(client)
    assert result["seq"] == 0 and result["eintraege"] == []
    assert result["aliase"] == [] and result["ergebnisse"] == []
    assert parse_hlc(result["hlc"])[2] == 'server'
    assert result["listen"] == [{"uuid": result["liste"], "name": "Einkauf", "ist_standard": True, "laden_id": None}]
    assert client.get('/api/einkauf/listen').json() == {"listen": result["listen"]}


def test_two_clients_exchange_only_changed_entries(client):
    a = sync(client)
    first, second = str(uuid4()), str(uuid4())
    a = sync(client, a["seq"], [op('anlegen', first, {"name": "Milch"}),
                               op('anlegen', second, {"name": "Brot"})])
    b = sync(client)
    a = sync(client, a["seq"], [op('status_setzen', first, {"erledigt": True}, t=20)])
    b = sync(client, b["seq"])
    assert [row["uuid"] for row in b["eintraege"]] == [first]
    assert b["eintraege"][0]["erledigt"]
    b = sync(client, b["seq"], [op('inhalt_setzen', second, {"name": "Vollkornbrot"}, t=30, device='B')])
    changes = sync(client, a["seq"])
    assert [row["uuid"] for row in changes["eintraege"]] == [second]
    assert changes["eintraege"][0]["name"] == 'Vollkornbrot'
    assert sync(client, changes["seq"])["eintraege"] == []


def test_offline_five_operations_preserve_independent_fields(client):
    ids = [str(uuid4()) for _ in range(8)]
    baseline = sync(client, ops=[op('anlegen', ident, {"name": str(i)}, t=0) for i, ident in enumerate(ids)])
    offline = [op('status_setzen', ident, {"erledigt": True}, t=10) for ident in ids[:5]]
    sync(client, baseline["seq"], [op('status_setzen', ident, {"erledigt": True}, t=20, device='B') for ident in ids[5:]] +
         [op('menge_setzen', ids[0], {"menge": 3, "einheit": None, "menge_text": None}, t=30, device='B')])
    result = sync(client, baseline["seq"], offline)
    assert [item["ergebnis"] for item in result["ergebnisse"]] == ['ok'] * 5
    assert len(result["eintraege"]) == 8
    assert all(row["erledigt"] for row in result["eintraege"])
    assert next(row for row in result["eintraege"] if row["uuid"] == ids[0])["menge"] == 3


def test_retry_has_identical_results_without_duplicate_delta_or_alias(client):
    target, alias = str(uuid4()), str(uuid4())
    sync(client, ops=[op('anlegen', target, {"name": "Milch", "menge": 1}, t=0)])
    batch = [op('anlegen', alias, {"name": "Milch", "menge": 2}), op('menge_plus', alias, {"menge": 1}, t=20)]
    first = sync(client, ops=batch)
    retry = sync(client, ops=batch)
    for key in ('ergebnisse', 'seq', 'eintraege', 'aliase'):
        assert retry[key] == first[key]
    assert first["eintraege"][0]["menge"] == 4
    assert first["aliase"] == [{"alt": alias, "ziel": target}]


def test_legacy_writes_appear_as_sync_changes(client):
    previous = sync(client)["seq"]
    created = client.post('/api/einkaufsliste', json={"name": "Milch"})
    assert created.status_code == 201
    row = created.json()
    assert type(row["id"]) is int and row["manuell"] is True
    changes = sync(client, previous)
    assert changes["eintraege"][0]["uuid"] == row["uuid"]
    previous = changes["seq"]
    assert client.patch(f'/api/einkaufsliste/{row["id"]}', json={"erledigt": True}).status_code == 200
    changes = sync(client, previous)
    assert changes["eintraege"][0]["erledigt"]
    previous = changes["seq"]
    assert client.post('/api/einkaufsliste/aufraeumen', json={}).json() == {"geloescht": 1}
    changes = sync(client, previous)
    assert changes["eintraege"][0]["geloescht"]
    assert client.post('/api/einkaufsliste/aufraeumen', json={}).json() == {"geloescht": 0}
    assert client.delete(f'/api/einkaufsliste/{row["id"]}').status_code == 404
    assert client.patch(f'/api/einkaufsliste/{row["id"]}', json={"name": "Alt"}).status_code == 404
    deleted = client.post('/api/einkaufsliste', json={"name": "Brot"}).json()
    previous = sync(client)["seq"]
    assert client.delete(f'/api/einkaufsliste/{deleted["id"]}').json() == {"ok": True}
    assert sync(client, previous)["eintraege"][0]["geloescht"]
    assert client.get('/api/einkaufsliste').json()["eintraege"] == []
    previous = sync(client)["seq"]
    rid = client.post('/api/rezepte', json={"titel": "Test", "portionen": 2,
                      "zutaten": [{"name": "Reis", "menge": "100", "einheit": "g"}]}).json()["id"]
    assert client.post(f'/api/rezepte/{rid}/zu-einkaufsliste', json={"portionen": 4}).status_code == 200
    added = sync(client, previous)["eintraege"]
    assert len(added) == 1 and added[0]["name"] == "Reis" and added[0]["menge"] == 200
    previous = sync(client)["seq"]
    assert client.post('/api/wochenplan', json={"rezept_id": rid, "datum": "2026-11-21"}).status_code == 201
    assert client.post('/api/wochenplan/einkaufsliste', json={"von": "2026-11-21", "bis": "2026-11-21"}).status_code == 200
    assert sync(client, previous)["eintraege"][0]["menge"] == 300


@pytest.mark.parametrize('seit', [-1, 1.5, '0', None, True])
def test_invalid_since(client, seit):
    assert client.post('/api/einkauf/sync', json={"seit": seit, "ops": []}).status_code == 400


def test_validation_is_per_operation(client):
    assert client.post('/api/einkauf/sync', json={"seit": 0, "ops": [{}] * 501}).status_code == 413
    assert client.post('/api/einkauf/sync', json={"seit": 0, "liste": str(uuid4())}).status_code == 404
    assert client.post('/api/einkauf/sync', json={"seit": 0, "ops": {}}).status_code == 400
    ident = str(uuid4())
    invalid = op('status_setzen', ident, {"erledigt": 'ja'})
    result = sync(client, ops=[op('anlegen', ident, {"name": "Milch"}, t=0), invalid, None,
                               op('status_setzen', ident, {"erledigt": True}, t=20)])
    assert [item["ergebnis"] for item in result["ergebnisse"]] == ['ok', 'abgelehnt', 'abgelehnt', 'ok']
    assert result["eintraege"][0]["erledigt"]


@pytest.mark.parametrize('seen', ['kaputt', 123, None, '9999999999999-ffff-client'])
def test_invalid_or_far_future_client_clock_is_ignored(client, monkeypatch, seen):
    import services.einkauf_sync as engine
    monkeypatch.setattr(engine, '_last_clock', (0, 0))
    now = int(time.time() * 1000)
    stamp = parse_hlc(sync(client, hlc=seen)["hlc"])[0]
    assert now <= stamp < now + 60000
    assert parse_hlc(engine.server_hlc())[0] < now + 60000


def test_valid_client_clock_is_observed(client, monkeypatch):
    import services.einkauf_sync as engine
    monkeypatch.setattr(engine, '_last_clock', (0, 0))
    seen = f'{int(time.time() * 1000) + 3600000:013d}-0000-client'
    assert sync(client, hlc=seen)["hlc"] > seen


def test_read_only_sync_does_not_write_or_take_update_locks(client, monkeypatch):
    from pymysql.cursors import Cursor
    baseline = sync(client)
    statements = []
    execute = Cursor.execute

    def record(self, sql, args=None):
        statements.append(sql.upper())
        return execute(self, sql, args)

    monkeypatch.setattr(Cursor, 'execute', record)
    assert sync(client, baseline["seq"], liste=baseline["liste"])["eintraege"] == []
    assert sync(client, baseline["seq"])["eintraege"] == []
    assert not any(sql.lstrip().startswith(('INSERT', 'UPDATE', 'DELETE')) or 'FOR UPDATE' in sql for sql in statements)


def test_list_isolation_and_archived_catalog(client):
    default = sync(client)["liste"]
    other, archived, ident = str(uuid4()), str(uuid4()), str(uuid4())
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO einkaufslisten (uuid,name) VALUES (%s,'Andere')", (other,))
            cur.execute("INSERT INTO einkaufslisten (uuid,name,archiviert) VALUES (%s,'Archiv',1)", (archived,))
    result = sync(client, liste=other, ops=[op('anlegen', ident, {"name": "Privat"})])
    assert result["liste"] == other and result["eintraege"][0]["uuid"] == ident
    assert {row["uuid"] for row in result["listen"]} == {default, other}
    assert client.get('/api/einkauf/listen').json()["listen"] == result["listen"]
    assert client.get('/api/einkaufsliste').json()["eintraege"] == []
    eid = result["eintraege"][0]["id"]
    assert client.delete(f'/api/einkaufsliste/{eid}').status_code == 404


def test_sync_requires_auth(client, monkeypatch):
    import auth
    monkeypatch.setattr(auth, 'AUTH_ENABLED', True)
    assert client.post('/api/einkauf/sync', json={"seit": 0}).status_code == 401
    assert client.get('/api/einkauf/listen').status_code == 401


def test_legacy_delete_and_cleanup_publish_tombstones(client):
    first = client.post('/api/einkaufsliste', json={"name": "Milch"}).json()
    second = client.post('/api/einkaufsliste', json={"name": "Brot"}).json()
    third = client.post('/api/einkaufsliste', json={"name": "Salz"}).json()
    baseline = sync(client)["seq"]
    assert client.delete(f'/api/einkaufsliste/{first["id"]}').json() == {"ok": True}
    deleted = sync(client, baseline)
    assert len(deleted["eintraege"]) == 1
    assert deleted["eintraege"][0]["uuid"] == first["uuid"]
    assert deleted["eintraege"][0]["geloescht"] is True
    assert client.delete(f'/api/einkaufsliste/{first["id"]}').status_code == 404
    assert client.patch(f'/api/einkaufsliste/{first["id"]}', json={"name": "Alt"}).status_code == 404
    assert client.patch('/api/einkaufsliste/2147483647', json={"erledigt": True}).status_code == 404
    assert client.delete('/api/einkaufsliste/2147483647').status_code == 404
    assert client.patch(f'/api/einkaufsliste/{second["id"]}', json={"erledigt": True}).status_code == 200
    baseline = sync(client)["seq"]
    assert client.post('/api/einkaufsliste/aufraeumen').json() == {"geloescht": 1}
    changes = sync(client, baseline)
    assert len(changes["eintraege"]) == 1
    assert changes["eintraege"][0]["uuid"] == second["uuid"]
    assert changes["eintraege"][0]["geloescht"] is True
    assert [row["uuid"] for row in client.get('/api/einkaufsliste').json()["eintraege"]] == [third["uuid"]]
    assert client.post('/api/einkaufsliste/aufraeumen').json() == {"geloescht": 0}


def test_legacy_patch_fields_and_rank_are_synced(client):
    first = client.post('/api/einkaufsliste', json={"name": "Kartoffeln", "menge": 1, "einheit": "kg"}).json()
    second = client.post('/api/einkaufsliste', json={"name": "Petersilie", "menge": 1, "einheit": "Bund"}).json()
    baseline = sync(client)["seq"]
    updated = client.patch(f'/api/einkaufsliste/{first["id"]}', json={"name": "Festkochende", "menge": 1.5, "erledigt": True})
    assert updated.status_code == 200
    row = updated.json()
    assert (row["name"], row["menge"], row["einheit"], row["erledigt"]) == ('Festkochende', 1.5, 'kg', True)
    assert client.patch(f'/api/einkaufsliste/{second["id"]}', json={"menge": 2}).json()["einheit"] == 'Bund'
    assert client.patch(f'/api/einkaufsliste/{first["id"]}', json={"erledigt": False}).status_code == 200
    assert client.patch(f'/api/einkaufsliste/{second["id"]}', json={"sortierung": 0}).status_code == 200
    listed = client.get('/api/einkaufsliste').json()["eintraege"]
    assert [row["uuid"] for row in listed] == [second["uuid"], first["uuid"]]
    changes = sync(client, baseline)
    assert len(changes["eintraege"]) == 2
    moved = next(row for row in changes["eintraege"] if row["uuid"] == second["uuid"])
    assert moved["rang"] != second["rang"] and moved["hlc_position"] > second["hlc_position"]
    assert client.patch(f'/api/einkaufsliste/{first["id"]}', json={"menge_text": "nach Bedarf", "menge": None, "einheit": None}).status_code == 200
    changed = sync(client, changes["seq"])["eintraege"][0]
    assert changed["menge"] is None and changed["einheit"] is None and changed["menge_text"] == 'nach Bedarf'
    before = sync(client)["seq"]
    assert client.patch(f'/api/einkaufsliste/{first["id"]}', json={"name": "Zurückrollen", "menge": "kaputt"}).status_code == 400
    assert sync(client, before)["eintraege"] == []
    assert next(row for row in client.get('/api/einkaufsliste').json()["eintraege"] if row["uuid"] == first["uuid"])["name"] == 'Festkochende'


def test_legacy_patch_observes_newer_client_field_clock(client, monkeypatch):
    import services.einkauf_sync as engine
    monkeypatch.setattr(engine, '_last_clock', (0, 0))
    row = client.post('/api/einkaufsliste', json={"name": "Milch"}).json()
    newer = op('status_setzen', row["uuid"], {"erledigt": True})
    newer["hlc"] = f'{int(time.time() * 1000) + 3600000:013d}-0000-client'
    assert sync(client, ops=[newer])["eintraege"][0]["erledigt"] is True
    assert client.patch(f'/api/einkaufsliste/{row["id"]}', json={"erledigt": False}).json()["erledigt"] is False


def test_cleanup_handles_more_than_500_completed_entries(client):
    batch = []
    for i in range(501):
        ident = str(uuid4())
        batch.extend([op('anlegen', ident, {"name": f'Artikel {i}', "rang": rang_initial(i)}, t=0),
                      op('status_setzen', ident, {"erledigt": True}, t=10)])
    for start in range(0, len(batch), 500):
        baseline = sync(client, ops=batch[start:start + 500])
        assert all(item["ergebnis"] == "ok" for item in baseline["ergebnisse"])
    assert client.post('/api/einkaufsliste/aufraeumen').json() == {"geloescht": 501}
    changes = sync(client, baseline["seq"])
    assert len(changes["eintraege"]) == 501
    assert all(row["geloescht"] for row in changes["eintraege"])
    assert client.get('/api/einkaufsliste').json()["eintraege"] == []
