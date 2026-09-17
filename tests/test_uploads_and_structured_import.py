import io
import json

from PIL import Image


def _recipe(client, title="Upload-Rezept"):
    response = client.post("/api/rezepte", json={
        "titel": title, "zutaten": [], "zubereitung": "Mischen.",
        "portionen": 2, "tags": [],
    })
    assert response.status_code == 201
    return response.json()


def _jpeg_bytes(orientation=None):
    image = Image.new("RGB", (40, 20), "red")
    data = io.BytesIO()
    if orientation:
        exif = Image.Exif()
        exif[274] = orientation
        image.save(data, format="JPEG", exif=exif)
    else:
        image.save(data, format="JPEG")
    return data.getvalue()


def test_recipe_image_upload_orients_and_saves_a_real_image(client):
    recipe = _recipe(client)
    response = client.post(
        f"/api/rezepte/{recipe['id']}/bilder",
        files={"file": ("rotated.jpg", _jpeg_bytes(6), "image/jpeg")},
        data={"ist_haupt": "true"},
    )
    assert response.status_code == 200
    filename = response.json()["dateiname"]
    assert filename.endswith(".jpg")

    from config import UPLOAD_DIR
    with Image.open(UPLOAD_DIR / filename) as saved:
        assert saved.size == (20, 40)


def test_recipe_image_upload_rejects_a_renamed_non_image(client):
    recipe = _recipe(client)
    response = client.post(
        f"/api/rezepte/{recipe['id']}/bilder",
        files={"file": ("not-an-image.jpg", b"this is not an image", "image/jpeg")},
    )
    assert response.status_code == 400
    assert "lesbares Bild" in response.json()["detail"]


def test_json_recipe_import_parses_without_claude_and_creates_recipe(client, monkeypatch):
    # The JSON branch must never ask Claude for a key or a completion.
    monkeypatch.setattr("routes.ai.check_api_key", lambda: (_ for _ in ()).throw(AssertionError("Claude used")))
    payload = {
        "format": "rezeptify-recipe/v1",
        "title": "Deterministische Suppe",
        "ingredients": [{"amount": 800, "unit": "g", "name": "Tomaten"}],
        "steps": ["Tomaten kochen.", "Pürieren."],
        "servings": 3,
        "prep_minutes": 5,
        "cook_minutes": 20,
        "difficulty": "leicht",
        "tags": ["vegetarisch"],
    }
    imported = client.post(
        "/api/analysiere-bild",
        files={"file": ("suppe.json", json.dumps(payload).encode(), "application/json")},
    )
    assert imported.status_code == 200
    data = imported.json()
    assert data["structured_import"] is True
    assert data["zutaten"] == [{"menge": "800", "einheit": "g", "name": "Tomaten", "gruppe": None}]
    assert data["zubereitung"] == "Tomaten kochen.\n\nPürieren."

    created = client.post("/api/rezepte", json=data)
    assert created.status_code == 201
    assert created.json()["titel"] == "Deterministische Suppe"
    assert created.json()["quelle_typ"] == "datei-import"


def test_json_recipe_import_returns_actionable_validation_error(client):
    response = client.post(
        "/api/analysiere-bild",
        files={"file": ("broken.json", b'{"format":"rezeptify-recipe/v1"', "application/json")},
    )
    assert response.status_code == 400
    assert "Zeile" in response.json()["detail"]

    schema_error = client.post(
        "/api/analysiere-bild",
        files={"file": ("missing-title.json", b'{"format":"rezeptify-recipe/v1","steps":["x"]}', "application/json")},
    )
    assert schema_error.status_code == 422
    assert "title" in schema_error.json()["detail"]


def test_pdf_import_still_uses_ai_branch(client, monkeypatch):
    class Message:
        content = [type("Content", (), {"text": "ignored"})()]

    class Claude:
        class messages:
            @staticmethod
            def create(**kwargs):
                assert kwargs["messages"][0]["content"][0]["type"] == "document"
                return Message()

    monkeypatch.setattr("routes.ai.check_api_key", lambda: None)
    monkeypatch.setattr("routes.ai.get_claude", lambda: Claude())
    monkeypatch.setattr("routes.ai.parse_claude", lambda _: {
        "titel": "PDF-Rezept", "zutaten": [], "zubereitung": "Backen.", "tags": []
    })
    response = client.post(
        "/api/analysiere-bild",
        files={"file": ("rezept.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert response.status_code == 200
    assert response.json()["quelle_typ"] == "pdf-import"
    assert response.json()["quelldatei"].endswith(".pdf")
