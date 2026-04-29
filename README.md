# 🌿 Rezeptify v2.0

> Persönliche Rezeptdatenbank der Familie Battlogg — PWA mit KI-Import

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)](https://fastapi.tiangolo.com)
[![Claude](https://img.shields.io/badge/Claude-Haiku_4.5-orange)](https://anthropic.com)

## Features

| Feature | Beschreibung |
|---------|-------------|
| 📱 **PWA** | Installierbar auf iOS & Android, offline-fähig |
| 🤖 **KI-Import** | URL, Screenshot, Kamerafoto oder PDF → Rezept automatisch extrahiert (Claude Haiku 4.5) |
| 📐 **Metrische Einheiten** | KI konvertiert cups/oz/°F automatisch → ml/g/°C |
| 🔍 **KI-Suchbot** | Freitext-Suche via Web Search — findet & extrahiert komplette Rezepte |
| 📖 **Rezeptbuch** | Rezepte auswählen, sortieren, als mehrseitiges PDF exportieren |
| ⭐ **Bewertungen** | 1–5 Sterne pro Rezept, sortierbar |
| 🔗 **Deep Links** | Jedes Rezept hat eine eigene URL (`/rezept/pasta-carbonara-42`) |
| 📊 **Portionsskalierung** | Zutaten passen sich live an |
| 📄 **PDF Export** | Einzelrezept als PDF mit Bild, Zutaten, Zubereitung |
| 🛒 **Einkaufsliste** | Zutaten einzeln oder gesamt kopieren |
| 🔒 **Passwortschutz** | HTTP Basic Auth — Zugang nur mit Passwort |
| 🌙 **Dark Mode** | Automatisch via `prefers-color-scheme` |
| 📸 **Mehrere Bilder** | Galerie pro Rezept, Drag-to-reorder, Auto-Bild von Chefkoch.de |
| 🗂️ **Zutatengruppen** | z.B. „Für den Teig" / „Für das Frosting" |

## Tech Stack

| Schicht | Technologie |
|---------|-------------|
| Backend | Python 3.11 + FastAPI (modular, Router-basiert) |
| Datenbank | MariaDB + PyMySQL |
| KI | Anthropic Claude Haiku 4.5 mit Prompt Caching |
| Bildverarbeitung | Pillow (resize + EXIF-Rotation) |
| Frontend | Vanilla JS ES Modules (kein Build-Schritt, kein Framework) |
| Hosting | CloudPanel + Systemd User Service |

## Projektstruktur

```
rezeptify/
├── app.py                  # FastAPI Entry Point (~35 Zeilen)
├── auth.py                 # HTTP Basic Auth
├── db.py                   # DB-Verbindung, Migrations, Helpers
├── models.py               # Pydantic Modelle
├── slug_utils.py           # URL-Slugs mit Umlaut-Handling
├── config.py               # Konfiguration (nicht in Git!)
├── config.example.py       # Vorlage
├── requirements.txt
├── wsgi.py                 # uWSGI Entry Point
├── SETUP.md                # CloudPanel Deployment Guide
├── routes/
│   ├── rezepte.py          # CRUD Rezepte
│   ├── bilder.py           # Bild-Upload / Verwaltung
│   ├── ai.py               # KI-Analyse Endpunkte
│   └── meta.py             # Kategorien, Tags, Statistiken
├── services/
│   ├── claude_service.py   # Claude Prompts + Metrik-Konvertierung
│   └── image_service.py    # Bild-Download, Resize, Validierung
└── static/
    ├── index.html          # HTML-Shell (~220 Zeilen)
    ├── manifest.json       # PWA Manifest
    ├── sw.js               # Service Worker
    ├── css/
    │   └── styles.css      # Alle Styles (~780 Zeilen)
    ├── js/
    │   ├── app.js          # App-Init, Navigation, Login, PWA
    │   ├── api.js          # Fetch-Wrapper, Auth-Token
    │   ├── utils.js        # HTML-Escape, Toast, Skalierung, Emojis
    │   └── views/
    │       ├── home.js     # Rezepte-Grid, Suche, Filter, Sort
    │       ├── detail.js   # Rezept-Detail, Bewertung, PDF
    │       ├── form.js     # Erstellen/Bearbeiten Formular
    │       ├── import.js   # URL/Bild Import
    │       ├── bot.js      # KI-Suchbot
    │       └── buch.js     # Rezeptbuch PDF-Export
    └── uploads/            # Hochgeladene Bilder (nicht in Git)
```

## Setup (Erstinstallation)

### Voraussetzungen
- Python 3.11, MariaDB, Anthropic API Key

```bash
# 1. Repository klonen
git clone https://github.com/BattloXX/rezeptify.git
cd rezeptify

# 2. Konfiguration einrichten
cp config.example.py config.py
nano config.py   # DB-Zugangsdaten + API Key + Passwort eintragen

# 3. Virtuelle Umgebung + Pakete
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. Starten
uvicorn app:app --host 127.0.0.1 --port 8000
```

Siehe `SETUP.md` für die vollständige CloudPanel-Anleitung.

## Update einspielen (v1 → v2)

```bash
# 1. Auf dem Server: aktuellen Stand holen
ssh user@server
cd /home/SITE-USER/htdocs/rezeptify.domain.de

git pull origin main

# 2. Neue Abhängigkeiten installieren
source venv/bin/activate
pip install -r requirements.txt

# 3. config.py aktualisieren — neue Felder eintragen
#    Vorlage: config.example.py
#    Neu in v2: AUTH_ENABLED, AUTH_PASSWORD, CORS_ORIGINS
nano config.py

# 4. Service neustarten
systemctl --user restart rezeptify

# 5. Status prüfen
systemctl --user status rezeptify
journalctl --user -u rezeptify -f
```

> **Datenbank:** Schema-Migrationen laufen automatisch beim Start.  
> **config.py wird nicht überschrieben** — nur neue Felder manuell ergänzen.

### Neue config.py Felder (v2)

```python
# Passwortschutz (v2 neu)
AUTH_ENABLED  = True
AUTH_PASSWORD = "sicheres-passwort"

# CORS (v2 neu) — nur wenn von anderem Port/Domain zugegriffen wird
CORS_ORIGINS  = ["https://deine-domain.de"]
```

## API Endpunkte

```
GET    /api/rezepte                    Liste + Suche + Filter + Sort
GET    /api/rezepte/{id}               Einzelrezept
GET    /api/rezepte/slug/{slug}        Rezept per URL-Slug (Deep Links)
POST   /api/rezepte                    Erstellen
PUT    /api/rezepte/{id}               Aktualisieren
DELETE /api/rezepte/{id}               Löschen
PATCH  /api/rezepte/{id}/bewertung     Sterne setzen (1–5 oder null)

POST   /api/rezepte/{id}/bilder        Bild hochladen (auto-resize)
POST   /api/rezepte/{id}/bilder/attach Gespeichertes Bild zuweisen
DELETE /api/bilder/{id}                Bild löschen
PUT    /api/bilder/{id}/haupt          Als Hauptbild setzen
POST   /api/rezepte/{id}/fetch-bild    Internet-Bild automatisch suchen

POST   /api/analysiere-url             URL via Claude analysieren
POST   /api/analysiere-bild            Screenshot/Foto/PDF via Claude
POST   /api/rezept-suche               Rezepte im Internet suchen (Suchbot)

GET    /api/kategorien                 Kategorieliste
GET    /api/tags                       Alle verwendeten Tags
GET    /api/stats                      Statistiken
```

## Konfiguration (`config.py`)

```python
CLAUDE_MODEL    = "claude-haiku-4-5-20251001"  # ~$0.003/Analyse
DB_HOST         = "localhost"
DB_NAME         = "rezeptify"
DB_USER         = "rezeptify"
DB_PASSWORD     = "..."
ANTHROPIC_API_KEY = "sk-ant-..."
AUTH_ENABLED    = True
AUTH_PASSWORD   = "..."
CORS_ORIGINS    = ["https://deine-domain.de"]
IMG_MAX_PX      = 1600    # Max. Bildgröße nach Upload
IMG_QUALITY     = 82      # JPEG-Qualität
DEBUG           = False
```

## Metrische Einheiten (v2)

Alle KI-Importe erzwingen metrische Einheiten:

| Imperial | Metrisch |
|----------|---------|
| 1 cup Mehl | 120 g |
| 1 cup Milch | 240 ml |
| 1 oz | 28 g |
| 1 lb | 454 g |
| 350 °F | 175 °C |
| 1 stick Butter | 115 g |

Erlaubte Einheiten: `g`, `kg`, `ml`, `l`, `EL`, `TL`, `Prise`, `Stück`

## Server-Verwaltung

```bash
systemctl --user restart rezeptify   # Neustarten
systemctl --user status rezeptify    # Status
journalctl --user -u rezeptify -f    # Logs live
```

## Kosten

| Aktion | Kosten |
|--------|--------|
| URL/Bild analysieren | ~$0.003 |
| KI-Suchbot | ~$0.01–0.02 |
| Prompt Caching | ~80% günstiger bei Wiederholung |

## PWA installieren

**iOS (Safari):** Teilen ⎙ → „Zum Home-Bildschirm"  
**Android (Chrome):** Installations-Banner oder Menü → „App installieren"
