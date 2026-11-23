"""Lossless export coverage against the production MariaDB schema."""
import json
from pathlib import Path

import pytest


@pytest.fixture()
def export_data(client):
    from db import get_db

    ingredients = [{"gruppe": "Teig"}, {"name": "Mehl", "menge": 125.5, "einheit": "g"}]
    with get_db() as conn:
        with conn.cursor() as cur:
            ids = []
            for title, source in [("Export A", "manuell"), ("Export B", "keine")]:
                cur.execute("""INSERT INTO rezepte (titel, slug, beschreibung, zutaten, tags,
                    zubereitung, schritte_quelle, portionen, zeit_vorb, zeit_koch,
                    schwierigkeit, kategorie, quelle_url, quelle_typ, quelldatei,
                    bewertung, favorit, kalorien_pro_portion, erstellt_am, geaendert_am)
                    VALUES (%s, %s, 'Beschreibung', %s, %s, 'Mischen. Backen.', %s,
                    3, 10, 20, 'leicht', 'Backen', 'https://example.test/rezept', 'datei',
                    'quelle.pdf', 4, 1, 321, '2026-01-02 03:04:05', '2026-02-03 04:05:06')""",
                            (title, title.lower().replace(" ", "-"), json.dumps(ingredients),
                             json.dumps(["süß", "Ofen"]), source))
                ids.append(cur.lastrowid)
            cur.execute("INSERT INTO bilder (rezept_id, dateiname, ist_haupt) VALUES (%s, 'kuchen.jpg', 1)",
                        (ids[0],))
            image_id = cur.lastrowid
            # Insert in reverse order to exercise position ordering.
            for position, indices, timer in [(2, None, None), (1, '[1]', 120)]:
                cur.execute("""INSERT INTO rezept_schritte
                    (rezept_id, position, text, zutaten_indices, timer_sekunden)
                    VALUES (%s, %s, %s, %s, %s)""",
                            (ids[0], position, f"Schritt {position}", indices, timer))
            cur.execute("""INSERT INTO kochhistorie (rezept_id, gekocht_am, portionen_verwendet,
                notiz, nachtraegliche_bewertung) VALUES (%s, '2026-03-04 05:06:07', 2, 'Gut!', 5)""",
                        (ids[0],))
            history_id = cur.lastrowid
            cur.execute("""INSERT INTO wochenplan (rezept_id, datum, mahlzeit, portionen, notiz)
                VALUES (%s, '2026-04-05', 'abend', 2, 'Plan')""", (ids[0],))
            cur.execute("SELECT id FROM einkauf_kategorien ORDER BY id LIMIT 1")
            category_id = cur.fetchone()["id"]
            cur.execute("INSERT INTO laeden (name, standard) VALUES ('Export Laden', 1)")
            store_id = cur.lastrowid
            cur.execute("INSERT INTO laden_kategorie_rang VALUES (%s, %s, 'abc')",
                        (store_id, category_id))
            cur.execute("""INSERT INTO einkauf_artikel (name_norm, anzeigename, kategorie_id,
                letzte_menge, intervall_tage, zuletzt_gekauft)
                VALUES ('export mehl', 'Export Mehl', %s, 1.125, 2.50, '2026-01-02 03:04:05')""",
                        (category_id,))
            lists = ['00000000-0000-0000-0000-000000000001',
                     '00000000-0000-0000-0000-000000000002']
            for archived, list_id in enumerate(lists):
                cur.execute("""INSERT INTO einkaufslisten (uuid, name, archiviert, laden_id)
                    VALUES (%s, 'Export Liste', %s, %s)""", (list_id, archived, store_id))
            for i, amount, deleted in [(1, 1.125, None), (2, None, None), (3, 2, '2026-01-01')]:
                cur.execute("""INSERT INTO einkaufsliste_eintraege (uuid, liste_uuid, name,
                    menge, einheit, menge_text, notiz, kategorie_id, rang, erledigt,
                    manuell, herkunft, geloescht_am) VALUES (%s, %s, 'Mehl', %s, 'kg',
                    'nach Bedarf', 'Bio', %s, 'abc', 1, 1, %s, %s)""",
                            (f"10000000-0000-0000-0000-{i:012d}", lists[i % 2], amount,
                             category_id, json.dumps([{"rezept_id": ids[0], "menge": 125.5}]), deleted))
    return {"ids": ids, "ingredients": ingredients, "image_id": image_id,
            "history_id": history_id, "category_id": category_id, "store_id": store_id,
            "lists": lists}


