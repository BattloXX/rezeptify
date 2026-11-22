"""Category seeds, learned assignments and store-specific shopping order."""
from uuid import uuid4

import pytest

from db import get_db, init_db
from services.einkauf_woerterbuch import KATEGORIEN, WOERTERBUCH, kategorie_fuer
from tests.test_einkauf_sync import op
from tests.test_einkauf_sync_api import sync


def categories(client, laden=None):
    response = client.get('/api/einkauf/kategorien', params={} if laden is None else {'laden': laden})
    assert response.status_code == 200, response.text
    return response.json()['kategorien']


def test_seed_idempotent_and_preserves_learning(client):
    cats = categories(client)
    assert [(row['name'], row['icon']) for row in cats] == KATEGORIEN
    assert len(WOERTERBUCH) >= 300
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) AS n FROM einkauf_artikel')
            seed_count = cur.fetchone()['n']
    row = client.post('/api/einkauf/eintraege', json={'text': 'Milch'}).json()['eintraege'][0]
    learned = cats[0]['id']
    assert client.patch('/api/einkauf/eintraege/' + row['uuid'], json={'kategorie_id': learned}).status_code == 200
    init_db()
    init_db()
    assert categories(client) == cats
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM einkauf_artikel WHERE quelle='start'")
            assert cur.fetchone()['n'] == seed_count - 1
            cur.execute("SELECT kategorie_id,quelle FROM einkauf_artikel WHERE name_norm='milch'")
            assert cur.fetchone() == {'kategorie_id': learned, 'quelle': 'gelernt'}
            cur.execute('SELECT anzeigename FROM einkauf_artikel WHERE vorrat=1 ORDER BY anzeigename')
            assert {r['anzeigename'] for r in cur.fetchall()} == {'Salz', 'Pfeffer', 'Öl', 'Olivenöl', 'Zucker', 'Mehl', 'Wasser'}


@pytest.mark.parametrize('name,category', [
    ('Paradeiser', 'Obst & Gemüse'), ('Erdäpfel', 'Obst & Gemüse'), ('Marillen', 'Obst & Gemüse'),
    ('Karfiol', 'Obst & Gemüse'), ('Kren', 'Obst & Gemüse'), ('Faschiertes', 'Fleisch & Fisch'),
    ('Topfen', 'Kühlregal & Milch'), ('Schlagobers', 'Kühlregal & Milch'), ('Obers', 'Kühlregal & Milch'),
    ('Germ', 'Kühlregal & Milch'), ('Semmeln', 'Brot & Backwaren'),
    ('frische Zitronen', 'Obst & Gemüse'), ('rote Paprikas', 'Obst & Gemüse'),
    ('Bio Karotten', 'Obst & Gemüse'), ('Unbekanntes Ding', 'Sonstiges'),
])
def test_assignment_vocabulary_and_stems(client, name, category):
    cats = {row['name']: row['id'] for row in categories(client)}
    ident = str(uuid4())
    result = sync(client, ops=[op('anlegen', ident, {'name': name})])
    assert result['ergebnisse'][0]['ergebnis'] == 'ok'
    assert result['eintraege'][0]['kategorie_id'] == cats[category]
    with get_db() as conn:
        with conn.cursor() as cur:
            assert kategorie_fuer(cur, name) == cats[category]


def test_manual_assignment_learning_and_lww(client):
    cats = categories(client)
    ident = str(uuid4())
    sync(client, ops=[op('anlegen', ident, {'name': 'Milch'}, t=0)])
    sync(client, ops=[op('inhalt_setzen', ident, {'kategorie_id': cats[0]['id']}, t=20)])
    ignored = sync(client, ops=[op('inhalt_setzen', ident, {'kategorie_id': cats[1]['id']}, t=10)])
    assert ignored['ergebnisse'][0]['ergebnis'] == 'ignoriert'
    sync(client, ops=[op('loeschen', ident, {}, t=30)])
    new = client.post('/api/einkauf/eintraege', json={'text': 'Milch'}).json()['eintraege'][0]
    assert new['kategorie_id'] == cats[0]['id']
    bad = sync(client, ops=[op('inhalt_setzen', new['uuid'], {'kategorie_id': 2147483647}, t=40)])
    assert bad['ergebnisse'][0]['ergebnis'] == 'abgelehnt'
    assert client.patch('/api/einkauf/eintraege/' + new['uuid'], json={'kategorie_id': None}).status_code == 200
    with get_db() as conn:
        with conn.cursor() as cur:
            assert kategorie_fuer(cur, 'Milch') is None


