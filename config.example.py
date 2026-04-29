"""
Rezeptify v2.0 – Konfigurationsvorlage
Kopiere als config.py und trage deine Werte ein:
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
ANTHROPIC_API_KEY = "sk-ant-DEIN-KEY-HIER"

# Modell-Wahl:
# claude-haiku-4-5-20251001  → günstig (~$0.003/Rezept) – empfohlen
# claude-sonnet-4-6           → mittel  (~$0.02/Rezept)
# claude-opus-4-6             → teuer   (~$0.10/Rezept)
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

# ── Authentifizierung ─────────────────────────────────────────────────────────
AUTH_ENABLED  = True
AUTH_PASSWORD = "DEIN_APP_PASSWORT"   # Nur Passwort, kein Benutzername nötig

# ── CORS (Produktion: eigene Domain eintragen) ────────────────────────────────
CORS_ORIGINS = ["*"]   # z.B. ["https://rezeptify.battlogg.at"]

# ── Upload ────────────────────────────────────────────────────────────────────
MAX_UPLOAD_MB  = 10
ALLOWED_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}

# ── App ───────────────────────────────────────────────────────────────────────
APP_TITLE = "Rezeptify"
DEBUG     = False
