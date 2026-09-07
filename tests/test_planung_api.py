from datetime import date, timedelta


def recipe(client, title, ingredients, portions=4):
    response = client.post("/api/rezepte", json={"titel": title, "portionen": portions, "zutaten": ingredients})
    assert response.status_code == 201
    return response.json()["id"]


def test_create_move_and_delete_plan_entry(client):
    rid = recipe(client, "Plan-Rezept", [{"menge": "100", "einheit": "g", "name": "Mehl"}])
    created = client.post("/api/wochenplan", json={"rezept_id": rid, "datum": "2026-09-07", "mahlzeit": "abend", "portionen": 2})
    assert created.status_code == 201
    eid = created.json()["id"]
    listed = client.get("/api/wochenplan?von=2026-09-07&bis=2026-09-13").json()["eintraege"]
    assert listed[0]["titel"] == "Plan-Rezept"
    assert listed[0]["portionen"] == 2
    moved = client.patch(f"/api/wochenplan/{eid}", json={"datum": "2026-09-08", "mahlzeit": "mittag", "portionen": 3})
    assert moved.status_code == 200
    assert moved.json()["datum"] == "2026-09-08"
    assert moved.json()["mahlzeit"] == "mittag"
    assert client.delete(f"/api/wochenplan/{eid}").status_code == 200
    assert client.get("/api/wochenplan?von=2026-09-07&bis=2026-09-13").json()["eintraege"] == []


def test_week_plan_aggregates_scaled_ingredients(client):
    first = recipe(client, "Erstes", [{"menge": "100", "einheit": "g", "name": "Mehl"}], 4)
    second = recipe(client, "Zweites", [{"menge": "200", "einheit": "g", "name": "Mehl"}, {"menge": "1", "einheit": "Stk", "name": "Ei"}], 2)
    assert client.post("/api/wochenplan", json={"rezept_id": first, "datum": "2026-09-07", "mahlzeit": "abend", "portionen": 8}).status_code == 201
    assert client.post("/api/wochenplan", json={"rezept_id": second, "datum": "2026-09-08", "mahlzeit": "mittag"}).status_code == 201
    result = client.post("/api/wochenplan/einkaufsliste", json={"von": "2026-09-07", "bis": "2026-09-13"})
    assert result.status_code == 200
    assert result.json()["anzahl"] == 3
    entries = client.get("/api/einkaufsliste").json()["eintraege"]
    flour = next(entry for entry in entries if entry["name"] == "Mehl")
    assert flour["menge"] == 400
    assert flour["einheit"] == "g"
    assert len(flour["herkunft"]) == 2


def test_week_plan_rejects_invalid_ranges(client):
    assert client.post("/api/wochenplan/einkaufsliste", json={"von": "2026-09-08", "bis": "2026-09-07"}).status_code == 400
    assert client.post("/api/wochenplan/einkaufsliste", json={"von": "2026-09-01", "bis": "2026-10-02"}).status_code == 400
