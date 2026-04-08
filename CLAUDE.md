# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Development server
uvicorn app:app --host 127.0.0.1 --port 8000 --reload

# Install dependencies
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Production restart (CloudPanel/systemd)
systemctl --user restart rezeptify
systemctl --user status rezeptify
journalctl --user -u rezeptify -f
```

There are no tests or linter configured for this project.

## Configuration

`config.py` is not tracked in Git. Copy `config.example.py` → `config.py` and fill in:
- `DB_HOST`, `DB_USER`, `DB_PASSWORD` (MariaDB connection)
- `ANTHROPIC_API_KEY`

The database schema is auto-created and migrated on startup (`init_db()` in `app.py`).

## Architecture

**Backend**: `app.py` (~930 lines) — single FastAPI file with all routes, DB access (raw PyMySQL, no ORM), and AI integration. `config.py` holds all settings.

**Frontend**: `static/index.html` (~4000+ lines) — vanilla JS single-page app with no framework. Service worker (`sw.js`) enables offline support (network-first for `/api/` and uploads, cache-first for static assets).

**Database** (MariaDB): Three tables — `rezepte` (recipes with JSON fields for `zutaten`/`tags`), `bilder` (images, cascade-deleted), `kategorien` (lookup). Full-text index on `(titel, beschreibung)` for search. Schema migrations run automatically at startup.

**AI features** (Claude Haiku 4.5, cost ~$0.003/recipe):
- `/api/analysiere-url` — fetches URL, strips HTML, calls Claude for structured JSON extraction
- `/api/analysiere-bild` — base64-encodes image/PDF, sends to Claude vision
- `/api/rezept-suche` — agentic loop (up to 6 rounds) using Claude's `web_search_20250305` tool

**Image pipeline**: Upload → EXIF auto-rotate → resize to max 1600px → JPEG quality 82 → UUID filename. Stored in `static/uploads/` (not tracked in Git).

**Deployment target**: CloudPanel + uWSGI or systemd user service. Entry points: `app:app` (uvicorn) or `wsgi:application` (uWSGI via `wsgi.py`).

## Key Patterns

- Slugs are generated via `make_slug()` (Unicode normalization + recipe ID suffix for uniqueness) and stored in DB
- JSON fields (`zutaten`, `tags`) are parsed from DB strings on every read
- AI responses use a 4-fallback JSON parser to handle markdown code fences, truncation, and bad characters
- Recipe deep links use clean URLs like `/rezept/pasta-carbonara-123`; the SPA catch-all route in FastAPI serves `index.html` for all non-API paths
