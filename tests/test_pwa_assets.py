"""Versioned app shell, public update probe and root-scoped service worker."""
import json
import os
from pathlib import Path
import re

import pytest


def test_versioned_shell(client):
    response = client.get("/")
    version = client.get("/api/asset-version")
    assert response.status_code == 200
    assert version.status_code == 200
    assert version.headers["Cache-Control"] == "no-store"
    token = version.json()["asset_version"]
    assert re.fullmatch(r"[0-9a-f]{10}", token)
    assert "no-cache" in response.headers["Cache-Control"]
    assert 'type="importmap"' in response.text
    assert f'/static/css/styles.css?v={token}' in response.text
    assert f'/static/js/app.js?v={token}' in response.text
    assert f'<meta name="rezeptify-asset-version" content="{token}">' in response.text


def test_import_map_covers_modules_and_matches_entry(client):
    html = client.get("/").text
    token = client.get("/api/asset-version").json()["asset_version"]
    match = re.search(r'<script type="importmap">(.*?)</script>', html, re.S)
    imports = json.loads(match.group(1))["imports"]
    base = Path(__file__).resolve().parents[1]
    expected = {
        "/" + path.relative_to(base).as_posix()
        for path in (base / "static/js").rglob("*.js") if path.is_file()
    }
    assert set(imports) == expected
    assert "/static/js/views/detail.js" in imports
    assert "/static/js/api.js" in imports
    assert all(target == f"{source}?v={token}" for source, target in imports.items())
    entry = re.search(r'<script type="module" src="([^"]+)"', html)
    assert imports["/static/js/app.js"] == entry.group(1)
    assert match.start() < entry.start()


def test_deep_link_returns_versioned_shell(client):
    response = client.get("/rezept/irgendwas")
    assert response.status_code == 200
    assert "no-cache" in response.headers["Cache-Control"]
    assert response.text == client.get("/").text


def test_service_worker(client):
    response = client.get("/service-worker")
    token = client.get("/api/asset-version").json()["asset_version"]
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert response.headers["Service-Worker-Allowed"] == "/"
    assert "no-cache" in response.headers["Cache-Control"]
    assert f"rezeptify-{token}" in response.text
    assert "__ASSET_VERSION__" not in response.text


def test_asset_version_is_public_with_auth_enabled(client, monkeypatch):
    import auth
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    assert client.get("/api/asset-version").status_code == 200


@pytest.mark.parametrize("relative", [
    "static/js/app.js", "static/js/views/detail.js", "static/css/styles.css",
    "static/sw.js", "VERSION",
])
def test_asset_changes_invalidate_version(tmp_path, monkeypatch, relative):
    from services import asset_version
    monkeypatch.setattr(asset_version, "BASE_DIR", tmp_path)
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("before", encoding="utf-8")
    before = asset_version.get_asset_version()
    cached = asset_version._hash_assets.cache_info()
    assert asset_version.get_asset_version() == before
    assert asset_version._hash_assets.cache_info().hits == cached.hits + 1
    stat = path.stat()
    path.write_text("after!", encoding="utf-8")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert asset_version.get_asset_version() != before


def test_asset_paths_invalidate_version(tmp_path, monkeypatch):
    from services import asset_version
    monkeypatch.setattr(asset_version, "BASE_DIR", tmp_path)
    path = tmp_path / "static/js/first.js"
    path.parent.mkdir(parents=True)
    path.write_text("export const value = 1;", encoding="utf-8")
    before = asset_version.get_asset_version()
    renamed = path.rename(path.with_name("second.js"))
    assert asset_version.get_asset_version() != before
    renamed.unlink()
    assert asset_version.get_asset_version() != before
