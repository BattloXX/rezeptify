"""Authenticated system administration endpoints and the public health probe."""
import logging
import secrets
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from auth import require_auth
import config
from db import SCHEMA_VERSION, get_db
from services.update_service import run_update

logger = logging.getLogger(__name__)
public_router = APIRouter()
router = APIRouter(dependencies=[Depends(require_auth)])
_RELEASE_URL = "https://api.github.com/repos/BattloXX/rezeptify/releases/latest"


def _app_version() -> str:
    # Imported lazily to avoid a circular import while app.py constructs routers.
    from app import APP_VERSION
    return APP_VERSION


def semver_is_newer(current: str, candidate: str) -> bool:
    """Compare normal SemVer release numbers without adding a dependency."""
    def parse(value: str):
        value = str(value).strip().lstrip("v").split("+", 1)[0]
        core, separator, prerelease = value.partition("-")
        parts = core.split(".")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            raise ValueError("Ungültige SemVer-Version")
        # A normal release supersedes a prerelease with the same numeric core.
        return tuple(int(part) for part in parts), (1 if not separator else 0), prerelease
    try:
        return parse(candidate) > parse(current)
    except (TypeError, ValueError):
        return False


def latest_release_version() -> Optional[str]:
    try:
        with httpx.Client(timeout=5.0, headers={"Accept": "application/vnd.github+json"}) as client:
            response = client.get(_RELEASE_URL)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        tag = response.json().get("tag_name")
        return tag.lstrip("v") if isinstance(tag, str) and tag.strip() else None
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Update-Check nicht verfügbar: %s", exc)
        return None


def _serialize(row: dict) -> dict:
    for key in ("gestartet_am", "beendet_am"):
        if row.get(key) and not isinstance(row[key], str):
            row[key] = row[key].isoformat()
    return row


@public_router.get("/api/health")
def health():
    database = "ok"
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
    except Exception:
        database = "error"
    return {"status": "ok", "version": _app_version(), "database": database,
            "schema_version": SCHEMA_VERSION}


@router.get("/api/system/update-check")
def update_check():
    current = _app_version()
    latest = latest_release_version()
    if latest is None:
        return {"aktuelle_version": current, "neueste_version": None,
                "update_verfuegbar": False, "hinweis": "Keine Releases gefunden"}
    return {"aktuelle_version": current, "neueste_version": latest,
            "update_verfuegbar": semver_is_newer(current, latest)}


@router.post("/api/system/update")
def start_update(body: dict, background_tasks: BackgroundTasks):
    password = body.get("passwort")
    if not isinstance(password, str) or not secrets.compare_digest(password.encode(), config.AUTH_PASSWORD.encode()):
        # 403, not 401: the frontend's global api() wrapper treats any 401 as an
        # expired session and force-logs-out the user. A wrong confirmation
        # password here is a separate concern from the session itself being invalid.
        raise HTTPException(403, "Passwort-Bestätigung fehlgeschlagen")

    # GET_LOCK serializes the check+insert across worker processes. The durable
    # status row then protects the whole background operation after this lock ends.
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT GET_LOCK('rezeptify_system_update_start', 5) AS locked")
            if not cur.fetchone()["locked"]:
                raise HTTPException(409, "Ein Update wird bereits vorbereitet")
            try:
                cur.execute("SELECT id FROM system_updates WHERE status IN ('laufend','neustart_ausgeloest') LIMIT 1")
                if cur.fetchone():
                    raise HTTPException(409, "Ein Update läuft bereits")
                target = latest_release_version()
                cur.execute("""INSERT INTO system_updates (status, von_version, ziel_version, log)
                    VALUES ('laufend', %s, %s, %s)""",
                    (_app_version(), target, "Update gestartet\n"))
                update_id = cur.lastrowid
            finally:
                cur.execute("SELECT RELEASE_LOCK('rezeptify_system_update_start')")
    logger.info("Update %s gestartet", update_id)
    background_tasks.add_task(run_update, update_id)
    return {"status": "gestartet", "update_id": update_id}


@router.get("/api/system/update-status/{update_id}")
def update_status(update_id: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, gestartet_am, status, von_version, ziel_version,
                log, fehler, beendet_am FROM system_updates WHERE id=%s""", (update_id,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Update nicht gefunden")
    return _serialize(row)


@router.get("/api/system/update-historie")
def update_history():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, gestartet_am, status, von_version, ziel_version,
                fehler, beendet_am FROM system_updates ORDER BY id DESC LIMIT 20""")
            rows = cur.fetchall()
    return {"updates": [_serialize(row) for row in rows]}
