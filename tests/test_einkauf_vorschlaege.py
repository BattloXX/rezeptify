"""Purchase learning, cached-suggestion contract and pantry integration on MariaDB."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import json

import pytest

from db import get_db
from services.einkauf_sync import apply_ops, server_op, standard_liste
from test_mcp_endpoint import _call_tool


def sql(statement, args=(), one=False):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(statement, args)
            return cur.fetchone() if one else cur.fetchall()


def article(name='milch'):
    return sql('SELECT * FROM einkauf_artikel WHERE name_norm=%s', (name,), one=True)


def add(client, name='Milch', **fields):
    response = client.post('/api/einkauf/eintraege', json={'eintraege': [{'name': name, **fields}]})
    assert response.status_code == 201, response.text
    return response.json()['eintraege'][0]['uuid']


def status(ident, done):
    operation = server_op('status_setzen', ident, {'erledigt': done})
    with get_db() as conn:
        with conn.cursor() as cur:
            result = apply_ops(cur, standard_liste(cur), [operation])
    assert result['ergebnisse'][0]['ergebnis'] == 'ok'
    return operation


def test_three_purchases_interval_and_retry(client):
    ident = add(client, menge=2, einheit='l')
    for purchase in range(3):
        if purchase:
            # Reopening after the undo window keeps the old purchase.
            sql("UPDATE einkauf_ops SET daten=JSON_REMOVE(daten,'$._kauf') WHERE eintrag_uuid=%s", (ident,))
            status(ident, False)
            sql('UPDATE einkauf_artikel SET zuletzt_gekauft=DATE_SUB(UTC_TIMESTAMP(),INTERVAL 5 DAY) WHERE name_norm=%s', ('milch',))
        operation = status(ident, True)
        with get_db() as conn:
            with conn.cursor() as cur:
                apply_ops(cur, standard_liste(cur), [operation])
        assert article()['anzahl_gekauft'] == purchase + 1
    learned = article()
    assert float(learned['intervall_tage']) == pytest.approx(5, abs=.01)
    assert learned['letzte_menge'] == 2 and learned['letzte_einheit'] == 'l'
    assert learned['kategorie_id'] is not None
    # A new op repeating the same status must also not count a purchase.
    status(ident, True)
    assert article()['anzahl_gekauft'] == 3


def test_quick_undo_restores_previous_purchase_even_after_repeated_status(client):
    ident = add(client)
    sql("UPDATE einkauf_artikel SET anzahl_gekauft=4,intervall_tage=8,zuletzt_gekauft=DATE_SUB(UTC_TIMESTAMP(),INTERVAL 5 DAY) WHERE name_norm='milch'")
    before = article()
    status(ident, True)
    assert article()['anzahl_gekauft'] == 5
    assert article()['intervall_tage'] == Decimal('7.10')
    status(ident, True)
    status(ident, False)
    after = article()
    for field in ('anzahl_gekauft', 'zuletzt_gekauft', 'intervall_tage'):
        assert after[field] == before[field]
    status(ident, False)
    assert article()['anzahl_gekauft'] == 4


def test_same_trip_keeps_interval_and_late_undo_keeps_purchase(client):
    ident = add(client, 'Spezialbrot')
    status(ident, True)
    sql("UPDATE einkauf_artikel SET intervall_tage=6 WHERE name_norm='spezialbrot'")
    sql("UPDATE einkauf_ops SET daten=JSON_SET(daten,'$._kauf.zeit',DATE_FORMAT(DATE_SUB(UTC_TIMESTAMP(),INTERVAL 11 MINUTE),'%%Y-%%m-%%dT%%H:%%i:%%s')) WHERE eintrag_uuid=%s AND typ='status_setzen'", (ident,))
    status(ident, False)
    assert article('spezialbrot')['anzahl_gekauft'] == 1
    status(ident, True)
    assert article('spezialbrot')['anzahl_gekauft'] == 2
    assert article('spezialbrot')['intervall_tage'] == 6


def seed_article(name, count=3, days=10, interval=5, hidden=0, hidden_days=None):
    sql('''INSERT INTO einkauf_artikel
        (name_norm,anzeigename,anzahl_gekauft,zuletzt_gekauft,intervall_tage,ausgeblendet,ausgeblendet_bis)
        VALUES (%s,%s,%s,DATE_SUB(UTC_TIMESTAMP(),INTERVAL %s DAY),%s,%s,DATE_ADD(UTC_TIMESTAMP(),INTERVAL %s DAY))''',
        (name, name, count, days, interval, hidden, hidden_days))


def test_suggestions_sorting_filters_limits_and_list_scope(client):
    seed_article('stark', count=4, days=20)
    seed_article('frisch', count=8, days=1)
    seed_article('normal', count=5, days=10)
    seed_article('dauerhaft', hidden=1)
    seed_article('morgen', hidden=1, hidden_days=1)
    seed_article('abgelaufen', hidden=1, hidden_days=-1)
    seed_article('offen')
    add(client, 'offen')
    result = client.get('/api/einkauf/vorschlaege').json()
    assert [row['name_norm'] for row in result['faellig']] == ['stark', 'abgelaufen', 'normal']
    assert result['faellig'][0]['tage_ueber'] == pytest.approx(15, abs=.01)
    assert [row['name_norm'] for row in result['haeufig']][:3] == ['frisch', 'normal', 'stark']
    assert result['zuletzt'][0]['name_norm'] == 'frisch'
    assert not {'dauerhaft', 'morgen', 'offen'} & {row['name_norm'] for row in result['zuletzt']}
    assert client.get('/api/einkauf/vorschlaege?liste=ungueltig').status_code == 404
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO einkaufslisten (uuid,name) VALUES (UUID(),'Andere')")
            cur.execute("SELECT uuid FROM einkaufslisten WHERE name='Andere'")
            other = cur.fetchone()['uuid']
    assert 'offen' in {row['name_norm'] for row in client.get('/api/einkauf/vorschlaege', params={'liste': other}).json()['haeufig']}
    for i in range(25):
        seed_article(f'limit{i}')
    capped = client.get('/api/einkauf/vorschlaege').json()
    assert len(capped['faellig']) == 12
    assert len(capped['haeufig']) == len(capped['zuletzt']) == 20


def test_hide_unhide_and_validation(client):
    seed_article('artikel')
    for days in (7, None):
        assert client.post('/api/einkauf/vorschlaege/ausblenden', json={'name': 'artikel', 'tage': days}).status_code == 200
        assert not client.get('/api/einkauf/vorschlaege').json()['haeufig']
        assert article('artikel')['ausgeblendet'] == 1
    assert client.post('/api/einkauf/vorschlaege/ausblenden', json={'name': 'artikel', 'tage': 0}).status_code == 200
    assert len(client.get('/api/einkauf/vorschlaege').json()['haeufig']) == 1
    for body in ({'name': 'x', 'tage': True}, {'name': 'x', 'tage': -1}, {'name': ''}):
        assert client.post('/api/einkauf/vorschlaege/ausblenden', json=body).status_code == 400
    assert client.get('/api/einkauf/artikel?limit=500').status_code == 200


def recipe(client):
    response = client.post('/api/rezepte', json={'titel': 'Suppe', 'portionen': 2, 'zutaten': [
        {'name': 'Salz', 'menge': '1', 'einheit': 'TL'}, {'name': 'Karotten', 'menge': '200', 'einheit': 'g'}]})
    assert response.status_code == 201, response.text
    return response.json()['id']


def test_week_plan_vienna_window_and_recipe_pantry(client):
    rid = recipe(client)
    today = datetime.now(timezone.utc).astimezone(ZoneInfo('Europe/Vienna')).date()
    for offset in (-1, 0, 6, 7):
        assert client.post('/api/wochenplan', json={'rezept_id': rid, 'datum': str(today + timedelta(days=offset)), 'portionen': 4}).status_code == 201
    planned = client.get('/api/einkauf/vorschlaege').json()['wochenplan']
    assert [row['datum'] for row in planned] == [str(today), str(today + timedelta(days=6))]
    result = client.post(f'/api/rezepte/{rid}/zu-einkaufsliste', json={'portionen': 4}).json()
    assert result['vorrat'] == [{'name': 'Salz', 'menge_text': '2 TL'}]
    assert [row['name'] for row in result['eintraege']] == ['Karotten']
    assert result['eintraege'][0]['menge'] == 400
    assert client.get('/api/einkauf/vorschlaege').json()['wochenplan'] == []
    assert client.post('/api/einkauf/artikel/vorrat', json={'name': 'Salz', 'vorrat': False}).status_code == 200
    result = client.post(f'/api/rezepte/{rid}/zu-einkaufsliste', json={'portionen': 2}).json()
    assert result['vorrat'] == [] and len(result['eintraege']) == 2


def test_week_plan_pantry_and_new_pantry_article(client):
    rid = recipe(client)
    today = str(datetime.now(timezone.utc).astimezone(ZoneInfo('Europe/Vienna')).date())
    client.post('/api/wochenplan', json={'rezept_id': rid, 'datum': today})
    assert client.post('/api/einkauf/artikel/vorrat', json={'name': 'Karotten', 'vorrat': True}).status_code == 200
    result = client.post('/api/wochenplan/einkaufsliste', json={'von': today, 'bis': today}).json()
    assert result['anzahl'] == 0
    assert {row['name'] for row in result['vorrat']} == {'Salz', 'Karotten'}
    assert client.post('/api/einkauf/artikel/vorrat', json={'name': 'Neu', 'vorrat': True}).status_code == 200
    assert article('neu')['vorrat'] == 1
    assert client.post('/api/einkauf/artikel/vorrat', json={'name': 'Neu', 'vorrat': 1}).status_code == 400


def test_mcp_suggestions_and_skipped_pantry(client):
    for i in range(12):
        seed_article(f'mcp{i}')
    rid = recipe(client)
    headers = {'Authorization': 'Bearer test-mcp-token'}
    result = _call_tool(client, headers, None, 1, 'get_shopping_suggestions', {})
    assert not result.get('isError'), result
    data = result.get('structuredContent') or json.loads(result['content'][0]['text'])
    assert len(data['haeufig']) == 10 and len(data['faellig']) == 12
    assert 'wochenplan' in data
    result = _call_tool(client, headers, None, 2, 'add_recipe_to_shopping_list', {'recipe_id': rid})
    assert not result.get('isError'), result
    data = result.get('structuredContent') or json.loads(result['content'][0]['text'])
    assert data['skipped_pantry'] == [{'name': 'Salz', 'menge_text': '1 TL'}]
    assert [row['name'] for row in data['items']] == ['Karotten']
