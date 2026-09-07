"""MariaDB-backed fixtures; no SQLite substitute for production SQL semantics."""
import os
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _install_test_config():
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    module = types.ModuleType("config")
    module.BASE_DIR = root
    module.UPLOAD_DIR = root / "static" / "uploads"
    module.DB_HOST = os.getenv("TEST_DB_HOST", "127.0.0.1")
    module.DB_PORT = int(os.getenv("TEST_DB_PORT", "3307"))
    module.DB_NAME = os.getenv("TEST_DB_NAME", "rezeptify_test")
    module.DB_USER = os.getenv("TEST_DB_USER", "rezeptify")
    module.DB_PASSWORD = os.getenv("TEST_DB_PASSWORD", "rezeptify")
    module.DB_CHARSET = "utf8mb4"
    module.ANTHROPIC_API_KEY = "test-key"
    module.CLAUDE_MODEL = "claude-haiku-4-5-20251001"
    module.AUTH_ENABLED = False
    module.AUTH_PASSWORD = ""
    module.CORS_ORIGINS = ["*"]
    module.MAX_UPLOAD_MB = 10
    module.ALLOWED_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}
    module.APP_TITLE = "Rezeptify Test"
    module.DEBUG = True
    sys.modules["config"] = module


_install_test_config()


@pytest.fixture()
def client():
    from app import app
    from db import get_db

    with TestClient(app) as test_client:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM einkaufsliste_eintraege")
                cur.execute("DELETE FROM wochenplan")
                cur.execute("DELETE FROM kochhistorie")
                cur.execute("DELETE FROM rezepte")
        yield test_client
