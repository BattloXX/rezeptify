import pytest


@pytest.mark.parametrize("source_url, expected", [
    ("javascript:alert(1)", ""),
    ("JaVaScRiPt:alert(1)", ""),
    ("https://example.com/x", "https://example.com/x"),
    ("HTTP://EXAMPLE.COM", "HTTP://EXAMPLE.COM"),
    ("https://example.com/" + "x" * 580, ""),
    ("x" * 600, ""),
    ("data:text/html,<script>alert(1)</script>", ""),
    ("//evil.com", ""),
    ("/relativ", ""),
    ("  https://example.com/x  ", "https://example.com/x"),
    ("  javascript:alert(1)  ", ""),
    ("https://example.com/" + "x" * 480, "https://example.com/" + "x" * 480),
    ("https://example.com/" + "x" * 481, ""),
    ("", ""),
    (None, ""),
])
@pytest.mark.parametrize("method", ["POST", "PUT"])
def test_source_url_is_sanitized_on_save(client, source_url, expected, method):
    payload = {"titel": "URL-Test", "quelle_url": source_url}
    if method == "POST":
        response = client.post("/api/rezepte", json=payload)
        assert response.status_code == 201
        rid = response.json()["id"]
    else:
        created = client.post("/api/rezepte", json={
            "titel": "URL-Test", "quelle_url": "https://old.example.com",
        })
        assert created.status_code == 201
        rid = created.json()["id"]
        response = client.put(f"/api/rezepte/{rid}", json=payload)
        assert response.status_code == 200
    saved = client.get(f"/api/rezepte/{rid}")
    assert saved.status_code == 200
    assert saved.json()["quelle_url"] == expected
