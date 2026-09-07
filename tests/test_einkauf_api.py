def _recipe(client):
    response = client.post("/api/rezepte", json={
        "titel": "Einkaufs-Test", "portionen": 4,
        "zutaten": [
            {"menge": "200", "einheit": "g", "name": "Mehl"},
            {"menge": "nach Geschmack", "einheit": "", "name": "Salz"},
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
    mehl = next(e for e in entries if e["name"] == "Mehl")
    salz = next(e for e in entries if e["name"] == "Salz")
    assert mehl["menge"] == 300
    assert mehl["herkunft"] == [{"rezept_id": rid, "rezept_titel": "Einkaufs-Test", "menge": "300", "einheit": "g"}]
    assert salz["menge_text"] == "nach Geschmack"

    assert client.patch(f"/api/einkaufsliste/{mehl['id']}", json={"erledigt": True}).json()["erledigt"] is True
    assert client.delete(f"/api/einkaufsliste/{salz['id']}").status_code == 200
    assert client.post("/api/einkaufsliste/aufraeumen", json={}).json()["geloescht"] == 1
    assert client.get("/api/einkaufsliste").json()["eintraege"] == []
