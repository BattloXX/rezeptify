"""
Rezeptify – Konfigurationsvorlage
Kopiere diese Datei als config.py und trage deine Werte ein:
    cp config.example.py config.py
"""
from pathlib import Path

# ── Pfade ─────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"

# ── Datenbank (MariaDB) ───────────────────────────────────────────────────────
DB_HOST     = "localhost"
DB_PORT     = 3306
DB_NAME     = "rezeptify"
DB_USER     = "rezeptify"
DB_PASSWORD = "DEIN_DB_PASSWORT"
DB_CHARSET  = "utf8mb4"

# ── Anthropic / Claude ────────────────────────────────────────────────────────
# API Key: https://console.anthropic.com/settings/keys
ANTHROPIC_API_KEY = "sk-ant-DEIN-KEY-HIER"

# Modell-Wahl (Kosten vs. Qualität):
# claude-haiku-4-5-20251001  → günstig  (~$0.003/Rezept) – empfohlen
# claude-sonnet-4-6           → mittel   (~$0.02/Rezept)
# claude-opus-4-6             → teuer    (~$0.10/Rezept)
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

# ── Upload ────────────────────────────────────────────────────────────────────
MAX_UPLOAD_MB  = 10
ALLOWED_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}

# ── App ───────────────────────────────────────────────────────────────────────
APP_TITLE = "Rezeptify"
DEBUG     = False
