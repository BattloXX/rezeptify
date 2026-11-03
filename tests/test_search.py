import json

import pytest

from db import build_suchtext, get_db, init_db


def recipe(client, titel, **fields):
    response = client.post("/api/rezepte", json={"titel": titel, **fields})
    assert response.status_code == 201, response.text
    return response.json()


def search(client, suche, **params):
    response = client.get("/api/rezepte", params={"suche": suche, **params})
    assert response.status_code == 200, response.text
    return response.json()


def ids(result):
    return [item["id"] for item in result["items"]]


@pytest.mark.parametrize("query,expected", [
    ("Duplikat**", [0]), ("a+", [0, 1]), ('"', [0, 1]),
    ("(", [0, 1]), ("-x", []), ("*", [0, 1]), ("~~", [0, 1]),
    ("%", [0, 1]), ("_", []), ("+~<>@()", [0, 1]),
])
def test_operator_characters_are_safe(client, query, expected):
    recipes = [recipe(client, "Duplikat"), recipe(client, "Salat")]
    result = search(client, query)
    assert set(ids(result)) == {recipes[index]["id"] for index in expected}
    assert result["total"] == len(expected)


def test_underscore_is_literal_in_filter_and_title_ranking(client):
    literal = recipe(client, "Salat_Mix")
    recipe(client, "Salat Mix")
    assert ids(search(client, "_")) == [literal["id"]]
    assert ids(search(client, "Salat_Mix")) == [literal["id"]]


def test_search_requires_all_words_and_matches_substrings(client):
    match = recipe(client, "Testrezept 050")
    recipe(client, "Testrezept 100")
    recipe(client, "Gericht 050")
    assert ids(search(client, "Testrezept 05")) == [match["id"]]


def test_search_includes_tags_ingredients_category_description_and_groups(client):
    paella = recipe(client, "Paella", tags=["spanisch"],
                    beschreibung="Traditionelles Familienessen",
                    zutaten=[{"name": "Reis", "gruppe": "Grundlage",
                              "menge": "987654", "einheit": "Spezialeinheit"}])
    salad = recipe(client, "Gurkengericht", kategorie="Salat")
    for query in ("Reis", "spanisch", "Familienessen", "Grundlage", "Reis spanisch"):
        assert ids(search(client, query)) == [paella["id"]]
    assert ids(search(client, "Salat")) == [salad["id"]]
    for query in ("987654", "Spezialeinheit"):
        assert search(client, query)["total"] == 0


@pytest.mark.parametrize("query", ["hähnchen", "HAHNCHEN", "HÄHNCHEN"])
def test_search_is_case_and_accent_insensitive(client, query):
    created = recipe(client, "Hähnchen-Curry")
    assert ids(search(client, query)) == [created["id"]]


def test_short_tokens_and_stopwords_are_searchable(client):
    created = recipe(client, "Frühstück", zutaten=[{"name": "Ei"}], tags=["und"])
    recipe(client, "Pasta")
    for query in ("ei", "und", "ei und"):
        assert ids(search(client, query)) == [created["id"]]


def test_title_relevance_and_explicit_sort_orders(client):
    ingredient = recipe(client, "A Pfanne", zutaten=[{"name": "Reis"}])
    title = recipe(client, "Reisgericht")
    two_titles = recipe(client, "Reis Pfanne")
    with get_db() as conn:
        with conn.cursor() as cur:
            for created, date in ((ingredient, "2020-01-01"), (title, "2021-01-01"),
                                  (two_titles, "2019-01-01")):
                cur.execute("UPDATE rezepte SET erstellt_am=%s WHERE id=%s", (date, created["id"]))
    assert ids(search(client, "Reis")) == [title["id"], two_titles["id"], ingredient["id"]]
    assert ids(search(client, "Reis Pfanne")) == [two_titles["id"], ingredient["id"]]
    assert ids(search(client, "Reis", sort="name")) == [ingredient["id"], two_titles["id"], title["id"]]
    assert client.patch(f"/api/rezepte/{ingredient['id']}/bewertung", json={"sterne": 5}).status_code == 200
    assert ids(search(client, "Reis", sort="sterne"))[0] == ingredient["id"]


