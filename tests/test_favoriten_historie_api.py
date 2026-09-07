def recipe(client, title):
    response = client.post("/api/rezepte", json={
        "titel": title,
        "beschreibung": "",
        "zutaten": [{"menge": "1", "einheit": "Stk", "name": "Tomate"}],
        "zeit_vorb": 5,
        "zeit_koch": 10,
        "kategorie": "Hauptgericht",
        "schwierigkeit": "leicht",
        "tags": [],
    })
    assert response.status_code == 201
    return response.json()


def test_favorit_toggle_is_idempotent(client):
    created = recipe(client, "Favorit")
    rid = created["id"]

    assert client.patch(f"/api/rezepte/{rid}/favorit", json={"favorit": True}).json()["favorit"] is True
    assert client.patch(f"/api/rezepte/{rid}/favorit", json={"favorit": False}).json()["favorit"] is False
    assert client.get(f"/api/rezepte/{rid}").json()["favorit"] == 0


def test_cooking_history_is_append_only_and_aggregated(client):
    created = recipe(client, "Oft gekocht")
    rid = created["id"]

    first = client.post(f"/api/rezepte/{rid}/kochen", json={"portionen": 2, "notiz": "Lecker"})
    second = client.post(f"/api/rezepte/{rid}/kochen", json={})
    assert first.status_code == second.status_code == 201
    assert second.json()["anzahl_gekocht"] == 2
    assert second.json()["zuletzt_gekocht"] is not None

    recipe_data = client.get(f"/api/rezepte/{rid}").json()
    assert recipe_data["anzahl_gekocht"] == 2
    assert recipe_data["zuletzt_gekocht"] is not None


def test_vorschlag_favorit_only_returns_favorites(client):
    favorite = recipe(client, "Mein Favorit")
    recipe(client, "Kein Favorit")
    client.patch(f"/api/rezepte/{favorite['id']}/favorit", json={"favorit": True})

    response = client.get("/api/rezepte/vorschlag", params={"favorit": True})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["rezepte"]] == [favorite["id"]]


def test_lange_nicht_gekocht_puts_never_cooked_before_recent(client):
    recent = recipe(client, "Kuerzlich gekocht")
    never = recipe(client, "Noch nie gekocht")
    assert client.post(f"/api/rezepte/{recent['id']}/kochen", json={}).status_code == 201

    response = client.get("/api/rezepte/vorschlag", params={"lange_nicht_gekocht": True})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["rezepte"]][:2] == [never["id"], recent["id"]]
