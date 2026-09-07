from types import SimpleNamespace


def _claude_response():
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text='[{"titel":"Test-Pasta","suchinfo":"4,8 Sterne"}]')],
        stop_reason="end_turn",
    )


def test_search_accepts_query_and_returns_recipe_wrapper(client, monkeypatch):
    import routes.ai as ai

    monkeypatch.setattr(ai, "check_api_key", lambda: None)
    monkeypatch.setattr(ai, "get_claude", lambda: SimpleNamespace(
        messages=SimpleNamespace(create=lambda **kwargs: _claude_response())
    ))

    response = client.post("/api/rezept-suche", json={"query": "Pasta"})

    assert response.status_code == 200
    assert response.json() == {"rezepte": [{"titel": "Test-Pasta", "suchinfo": "4,8 Sterne"}]}


def test_search_still_accepts_anfrage(client, monkeypatch):
    import routes.ai as ai

    monkeypatch.setattr(ai, "check_api_key", lambda: None)
    monkeypatch.setattr(ai, "get_claude", lambda: SimpleNamespace(
        messages=SimpleNamespace(create=lambda **kwargs: _claude_response())
    ))

    assert client.post("/api/rezept-suche", json={"anfrage": "Pasta"}).status_code == 200
