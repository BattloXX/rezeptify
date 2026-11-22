def _recipe(client):
    response = client.post("/api/rezepte", json={
        "titel": "Einkaufs-Test", "portionen": 4,
        "zutaten": [
            {"menge": "200", "einheit": "g", "name": "Reis"},
            {"menge": "nach Geschmack", "einheit": "", "name": "Basilikum"},
        ],
    })
    assert response.status_code == 201
    return response.json()["id"]


def test_add_scaled_recipe_toggle_delete_and_cleanup(client):
    rid = _recipe(client)
    added = client.post(f"/api/rezepte/{rid}/zu-einkaufsliste", json={"portionen": 6})
    assert added.status_code == 200

    listed = client.get("/api/einkaufsliste")
    assert listed.status_code == 200
    entries = listed.json()["eintraege"]
    mehl = next(e for e in entries if e["name"] == "Reis")
    salz = next(e for e in entries if e["name"] == "Basilikum")
    assert mehl["menge"] == 300
    assert mehl["herkunft"] == [{"rezept_id": rid, "rezept_titel": "Einkaufs-Test", "menge": "300", "einheit": "g"}]
    assert salz["menge_text"] == "nach Geschmack"

    assert client.patch(f"/api/einkaufsliste/{mehl['id']}", json={"erledigt": True}).json()["erledigt"] is True
    assert client.delete(f"/api/einkaufsliste/{salz['id']}").status_code == 200
    assert client.post("/api/einkaufsliste/aufraeumen", json={}).json()["geloescht"] == 1
    assert client.get("/api/einkaufsliste").json()["eintraege"] == []


def test_vorrat_zutaten_werden_uebersprungen_und_gemeldet(client):
    response = client.post("/api/rezepte", json={
        "titel": "Vorrat-Test", "portionen": 2,
        "zutaten": [{"menge": "200", "einheit": "g", "name": "Mehl"}, {"menge": "1", "einheit": "", "name": "Zucchini"}],
    })
    rid = response.json()["id"]
    result = client.post(f"/api/rezepte/{rid}/zu-einkaufsliste", json={"portionen": 2}).json()
    assert [e["name"] for e in result["eintraege"]] == ["Zucchini"]
    assert result["vorrat"] == [{"name": "Mehl", "menge_text": "200 g"}]
