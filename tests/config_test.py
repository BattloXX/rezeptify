"""Container-only configuration used by the MariaDB integration tests."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
DB_HOST = os.getenv("TEST_DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("TEST_DB_PORT", "3307"))
DB_NAME = os.getenv("TEST_DB_NAME", "rezeptify_test")
DB_USER = os.getenv("TEST_DB_USER", "rezeptify")
DB_PASSWORD = os.getenv("TEST_DB_PASSWORD", "rezeptify")
DB_CHARSET = "utf8mb4"
ANTHROPIC_API_KEY = "test-key"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
AUTH_ENABLED = False
AUTH_PASSWORD = ""
CORS_ORIGINS = ["*"]
MAX_UPLOAD_MB = 10
ALLOWED_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}
APP_TITLE = "Rezeptify Test"
DEBUG = True
