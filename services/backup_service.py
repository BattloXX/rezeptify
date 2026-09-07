"""Create private, local backups before a browser-triggered update."""
import shutil
import subprocess
import os
from datetime import datetime
from pathlib import Path

from config import BASE_DIR, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, UPLOAD_DIR

try:
    from config import BACKUP_DIR
except ImportError:  # Keeps old local config.py files usable until they are updated.
    BACKUP_DIR = BASE_DIR / "backups"


def _private_backup_dir() -> Path:
    """Return a configured backup location, rejecting anything served as static files."""
    backup_dir = Path(BACKUP_DIR).resolve()
    static_dir = (Path(BASE_DIR) / "static").resolve()
    try:
        backup_dir.relative_to(static_dir)
    except ValueError:
        return backup_dir
    raise RuntimeError("BACKUP_DIR darf nicht innerhalb von static/ liegen")


def _run_mysqldump(destination: Path) -> None:
    command = [
        "mysqldump", "--host", str(DB_HOST), "--port", str(DB_PORT),
        "--user", str(DB_USER),
        "--single-transaction", "--quick", "--routines", "--events", str(DB_NAME),
    ]
    with destination.open("wb") as dump_file:
        # Keep the password out of argv (and therefore out of process listings).
        subprocess.run(command, stdout=dump_file, stderr=subprocess.PIPE, check=True,
                       env={**os.environ, "MYSQL_PWD": str(DB_PASSWORD)})


def _rotate_backups(backup_dir: Path, keep: int = 5) -> None:
    backups = sorted((p for p in backup_dir.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
    for old_backup in backups[keep:]:
        # old_backup is an immediate child discovered from the dedicated backup directory.
        shutil.rmtree(old_backup)


def create_backup() -> str:
    """Dump the database and copy local deployment data; return the private path."""
    backup_dir = _private_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    destination.mkdir()
    _run_mysqldump(destination / "dump.sql")

    config_file = Path(BASE_DIR) / "config.py"
    if config_file.is_file():
        shutil.copy2(config_file, destination / "config.py")
    uploads = Path(UPLOAD_DIR)
    if uploads.is_dir():
        shutil.copytree(uploads, destination / "uploads")
    _rotate_backups(backup_dir)
    return str(destination)