def test_store_crud_order_and_list_sync(client):
    baseline = sync(client)
    cats = categories(client)
    created = client.post('/api/einkauf/laeden', json={'name': 'Markt', 'standard': True})
    assert created.status_code == 201
    shop = created.json()
    ident = shop['id']
    assert shop == {'id': ident, 'name': 'Markt', 'aktiv': True, 'standard': True}
    assert client.post('/api/einkauf/laeden', json={'name': 'Markt'}).status_code == 409
    assert client.post('/api/einkauf/laeden', json={'name': ''}).status_code == 400
    other = client.post('/api/einkauf/laeden', json={'name': 'Andere', 'standard': True}).json()
    assert not next(row for row in client.get('/api/einkauf/laeden').json()['laeden'] if row['id'] == ident)['standard']
    assert client.patch(f'/api/einkauf/laeden/{ident}', json={'name': 'Supermarkt', 'aktiv': False, 'standard': True}).status_code == 200
    assert client.patch(f'/api/einkauf/laeden/{ident}', json={'aktiv': 'ja'}).status_code == 400
    ids = [row['id'] for row in cats][::-1]
    assert client.put(f'/api/einkauf/laeden/{ident}/reihenfolge', json={'kategorien': ids}).status_code == 200
    assert [row['id'] for row in categories(client, ident)] == ids
    assert categories(client, other['id']) == cats
    for invalid in [ids[:-1], ids + [ids[0]], [True] + ids[1:], ids[:-1] + [2147483647]]:
        assert client.put(f'/api/einkauf/laeden/{ident}/reihenfolge', json={'kategorien': invalid}).status_code == 400
    path = '/api/einkauf/listen/' + baseline['liste']
    assert client.patch(path, json={'laden_id': ident}).status_code == 200
    assert sync(client, baseline['seq'])['listen'][0]['laden_id'] == ident
    assert client.patch(path, json={'laden_id': True}).status_code == 400
    assert client.patch(path, json={'laden_id': 2147483647}).status_code == 404
    assert client.patch(path, json={'laden_id': None}).status_code == 200
    assert sync(client)['listen'][0]['laden_id'] is None
    client.patch(path, json={'laden_id': ident})
    assert client.delete(f'/api/einkauf/laeden/{ident}').status_code == 200
    assert sync(client)['listen'][0]['laden_id'] is None
    assert client.delete(f'/api/einkauf/laeden/{ident}').status_code == 404
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM laden_kategorie_rang WHERE laden_id=%s', (ident,))
            assert not cur.fetchall()


def test_article_search_ranking_limits_and_literal_wildcards(client):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE einkauf_artikel SET anzahl_gekauft=5,zuletzt_gekauft='2026-01-01',
                letzte_menge=2.5,letzte_einheit='l' WHERE name_norm='milch'""")
            cur.execute("UPDATE einkauf_artikel SET anzahl_gekauft=5,zuletzt_gekauft='2026-02-01' WHERE name_norm='hafermilch'")
    response = client.get('/api/einkauf/artikel', params={'q': 'milch', 'limit': 2})
    assert response.status_code == 200
    rows = response.json()['artikel']
    assert [r['anzeigename'] for r in rows] == ['Hafermilch', 'Milch']
    assert rows[1]['letzte_menge'] == 2.5 and rows[1]['letzte_einheit'] == 'l'
    assert rows[1]['kategorie_id'] is not None and not rows[1]['vorrat']
    assert next(row for row in client.get('/api/einkauf/artikel', params={'q': 'Mehl'}).json()['artikel'] if row['anzeigename'] == 'Mehl')['vorrat']
    assert client.get('/api/einkauf/artikel', params={'q': '%'}).json()['artikel'] == []
    assert client.get('/api/einkauf/artikel', params={'limit': 501}).status_code == 400


def test_category_endpoints_require_auth(client, monkeypatch):
    import auth
    monkeypatch.setattr(auth, 'AUTH_ENABLED', True)
    for path in ('kategorien', 'laeden', 'artikel'):
        assert client.get('/api/einkauf/' + path).status_code == 401
