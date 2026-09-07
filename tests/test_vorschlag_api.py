def recipe(client, title, **overrides):
    payload = {
        "titel": title,
        "beschreibung": "",
        "zutaten": [{"menge": "1", "einheit": "Stk", "name": "Tomate"}],
        "zeit_vorb": 10,
        "zeit_koch": 20,
        "kategorie": "Hauptgericht",
        "schwierigkeit": "leicht",
        "tags": [],
    }
    payload.update(overrides)
    response = client.post("/api/rezepte", json=payload)
    assert response.status_code == 201
    return response.json()


def test_vorschlag_combines_time_category_tag_rating_and_text_filters(client):
    matching = recipe(
        client, "Vegetarische Pasta",
        beschreibung="Schnelles Nudelgericht mit Tomaten",
        zeit_vorb=10, zeit_koch=20, kategorie="Hauptgericht",
        schwierigkeit="leicht", tags=["vegetarisch", "pasta"],
    )
    assert client.patch(f"/api/rezepte/{matching['id']}/bewertung", json={"sterne": 4}).status_code == 200
    recipe(client, "Langsame Pasta", zeit_vorb=15, zeit_koch=20, tags=["vegetarisch", "pasta"])
    recipe(client, "Fleisch Pasta", tags=["pasta"])

    response = client.get("/api/rezepte/vorschlag", params={
        "max_zeit": 30,
        "kategorie": "Hauptgericht",
        "vegetarisch": True,
        "bewertung_min": 4,
        "schwierigkeit": "leicht",
        "text": "Pasta",
    })

    assert response.status_code == 200
    recipes = response.json()["rezepte"]
    assert [recipe["id"] for recipe in recipes] == [matching["id"]]
    assert recipes[0]["zutaten"][0]["name"] == "Tomate"
    assert recipes[0]["bilder"] == []


def test_vorschlag_filters_ingredients_and_accepts_ignored_favorit(client):
    recipe(client, "Tomaten Suppe", zutaten=[{"menge": "2", "einheit": "Stk", "name": "Tomaten"}])
    recipe(client, "Kartoffel Suppe", zutaten=[{"menge": "2", "einheit": "Stk", "name": "Kartoffeln"}])

    response = client.get("/api/rezepte/vorschlag", params={"zutaten": "tomat", "favorit": True})

    assert response.status_code == 200
    assert [recipe["titel"] for recipe in response.json()["rezepte"]] == ["Tomaten Suppe"]


def test_vorschlag_returns_empty_envelope_for_no_local_match(client):
    recipe(client, "Nudeln")

    response = client.get("/api/rezepte/vorschlag", params={"text": "Auberginenauflauf"})

    assert response.status_code == 200
    assert response.json() == {"rezepte": []}
