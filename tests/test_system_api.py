"""Security-sensitive tests for the browser update API."""
import pytest


def _insert_update(status="laufend"):
    from db import get_db
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO system_updates (status, von_version) VALUES (%s, '2.1.0')", (status,))
            return cur.lastrowid


def _row(update_id):
    from db import get_db
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM system_updates WHERE id=%s", (update_id,))
            return cur.fetchone()


def test_health_is_public_and_has_no_sensitive_fields(client):
    from routes import system
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"
    assert set(response.json()) == {"status", "version", "database", "schema_version"}
    assert system.public_router.dependencies == []


def test_update_requires_password_confirmation(client, monkeypatch):
    import config
    monkeypatch.setattr(config, "AUTH_PASSWORD", "test-secret")
    assert client.post("/api/system/update", json={}).status_code == 403
    assert client.post("/api/system/update", json={"passwort": "wrong"}).status_code == 403


def test_update_lock_rejects_second_attempt(client, monkeypatch):
    import config
    monkeypatch.setattr(config, "AUTH_PASSWORD", "test-secret")
    _insert_update("laufend")
    response = client.post("/api/system/update", json={"passwort": "test-secret"})
    assert response.status_code == 409


def test_run_update_success_is_fully_mocked(client, monkeypatch):
    from services import update_service
    update_id = _insert_update()
    calls = []
    monkeypatch.setattr(update_service, "create_backup", lambda: "/private/backup")
    monkeypatch.setattr(update_service, "_run_git", lambda args: calls.append(("git", args)))
    monkeypatch.setattr(update_service, "_run_pip", lambda: calls.append(("pip",)))
    monkeypatch.setattr(update_service, "_run_systemctl_restart", lambda: calls.append(("systemctl",)))
    monkeypatch.setattr(update_service, "init_db", lambda: calls.append(("db",)))
    update_service.run_update(update_id)
    row = _row(update_id)
    assert row["status"] == "neustart_ausgeloest"
    assert row["backup_pfad"] == "/private/backup"
    assert [item[0] for item in calls] == ["git", "git", "pip", "db", "systemctl"]


def test_run_update_records_mocked_step_failure(client, monkeypatch):
    from services import update_service
    update_id = _insert_update()
    monkeypatch.setattr(update_service, "create_backup", lambda: "/private/backup")
    monkeypatch.setattr(update_service, "_run_git", lambda args: (_ for _ in ()).throw(RuntimeError("git failure")))
    monkeypatch.setattr(update_service, "_run_pip", pytest.fail)
    monkeypatch.setattr(update_service, "_run_systemctl_restart", pytest.fail)
    update_service.run_update(update_id)
    row = _row(update_id)
    assert row["status"] == "fehlgeschlagen"
    assert "git failure" in row["fehler"]
    assert "Repository" in row["log"]


@pytest.mark.parametrize(("current", "candidate", "expected"), [
    ("2.1.0", "2.2.0", True), ("2.1.0", "2.1.0", False),
    ("2.1.0", "v2.1.1", True), ("2.1.0", "not-a-version", False),
])
def test_semver_comparison(current, candidate, expected):
    from routes.system import semver_is_newer
    assert semver_is_newer(current, candidate) is expected


def test_no_release_response(client, monkeypatch):
    from routes import system
    monkeypatch.setattr(system, "latest_release_version", lambda: None)
    response = client.get("/api/system/update-check")
    assert response.status_code == 200
    assert response.json()["neueste_version"] is None
    assert response.json()["update_verfuegbar"] is False
