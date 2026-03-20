# 🌿 Rezeptify

> Persönliche Rezeptdatenbank der Familie Battlogg — PWA mit KI-Import

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)](https://fastapi.tiangolo.com)
[![Claude](https://img.shields.io/badge/Claude-Haiku-orange)](https://anthropic.com)

## Features

| Feature | Beschreibung |
|---------|-------------|
| 📱 **PWA** | Installierbar auf iOS & Android, offline-fähig, Querformat-Support |
| 🤖 **KI-Import** | URL, Screenshot, Kamerafoto oder PDF → Rezept automatisch extrahiert (Claude Haiku) |
| 📖 **Rezeptbuch** | Rezepte auswählen, sortieren, als mehrseitiges PDF exportieren (Deckblatt + Inhaltsverzeichnis) |
| ⭐ **Bewertungen** | 1–5 Sterne pro Rezept, sortierbar |
| 🔗 **Deep Links** | Jedes Rezept hat eine eigene URL zum Teilen (`/rezept/name`) |
| 📊 **Portionsskalierung** | Zutaten und Kalorien passen sich live an |
| 🔥 **Kalorien** | Automatisch von KI geschätzt, pro Portion |
| 📄 **PDF Export** | Einzelrezept als PDF mit Bild, Zutaten, Zubereitung |
| 🛒 **Einkaufsliste** | Zutaten einzeln oder gesamt kopieren (Google Keep etc.) |
| 🔍 **Suche & Filter** | Volltextsuche, Kategorie, Schwierigkeit, Tags, Sortierung |
| 📸 **Bilder** | Mehrere Bilder pro Rezept, Kamera-Upload direkt am Smartphone |
| 🗜️ **Auto-Komprimierung** | Bilder werden automatisch auf max. 1600px & JPEG skaliert |

## Tech Stack

| Schicht | Technologie |
|---------|-------------|
| Backend | Python 3.11 + FastAPI |
| Datenbank | MariaDB + PyMySQL |
| KI | Anthropic Claude Haiku |
| Bildverarbeitung | Pillow (resize + EXIF-Rotation) |
| Frontend | Vanilla JS + PWA (kein Framework) |
| Hosting | CloudPanel + Systemd User Service |

## Setup

### Voraussetzungen
- Python 3.11
- MariaDB Datenbank
- Anthropic API Key → https://console.anthropic.com/settings/keys

### Installation

```bash
# 1. Repository klonen
git clone https://github.com/BattloXX/rezeptify.git
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

Siehe `SETUP.md` für die vollständige CloudPanel-Anleitung inkl. Systemd-Service.

## Projektstruktur

```
rezeptify/
├── app.py                 # FastAPI Backend + alle API Routes
├── config.py              # Zentrale Konfiguration (nicht in Git!)
├── config.example.py      # Vorlage für config.py
├── requirements.txt
├── wsgi.py                # uWSGI Entry Point
├── SETUP.md               # CloudPanel Deployment Guide
└── static/
    ├── index.html         # PWA Single Page App (komplettes Frontend)
    ├── manifest.json      # PWA Manifest (Orientation: any)
    ├── sw.js              # Service Worker (Offline-Support)
    ├── icons/             # App Icons (favicon, apple-touch, android-chrome)
    └── uploads/           # Hochgeladene Bilder (nicht in Git)
```

## API Endpunkte

```
GET    /api/rezepte                    Liste + Suche + Filter + Sort
GET    /api/rezepte/{id}               Einzelrezept
GET    /api/rezepte/slug/{slug}        Rezept per URL-Slug (Deep Links)
POST   /api/rezepte                    Erstellen
PUT    /api/rezepte/{id}               Aktualisieren
DELETE /api/rezepte/{id}               Löschen
PATCH  /api/rezepte/{id}/bewertung     Sterne setzen (1–5)
POST   /api/rezepte/{id}/bilder        Bild hochladen (auto-resize)
DELETE /api/bilder/{id}                Bild löschen
PUT    /api/bilder/{id}/haupt          Als Hauptbild setzen
POST   /api/analysiere-url             URL via Claude analysieren
POST   /api/analysiere-bild            Screenshot/Foto/PDF via Claude analysieren
GET    /api/kategorien                 Kategorieliste
GET    /api/tags                       Alle verwendeten Tags
GET    /api/stats                      Statistiken
```

## Git Workflow

```bash
# Änderungen committen und pushen
git add .
git commit -m "Feature: Beschreibung der Änderung"
git push -u origin main
```

Auth: Personal Access Token (kein GitHub-Passwort).
Token einmalig speichern: `git config credential.helper store`

## Konfiguration

Alle Einstellungen zentral in `config.py` (wird **nicht** in Git verwaltet):

```python
CLAUDE_MODEL = "claude-haiku-4-5-20251001"  # Günstigstes Modell (~$0.003/Analyse)
DB_HOST      = "localhost"
DB_NAME      = "rezeptify"
DB_USER      = "rezeptify"
DB_PASSWORD  = "..."
ANTHROPIC_API_KEY = "sk-ant-..."
IMG_MAX_PX   = 1600    # Max. Bildgröße nach Upload
IMG_QUALITY  = 82      # JPEG-Qualität
```

## Server-Verwaltung

```bash
# App neustarten
systemctl --user restart rezeptify

# Status prüfen
systemctl --user status rezeptify

# Logs live
journalctl --user -u rezeptify -f

# Nächste Neustarts (Timer)
systemctl --user list-timers
```

## Kosten

Ca. **$0.003 pro KI-Analyse** mit Claude Haiku.
10 Rezepte ≈ $0.03 · 1.000 Rezepte ≈ $3.00

## PWA installieren

**iOS (Safari):** Teilen ⎙ → „Zum Home-Bildschirm"  
**Android (Chrome):** Installations-Banner antippen oder Menü → „App installieren"

## Rezept-Suchbot

Der Suchbot verwendet Claude mit Web Search um passende Rezepte im Internet zu finden.

**Funktionsweise:**
1. Freitext-Beschreibung eingeben (Ernährung, Zutaten, Zeit, Personenzahl, etc.)
2. Claude durchsucht deutschsprachige Rezeptseiten (Chefkoch, Lecker, gutekueche.at, etc.)
3. Die **2–3 besten Ergebnisse** werden nach Bewertungen gefiltert und vollständig extrahiert
4. Jedes Ergebnis kann direkt gespeichert oder bearbeitet werden

**Darstellung:** 🥇 Beste Wahl · 🥈 Gute Alternative · 🥉 Weitere Option

**Bevorzugte Quellen:** chefkoch.de, lecker.de, küchengötter.de, gutekueche.at, ichkoche.at, rezeptwelt.at

**Kosten:** Ca. $0.01–0.02 pro Suche (Web Search + längerer Kontext)

**Endpunkt:** `POST /api/rezept-suche` → gibt JSON-Array mit 2–3 Rezepten zurück
