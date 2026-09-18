"""Security-sensitive tests for the browser update API."""
import signal
import subprocess

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


def test_public_update_log_is_read_only_and_redacts_secrets(client, monkeypatch):
    import config
    from db import get_db

    monkeypatch.setattr(config, "AUTH_PASSWORD", "test-secret")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "api-secret")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO system_updates
                (status, von_version, ziel_version, log, fehler, beendet_am)
                VALUES ('fehlgeschlagen', '2.3.1', '2.3.2', %s, %s, NOW())""", (
                "Update gestartet\nAUTH_PASSWORD=test-secret\ntoken: api-secret\n"
                "https://user:api-secret@example.test/repo",
                "password=test-secret",
            ))

    response = client.get("/api/system/update-log")
    assert response.status_code == 200
    update = response.json()["updates"][0]
    assert set(update) == {"status", "von_version", "ziel_version", "gestartet_am", "beendet_am", "fehler", "log"}
    assert update["status"] == "fehlgeschlagen"
    assert update["von_version"] == "2.3.1"
    assert update["ziel_version"] == "2.3.2"
    assert "test-secret" not in update["log"] + update["fehler"]
    assert "api-secret" not in update["log"] + update["fehler"]
    assert "[REDACTED]" in update["log"]


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


def test_run_update_keeps_restart_pending_after_sigterm(client, monkeypatch):
    from services import update_service

    update_id = _insert_update()
    monkeypatch.setattr(update_service, "create_backup", lambda: "/private/backup")
    monkeypatch.setattr(update_service, "_run_git", lambda args: None)
    monkeypatch.setattr(update_service, "_run_pip", lambda: None)
    monkeypatch.setattr(update_service, "init_db", lambda: None)
    monkeypatch.setattr(
        update_service,
        "_run_systemctl_restart",
        lambda: (_ for _ in ()).throw(subprocess.CalledProcessError(-signal.SIGTERM, "systemctl")),
    )

    update_service.run_update(update_id)

    row = _row(update_id)
    assert row["status"] == "neustart_ausgeloest"
    assert row["fehler"] is None


def test_analysiere_bild_returns_clean_error_when_claude_fails(client, monkeypatch, tmp_path):
    from routes import ai

    monkeypatch.setattr(ai, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(
        ai, "get_claude",
        lambda: (_ for _ in ()).throw(RuntimeError("upstream secret failure")),
    )

    response = client.post(
        "/api/analysiere-bild",
        files={"file": ("rezept.jpg", b"not-a-real-image", "image/jpeg")},
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "Rezeptanalyse ist derzeit nicht verfügbar, bitte erneut versuchen"
    }


def test_global_error_handler_persists_redacted_public_error_log(client, monkeypatch):
    from routes import system

    def fail_version():
        raise RuntimeError(
            "AUTH_PASSWORD=test-secret ANTHROPIC_API_KEY=test-key "
            "DB_PASSWORD=rezeptify https://user:password@example.test"
        )

    monkeypatch.setattr(system, "_app_version", fail_version)
    response = client.get("/api/health")
    assert response.status_code == 500
    assert response.json() == {"detail": "Serverfehler, bitte erneut versuchen"}

    response = client.get("/api/system/error-log")
    assert response.status_code == 200
    error = response.json()["errors"][0]
    assert error["methode"] == "GET"
    assert error["pfad"] == "/api/health"
    assert error["exception_typ"] == "RuntimeError"
    assert "test-secret" not in error["nachricht"]
    assert "test-key" not in error["nachricht"]
    assert "rezeptify" not in error["nachricht"]
    assert "password@example.test" not in error["nachricht"]
    assert "[REDACTED]" in error["nachricht"]


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
