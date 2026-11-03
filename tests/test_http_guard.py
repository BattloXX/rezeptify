from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from services import http_guard
from services.http_guard import check_url, safe_get, UnsafeUrlError, TooLargeError


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://localhost/", "http://10.0.0.5/",
    "http://169.254.169.254/latest/meta-data", "http://[::1]/",
    "http://[::ffff:127.0.0.1]/", "http://[fc00::1]/",
    "http://224.0.0.1/", "http://[ff0e::1]/",
    "ftp://example.com/", "http://example.com:8080/", "http:///",
])
def test_check_url_rejects_unsafe_urls(url, monkeypatch):
    monkeypatch.setattr(http_guard, "_resolve", lambda host: ["127.0.0.1"])
    with pytest.raises(UnsafeUrlError, match="Adresse nicht erlaubt"):
        check_url(url)


def test_check_url_rejects_mixed_dns_answers(monkeypatch):
    monkeypatch.setattr(http_guard, "_resolve", lambda host: ["93.184.216.34", "10.0.0.5"])
    with pytest.raises(UnsafeUrlError):
        check_url("https://example.com/")


@pytest.mark.parametrize("addresses", [[], ["not-an-ip"]])
def test_check_url_rejects_invalid_dns_answers(addresses, monkeypatch):
    monkeypatch.setattr(http_guard, "_resolve", lambda host: addresses)
    with pytest.raises(UnsafeUrlError):
        check_url("https://example.com/")


def test_check_url_accepts_public_destination(monkeypatch):
    monkeypatch.setattr(http_guard, "_resolve", lambda host: ["93.184.216.34"])
    check_url("https://example.com/")
    check_url("http://93.184.216.34/")
    check_url("https://[::ffff:93.184.216.34]/")


def test_resolve_uses_all_getaddrinfo_answers(monkeypatch):
    monkeypatch.setattr(http_guard.socket, "getaddrinfo", lambda host, port: [
        (2, 1, 6, "", ("93.184.216.34", 0)),
        (10, 1, 6, "", ("::1", 0, 0, 0)),
    ])
    with pytest.raises(UnsafeUrlError):
        check_url("https://example.com/")


def test_safe_get_rejects_internal_redirect_before_request(monkeypatch):
    monkeypatch.setattr(http_guard, "_resolve", lambda host: ["93.184.216.34"])
    requests = []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/"})

    with pytest.raises(UnsafeUrlError):
        safe_get("https://example.com/", max_bytes=100, transport=httpx.MockTransport(handler))
    assert requests == ["https://example.com/"]


def test_safe_get_stops_reading_and_closes_oversized_stream(monkeypatch):
    monkeypatch.setattr(http_guard, "_resolve", lambda host: ["93.184.216.34"])
    read_chunks = []
    closed = []

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for chunk in [b"123", b"456", b"never read"]:
                read_chunks.append(chunk)
                yield chunk

        def close(self):
            closed.append(True)

    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=Stream()))
    with pytest.raises(TooLargeError):
        safe_get("https://example.com/", max_bytes=5, transport=transport)
    assert read_chunks == [b"123", b"456"]
    assert closed == [True]


def test_safe_get_relative_redirect_final_url_and_encoding(monkeypatch):
    resolved = []
    monkeypatch.setattr(http_guard, "_resolve", lambda host: resolved.append(host) or ["93.184.216.34"])
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(200, headers={"content-type": "text/html; charset=iso-8859-1"},
                              content=b"Gr\xfc\xdfe")

    response = safe_get("https://example.com/start", max_bytes=5, params={"q": "test"},
                        headers={"User-Agent": "test-agent"}, transport=httpx.MockTransport(handler))
    assert response.status_code == 200
    assert response.content == b"Gr\xfc\xdfe"
    assert response.text == "Grüße"
    assert response.url == "https://example.com/final"
    assert str(requests[0].url) == "https://example.com/start?q=test"
    assert requests[1].headers["user-agent"] == "test-agent"
    assert resolved == ["example.com", "example.com"]


def test_safe_get_limits_redirects(monkeypatch):
    monkeypatch.setattr(http_guard, "_resolve", lambda host: ["93.184.216.34"])
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "/again"})

    with pytest.raises(UnsafeUrlError, match="Weiterleitungen"):
        safe_get("https://example.com/", max_bytes=10, transport=httpx.MockTransport(handler))
    assert len(requests) == 6


def test_image_api_rejects_internal_url_before_download(client, monkeypatch):
    download = Mock()
    monkeypatch.setattr("routes.bilder.download_image", download)
    response = client.post("/api/bilder/from-url", json={"url": "http://127.0.0.1/x.jpg"})
    assert response.status_code == 400
    assert response.json() == {"detail": "Bild-URL nicht erlaubt"}
    download.assert_not_called()


def test_analysis_api_rejects_metadata_url_without_claude(client, monkeypatch):
    claude = Mock()
    monkeypatch.setattr("routes.ai.check_api_key", lambda: None)
    monkeypatch.setattr("routes.ai.get_claude", claude)
    response = client.post("/api/analysiere-url", json={"url": "http://169.254.169.254/"})
    assert response.status_code == 400
    assert response.json() == {"detail": "URL nicht erlaubt"}
    claude.assert_not_called()


def test_analysis_uses_final_url_as_image_base(client, monkeypatch):
    download = Mock(return_value="recipe.jpg")
    monkeypatch.setattr("routes.ai.check_api_key", lambda: None)
    monkeypatch.setattr("routes.ai.safe_get", lambda *args, **kwargs: SimpleNamespace(
        text='<meta property="og:image" content="photo.jpg">', url="https://example.com/redirected/",
    ))
    monkeypatch.setattr("routes.ai.download_image", download)
    monkeypatch.setattr("routes.ai.get_claude", lambda: SimpleNamespace(
        messages=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(content=[SimpleNamespace(text="ignored")]))
    ))
    monkeypatch.setattr("routes.ai.parse_claude", lambda text: {"titel": "Rezept"})
    response = client.post("/api/analysiere-url", json={"url": "https://example.com/original"})
    assert response.status_code == 200
    download.assert_called_once_with("photo.jpg", "https://example.com/redirected/")


@pytest.mark.parametrize("error", [UnsafeUrlError("Adresse nicht erlaubt"), TooLargeError("Antwort zu groß")])
def test_download_image_returns_none_for_guard_errors(error, monkeypatch):
    from services import image_service

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(image_service, "safe_get", fail)
    assert image_service.download_image("https://example.com/photo.jpg", "https://example.com/") is None