def test_put_rebuilds_search_text(client):
    created = recipe(client, "Gericht", tags=["Altmarkierung"])
    response = client.put(f"/api/rezepte/{created['id']}", json={
        "titel": "Neue Speise", "tags": ["Neumarkierung"],
        "beschreibung": "Aktualisiert", "kategorie": "Dessert",
        "zutaten": [{"name": "Kakao", "gruppe": "Glasur"}],
    })
    assert response.status_code == 200, response.text
    assert search(client, "Altmarkierung")["total"] == 0
    assert search(client, "Gericht")["total"] == 0
    for query in ("Neumarkierung", "Neue", "Aktualisiert", "Dessert", "Kakao", "Glasur"):
        assert ids(search(client, query)) == [created["id"]]


def test_init_db_backfills_null_search_text_idempotently(client):
    created = recipe(client, "Altbestand", tags=["Backfilltag"],
                     zutaten=[{"name": "Backfillzutat", "gruppe": "Backfillgruppe"}])
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE rezepte SET suchtext=NULL WHERE id=%s", (created["id"],))
    init_db()
    init_db()
    for query in ("Altbestand", "Backfilltag", "Backfillzutat", "Backfillgruppe"):
        assert ids(search(client, query)) == [created["id"]]


def test_init_db_migrates_existing_table(client):
    created = recipe(client, "Bestandsrezept", tags=["Migrationstag"])
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE rezepte DROP COLUMN suchtext")
    init_db()
    init_db()
    assert ids(search(client, "Migrationstag")) == [created["id"]]
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT DATA_TYPE, IS_NULLABLE, COLLATION_NAME
                FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()
                AND TABLE_NAME='rezepte' AND COLUMN_NAME='suchtext'""")
            assert cur.fetchone() == {"DATA_TYPE": "longtext", "IS_NULLABLE": "YES",
                                      "COLLATION_NAME": "utf8mb4_unicode_ci"}


def test_search_pagination_and_combined_filters(client):
    recipes = [recipe(client, f"Reisgericht {index}", kategorie="Hauptgericht", tags=["warm"])
               for index in range(5)]
    recipe(client, "Reis Salat", kategorie="Salat", tags=["kalt"])
    recipe(client, "Pasta", kategorie="Hauptgericht", tags=["warm"])
    result = search(client, "Reis", sort="name", kategorie="Hauptgericht", tag="warm", limit=2, offset=2)
    assert set(result) == {"total", "items", "limit", "offset"}
    assert (result["total"], result["limit"], result["offset"]) == (5, 2, 2)
    assert ids(result) == [recipes[2]["id"], recipes[3]["id"]]
    assert search(client, "Reis", limit=2, offset=20)["items"] == []
    assert search(client, "Reis", limit=2, offset=20)["total"] == 6


def test_search_limits_token_count_and_length(client):
    created = recipe(client, "eins zwei drei vier fünf sechs sieben acht " + "z" * 50)
    assert ids(search(client, "eins zwei drei vier fünf sechs sieben acht fehlend")) == [created["id"]]
    assert ids(search(client, "z" * 51)) == [created["id"]]


@pytest.mark.parametrize("as_json", [False, True])
def test_build_suchtext_accepts_lists_and_json(as_json):
    tags = ["spanisch", "warm"]
    zutaten = [{"name": "Reis", "menge": "100", "einheit": "g"}, {"gruppe": "Sauce"}]
    if as_json:
        tags, zutaten = json.dumps(tags), json.dumps(zutaten)
    assert build_suchtext("Paella", "Lecker", "Hauptgericht", tags, zutaten) == (
        "Paella Lecker Hauptgericht spanisch warm Reis Sauce")
    assert build_suchtext(None, None, None, None, None) == ""
