"""The deliberately small, fixed-command update workflow."""
import logging
import subprocess
import sys
from pathlib import Path

from config import BASE_DIR
try:
    from config import UPDATE_GIT_REMOTE, UPDATE_GIT_BRANCH
except ImportError:  # Compatibility for installations that have not copied new config keys yet.
    UPDATE_GIT_REMOTE, UPDATE_GIT_BRANCH = "origin", "main"

from db import get_db, init_db
from services.backup_service import create_backup

logger = logging.getLogger(__name__)


def _run_git(arguments: list[str]) -> None:
    subprocess.run(["git", *arguments], cwd=str(BASE_DIR), check=True)


def _run_pip() -> None:
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(Path(BASE_DIR) / "requirements.txt")],
                   cwd=str(BASE_DIR), check=True)


def _run_systemctl_restart() -> None:
    subprocess.run(["systemctl", "--user", "restart", "rezeptify"], check=True)


def _append_log(update_id: int, message: str) -> None:
    logger.info("Update %s: %s", update_id, message)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE system_updates SET log=CONCAT(COALESCE(log, ''), %s) WHERE id=%s",
                        (message + "\n", update_id))


def _fail(update_id: int, step: str, exc: Exception) -> None:
    message = f"Fehler in Schritt {step}: {exc}"
    logger.exception("Update %s fehlgeschlagen: %s", update_id, step)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE system_updates
                SET status='fehlgeschlagen', fehler=%s,
                    log=CONCAT(COALESCE(log, ''), %s), beendet_am=NOW()
                WHERE id=%s""", (str(exc)[:4000], message + "\n", update_id))


def run_update(update_id: int) -> None:
    """Run only fixed server-configured commands, never request-supplied commands."""
    try:
        _append_log(update_id, "Backup wird erstellt")
        backup_path = create_backup()
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE system_updates SET backup_pfad=%s WHERE id=%s", (backup_path, update_id))
        _append_log(update_id, "Backup abgeschlossen")
    except Exception as exc:
        _fail(update_id, "Backup", exc)
        return
    try:
        _append_log(update_id, "Repository wird aktualisiert")
        _run_git(["fetch", UPDATE_GIT_REMOTE, UPDATE_GIT_BRANCH])
        _run_git(["reset", "--hard", f"{UPDATE_GIT_REMOTE}/{UPDATE_GIT_BRANCH}"])
        _append_log(update_id, "Repository abgeschlossen")
    except Exception as exc:
        _fail(update_id, "Repository", exc)
        return
    try:
        _append_log(update_id, "Abhängigkeiten werden installiert")
        _run_pip()
        _append_log(update_id, "Abhängigkeiten abgeschlossen")
    except Exception as exc:
        _fail(update_id, "Abhängigkeiten", exc)
        return
    try:
        _append_log(update_id, "Datenbank wird migriert")
        init_db()
        _append_log(update_id, "Datenbank abgeschlossen")
    except Exception as exc:
        _fail(update_id, "Datenbank", exc)
        return
    try:
        # Persist this state before restarting: the next process proves success at startup.
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE system_updates SET status='neustart_ausgeloest' WHERE id=%s", (update_id,))
        _append_log(update_id, "Neustart wird ausgelöst")
        _run_systemctl_restart()
    except Exception as exc:
        _fail(update_id, "Neustart", exc)
