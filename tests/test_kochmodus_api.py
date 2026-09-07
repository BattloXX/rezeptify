def _recipe(client, preparation="1. Schneiden.\n2. 5 Minuten braten."):
    response = client.post("/api/rezepte", json={
        "titel": "Kochmodus-Test", "zubereitung": preparation,
        "zutaten": [{"menge": "1", "einheit": "Stk", "name": "Zwiebel"}],
    })
    assert response.status_code == 201
    return response.json()["id"]


def test_lazy_split_persists_and_does_not_overwrite_manual_steps(client):
    rid = _recipe(client)

    lazy = client.get(f"/api/rezepte/{rid}/schritte")
    assert lazy.status_code == 200
    assert lazy.json()["quelle"] == "auto"
    assert [step["text"] for step in lazy.json()["schritte"]] == ["Schneiden.", "5 Minuten braten."]
    assert lazy.json()["schritte"][1]["timer_sekunden"] == 300

    manual = client.put(f"/api/rezepte/{rid}/schritte", json={"schritte": ["Manueller erster Schritt"]})
    assert manual.status_code == 200
    assert manual.json()["quelle"] == "manuell"

    protected = client.post(f"/api/rezepte/{rid}/schritte/auto")
    assert protected.status_code == 409
    assert client.get(f"/api/rezepte/{rid}/schritte").json()["schritte"][0]["text"] == "Manueller erster Schritt"

    forced = client.post(f"/api/rezepte/{rid}/schritte/auto?force=true")
    assert forced.status_code == 200
    assert forced.json()["quelle"] == "auto"
