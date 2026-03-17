# 🌿 Rezeptify

> Persönliche Rezeptdatenbank der Familie Battlogg — PWA mit KI-Import

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)](https://fastapi.tiangolo.com)
[![Claude](https://img.shields.io/badge/Claude-Haiku-orange)](https://anthropic.com)

## Features

- 📱 **PWA** — installierbar auf iOS & Android, offline-fähig
- 🤖 **KI-Import** — URL, Screenshot, Kamerafoto oder PDF → Rezept automatisch extrahiert
- ⭐ **Bewertungen** — 1–5 Sterne pro Rezept
- 🔗 **Deep Links** — jedes Rezept hat eine eigene URL zum Teilen
- 📊 **Portionsskalierung** — Zutaten passen sich automatisch an
- 🔥 **Kalorienangabe** — wird automatisch von der KI geschätzt
- 📄 **PDF Export** — sauberes Drucklayout mit Bild
- 🛒 **Einkaufsliste** — Zutaten mit einem Klick kopieren (für Google Keep etc.)

## Tech Stack

| Schicht | Technologie |
|---------|-------------|
| Backend | Python 3.11 + FastAPI |
| Datenbank | MariaDB + PyMySQL |
| KI | Anthropic Claude (Haiku) |
| Frontend | Vanilla JS + PWA |
| Hosting | CloudPanel + Systemd |

## Setup

### Voraussetzungen
- Python 3.11
- MariaDB Datenbank
- Anthropic API Key → https://console.anthropic.com/settings/keys

### Installation

```bash
# 1. Repository klonen
git clone https://github.com/DEIN-USERNAME/rezeptify.git
cd rezeptify

# 2. Konfiguration einrichten
cp config.example.py config.py
nano config.py   # DB-Zugangsdaten + API Key eintragen

# 3. Virtuelle Umgebung + Pakete
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. Starten
uvicorn app:app --host 127.0.0.1 --port 8000
```

### CloudPanel (Produktion)

Siehe `SETUP.md` für die vollständige CloudPanel-Anleitung.

## Projektstruktur

```
rezeptify/
├── app.py                 # FastAPI Backend + API Routes
├── config.example.py      # Konfigurationsvorlage (config.py nicht committen!)
├── requirements.txt
├── wsgi.py                # uWSGI Entry Point
├── SETUP.md               # CloudPanel Deployment Guide
└── static/
    ├── index.html         # PWA Single Page App
    ├── manifest.json      # PWA Manifest
    ├── sw.js              # Service Worker
    ├── icons/             # App Icons
    └── uploads/           # Hochgeladene Bilder (nicht in Git)
```

## Entwicklung

```bash
# Lokale Entwicklung mit Auto-Reload
uvicorn app:app --reload --port 8000

# Server neustarten (Produktion)
systemctl --user restart rezeptify
```

## Deployment auf Server

```bash
# Geänderte Dateien per SFTP hochladen, dann:
systemctl --user restart rezeptify

# Logs ansehen
journalctl --user -u rezeptify -f
```

## Konfiguration

Alle Einstellungen zentral in `config.py` (wird nicht in Git verwaltet):

```python
CLAUDE_MODEL = "claude-haiku-4-5-20251001"  # Günstigstes Modell
DB_PASSWORD  = "..."
ANTHROPIC_API_KEY = "sk-ant-..."
```

## Kosten

Ca. **$0.003 pro KI-Analyse** mit Claude Haiku (URL-Import, Screenshot, PDF).