def test_recipe_export(client, export_data):
    from db import get_db

    response = client.get('/api/export/v1?teil=rezepte')
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["format"] == "rezeptify-export/v1"
    assert data["version"] == (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip()
    assert (data["total"], data["limit"], data["offset"]) == (2, 50, 0)
    recipe, unsplit = data["rezepte"]
    assert [r["id"] for r in data["rezepte"]] == export_data["ids"]
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM rezepte WHERE id=%s", (recipe["id"],))
            raw = cur.fetchone()
            assert set(raw) <= recipe.keys()
            for key, value in raw.items():
                if key not in {"zutaten", "tags", "erstellt_am", "geaendert_am"}:
                    assert recipe[key] == value
            cur.execute("SELECT COUNT(*) AS n FROM rezept_schritte WHERE rezept_id=%s", (unsplit["id"],))
            assert cur.fetchone()["n"] == 0
            cur.execute("SELECT schritte_quelle FROM rezepte WHERE id=%s", (unsplit["id"],))
            assert cur.fetchone()["schritte_quelle"] == "keine"
    assert recipe["zutaten"] == export_data["ingredients"]
    assert recipe["tags"] == ["süß", "Ofen"]
    assert recipe["erstellt_am"] == "2026-01-02T03:04:05+00:00"
    assert recipe["geaendert_am"] == "2026-02-03T04:05:06+00:00"
    assert recipe["quelldatei_url"] == "/static/uploads/quelle.pdf"
    image, = recipe["bilder"]
    assert image["id"] == export_data["image_id"]
    assert image["dateiname"] == "kuchen.jpg"
    assert image["url"] == "/static/uploads/kuchen.jpg"
    assert image["ist_haupt"] == 1
    assert image["erstellt_am"].endswith("+00:00")
    assert recipe["schritte"] == [
        {"position": 1, "text": "Schritt 1", "zutaten_indices": [1], "timer_sekunden": 120},
        {"position": 2, "text": "Schritt 2", "zutaten_indices": None, "timer_sekunden": None},
    ]
    history, = recipe["kochhistorie"]
    assert history == {"id": export_data["history_id"], "gekocht_am": "2026-03-04T05:06:07+00:00",
                       "portionen_verwendet": 2, "notiz": "Gut!", "nachtraegliche_bewertung": 5,
                       "erstellt_am": history["erstellt_am"]}
    assert history["erstellt_am"].endswith("+00:00")
    assert unsplit["schritte"] == []
    assert unsplit["bilder"] == unsplit["kochhistorie"] == []
    for offset, expected in [(0, [recipe]), (1, [unsplit]), (2, [])]:
        page = client.get(f'/api/export/v1?teil=rezepte&limit=1&offset={offset}').json()
        assert page == {**data, "limit": 1, "offset": offset, "rezepte": expected}


def test_meta_export(client, export_data):
    response = client.get('/api/export/v1?teil=meta')
    assert response.status_code == 200, response.text
    data = response.json()
    assert set(data) == {"format", "version", "kategorien", "wochenplan", "einkauf"}
    assert data["format"] == "rezeptify-export/v1"
    assert "Backen" in data["kategorien"]
    plan, = data["wochenplan"]
    assert plan == {"id": plan["id"], "rezept_id": export_data["ids"][0], "datum": "2026-04-05",
                    "mahlzeit": "abend", "portionen": 2, "notiz": "Plan", "erstellt_am": plan["erstellt_am"]}
    assert plan["erstellt_am"].endswith("+00:00")
    shopping = data["einkauf"]
    assert set(shopping) == {"kategorien", "artikel", "laeden", "laden_kategorie_rang", "listen", "eintraege"}
    assert export_data["category_id"] in [r["id"] for r in shopping["kategorien"]]
    article = next(r for r in shopping["artikel"] if r["name_norm"] == "export mehl")
    assert article["letzte_menge"] == 1.125
    assert article["intervall_tage"] == 2.5
    assert article["zuletzt_gekauft"] == "2026-01-02T03:04:05+00:00"
    assert shopping["laeden"][0]["id"] == export_data["store_id"]
    assert shopping["laden_kategorie_rang"] == [{"laden_id": export_data["store_id"],
                                               "kategorie_id": export_data["category_id"], "rang": "abc"}]
    assert [r["uuid"] for r in shopping["listen"]] == export_data["lists"]
    assert [r["archiviert"] for r in shopping["listen"]] == [0, 1]
    assert len(shopping["eintraege"]) == 2
    assert [r["menge"] for r in shopping["eintraege"]] == [1.125, None]
    for entry in shopping["eintraege"]:
        assert set(entry) == {"uuid", "liste_uuid", "name", "menge", "einheit", "menge_text",
                              "notiz", "kategorie_id", "rang", "erledigt", "manuell", "herkunft", "erstellt_am"}
        assert entry["herkunft"] == [{"rezept_id": export_data["ids"][0], "menge": 125.5}]
        assert entry["name"] == "Mehl"
        assert entry["notiz"] == "Bio"
        assert entry["erledigt"] == entry["manuell"] == 1
        assert entry["erstellt_am"].endswith("+00:00")


@pytest.mark.parametrize("query", ["", "teil=invalid", "teil=rezepte&limit=0",
                                   "teil=rezepte&limit=101", "teil=rezepte&offset=-1"])
def test_export_query_validation(client, query):
    assert client.get(f"/api/export/v1?{query}").status_code == 422


@pytest.mark.parametrize("teil", ["rezepte", "meta"])
def test_export_requires_auth(client, monkeypatch, teil):
    import auth

    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "test-secret")
    monkeypatch.setattr(auth, "MCP_API_TOKEN", "test-mcp-token")
    url = f"/api/export/v1?teil={teil}"
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get(url, headers={"Authorization": "Bearer test-mcp-token"}).status_code == 200


def test_export_cursor_rejects_writes(client):
    from db import get_db
    from routes.export import _ReadOnlyCursor

    with get_db() as conn:
        with conn.cursor(_ReadOnlyCursor) as cur:
            for query in ["INSERT INTO kategorien (name) VALUES ('Forbidden')",
                          "UPDATE rezepte SET titel='Forbidden'", "DELETE FROM rezepte"]:
                with pytest.raises(ValueError, match="SELECT"):
                    cur.execute(query)
