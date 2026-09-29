# 🌿 Rezeptify

> Persönliche Rezeptdatenbank der Familie Battlogg — PWA mit KI-Import, Kochmodus, Einkaufsliste, Wochenplanung und MCP-Anbindung für Claude/ChatGPT

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)](https://fastapi.tiangolo.com)
[![Claude](https://img.shields.io/badge/Claude-Haiku_4.5-orange)](https://anthropic.com)

Aktuelle Version: siehe Datei [`VERSION`](VERSION) bzw. die [Releases](https://github.com/BattloXX/rezeptify/releases).

## Features

### Rezepte sammeln

| Feature | Beschreibung |
|---------|-------------|
| 🤖 **KI-Import** | URL, Screenshot, Kamerafoto oder PDF → Rezept automatisch extrahiert (Claude Haiku 4.5) |
| 📦 **Mehrfach-Import** | Mehrere URLs (eine pro Zeile) oder mehrere Dateien auf einmal; Fortschrittsliste pro Rezept, ein Fehler bricht den Rest nicht ab |
| 📄 **JSON-Import** | Rezeptdateien im offenen `rezeptify-recipe/v1`-Format werden deterministisch und ohne KI importiert |
| 🔍 **KI-Suchbot** | Freitext-Suche mit Web Search — findet und extrahiert komplette Rezepte |
| 📐 **Metrische Einheiten** | Die KI rechnet cups/oz/°F automatisch in ml/g/°C um |
| 🤝 **MCP-Anbindung** | Rezepte direkt aus einem Chat mit Claude oder ChatGPT suchen und anlegen (siehe [MCP](#mcp-server)) |

### Rezepte verwalten

| Feature | Beschreibung |
|---------|-------------|
| 🔗 **Deep Links** | Jedes Rezept hat eine eigene URL (`/rezept/pasta-carbonara-42`) |
| 📸 **Mehrere Bilder** | Galerie pro Rezept, Hauptbild wählbar, Upload, Bild-URL oder automatische Bildsuche |
| 🗂️ **Zutatengruppen** | z. B. „Für den Teig" / „Für das Frosting" |
| ⭐ **Bewertungen** | 1–5 Sterne pro Rezept, sortierbar |
| ❤️ **Favoriten & Kochhistorie** | Favoriten markieren, „gekocht" festhalten; Sortierung nach zuletzt/häufig/lange nicht gekocht |
| 📊 **Portionsskalierung** | Zutatenmengen passen sich live an |
| 📖 **Rezeptbuch** | Rezepte auswählen, sortieren und als mehrseitiges PDF exportieren; auch Einzelrezept-PDF |

### Im Alltag

| Feature | Beschreibung |
|---------|-------------|
| 👩‍🍳 **Kochmodus** | Schritt-für-Schritt-Ansicht mit erkannten Timern; Schritte werden automatisch aus der Zubereitung erzeugt und lassen sich anpassen |
| 🛒 **Einkaufsliste** | Dauerhafte Liste; Zutaten eines Rezepts oder eines ganzen Wochenplans hinzufügen, gleiche Zutaten werden zusammengeführt, Erledigtes aufräumen |
| 📅 **Wochenplanung** | Rezepte auf Tage und Mahlzeiten (Frühstück, Mittag, Abend, Snack) verteilen, daraus die Einkaufsliste erzeugen |
| 🍽️ **„Was kochen wir?"** | Vorschläge aus den eigenen Rezepten nach Zutaten, Zeit, Kategorie, vegetarisch/vegan, Bewertung, Schwierigkeit oder „lange nicht gekocht" |

### Betrieb

| Feature | Beschreibung |
|---------|-------------|
| 📱 **PWA** | Installierbar auf iOS & Android, offline-fähig (Service Worker) |
| 🌙 **Dark Mode** | Automatisch via `prefers-color-scheme` |
| 🔒 **Zugangsschutz** | Optionales gemeinsames Familienpasswort (HTTP Basic); die Website kann auch öffentlich betrieben werden |
| 🔄 **Update im Browser** | Neue Releases prüfen und mit Passwort-Bestätigung einspielen (Backup → Git → pip → DB-Migration → Neustart) |
| 🩺 **Health, Update- und Fehlerlog** | `/api/health` sowie öffentliche, von Secrets bereinigte Update- und Fehlerprotokolle |

## Tech Stack

| Schicht | Technologie |
|---------|-------------|
| Backend | Python 3.11 + FastAPI (modular, Router-basiert), Pydantic 2 |
| Datenbank | MariaDB + PyMySQL (Schema wird beim Start automatisch angelegt/migriert) |
| KI | Anthropic Claude Haiku 4.5 mit Prompt Caching |
| MCP | Offizielles `mcp`-SDK (Streamable HTTP + OAuth 2.1, lokal auch stdio) |
| Bildverarbeitung | Pillow + pillow-heif (Größe max. 1600 px, EXIF-Rotation, JPEG) |
| Frontend | Vanilla JS ES Modules (kein Build-Schritt, kein Framework) |
| Hosting | CloudPanel (nginx) + systemd User Service (`uvicorn`) |

## Projektstruktur

```
rezeptify/
├── app.py                  # FastAPI-Einstieg: Router, CORS, MCP-Mount, SPA-Catch-all
├── auth.py                 # Zugangsschutz: Basic-Passwort, Bearer-Token (MCP_API_TOKEN)
├── db.py                   # DB-Verbindung, Schema/Migrationen (init_db), Helper
├── models.py               # Pydantic-Modelle
├── slug_utils.py           # URL-Slugs mit Umlaut-Handling
├── config.py               # Konfiguration (nicht in Git!)
├── config.example.py       # Vorlage für config.py
├── requirements.txt        # Produktionsabhängigkeiten
├── requirements-dev.txt    # + Testabhängigkeiten
├── wsgi.py                 # Alternativer Entry Point
├── VERSION                 # Aktuelle Version (Grundlage für Release/Update)
├── SETUP.md                # CloudPanel-Deployment-Anleitung
├── pytest.ini              # Root-Tests laufen nur unter tests/
├── docker-compose.test.yml # Testumgebung: MariaDB + App-Container
├── Dockerfile.test
├── routes/
│   ├── rezepte.py          # CRUD, Suche, Bewertung, Favoriten
│   ├── bilder.py           # Bild-Upload, Bild-URL, Hauptbild
│   ├── ai.py               # KI-Analyse, JSON-Import, Suchbot
│   ├── kochen.py           # Kochmodus-Schritte, Kochhistorie
│   ├── einkauf.py          # Einkaufsliste
│   ├── planung.py          # Wochenplan
│   ├── vorschlag.py        # „Was kochen wir?"
│   ├── meta.py             # Kategorien, Tags, Statistiken
│   ├── system.py           # Health, Update, Update-/Fehlerlog
│   └── mcp_auth.py         # Login-Seite für die MCP-OAuth-Anmeldung
├── services/
│   ├── claude_service.py           # Prompts, Antwort-Parser, Metrik-Konvertierung
│   ├── image_service.py            # Bild-Download, Resize, Validierung
│   ├── structured_recipe_service.py# rezeptify-recipe/v1
│   ├── kochmodus_service.py        # Schritte/Timer aus der Zubereitung
│   ├── shopping_service.py         # Zutaten zusammenführen
│   ├── backup_service.py           # Backup vor Updates
│   └── update_service.py           # Fester Update-Ablauf
├── mcp_server/             # MCP-Server (lokal per stdio und remote unter /mcp)
├── tests/                  # pytest gegen echte MariaDB
└── static/                 # PWA: index.html, manifest, Service Worker, CSS, JS, Icons
    └── js/views/           # home, detail, form, import, bot, buch, kochmodus,
                            # einkauf, wochenplan, system, update-log, error-log
```

## Setup (Erstinstallation)

Voraussetzungen: Python 3.11, MariaDB, Anthropic API Key. Für den Betrieb auf CloudPanel siehe [`SETUP.md`](SETUP.md).

```bash
git clone https://github.com/BattloXX/rezeptify.git
cd rezeptify

cp config.example.py config.py
nano config.py            # DB-Zugang, API-Key, Passwort eintragen

python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

uvicorn app:app --host 127.0.0.1 --port 8000
```

Das Datenbankschema wird beim Start automatisch angelegt und bei Updates migriert.

## Konfiguration (`config.py`)

`config.py` liegt nicht in Git. Die vollständige, kommentierte Vorlage ist [`config.example.py`](config.example.py). Wichtige Werte:

| Wert | Bedeutung |
|------|-----------|
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | MariaDB-Zugang |
| `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` | KI-Import und Suchbot |
| `AUTH_ENABLED`, `AUTH_PASSWORD` | Passwortschutz von Website und REST-API (nur Passwort, kein Benutzername) |
| `MCP_API_TOKEN` | Statisches Bearer-Token für MCP-Clients und den internen Zugriff des MCP-Servers auf die REST-API |
| `MCP_LOGIN_PASSWORD` | Passwort der MCP-Login-Seite; leer = `AUTH_PASSWORD` |
| `PUBLIC_BASE_URL` | Öffentliche URL der Installation, z. B. `https://rezeptify.battlogg.at` (wird für OAuth-Adressen gebraucht) |
| `CORS_ORIGINS` | Erlaubte Origins, in Produktion die eigene Domain |
| `MAX_UPLOAD_MB`, `ALLOWED_IMAGES` | Upload-Limits |
| `UPDATE_GIT_REMOTE`, `UPDATE_GIT_BRANCH`, `BACKUP_DIR` | Browser-Update; `BACKUP_DIR` muss außerhalb von `static/` liegen |
| `DEBUG` | `True` aktiviert `/api/docs` |

## Zugangsschutz

| Bereich | Schutz |
|---------|--------|
| Website & REST-API (`/api/...`) | `AUTH_ENABLED=True` → Familienpasswort (Basic) oder `MCP_API_TOKEN` als Bearer. Bei `False` ist alles offen. |
| MCP (`/mcp`) | **Immer** geschützt, unabhängig von `AUTH_ENABLED`: OAuth-Login über `/mcp/login` oder statisches `MCP_API_TOKEN`. Ohne konfiguriertes Passwort/Token kommt niemand hinein. |

> ⚠️ Mit `AUTH_ENABLED=False` kann jeder mit Kenntnis der URL Rezepte lesen, ändern und löschen und KI-Endpunkte auslösen, die dein Anthropic-Guthaben verbrauchen.

## MCP-Server

Rezepte lassen sich aus einem KI-Chat heraus suchen, lesen, anlegen und ändern.
Tools: `search_recipes`, `get_recipe`, `add_recipe`, `update_recipe`,
`list_categories`, `list_tags`. Vor einer Änderung wird das Rezept mit
`get_recipe` gelesen; `update_recipe` ändert nur übergebene Felder und nutzt für
neue Rezepte denselben Validierungsweg wie der JSON-Import.

| Verbindung | Wie |
|------------|-----|
| **claude.ai / ChatGPT** | Custom Connector mit `https://<domain>/mcp` hinzufügen; beim ersten Zugriff öffnet sich die Rezeptify-Login-Seite (OAuth 2.1 mit PKCE und dynamischer Client-Registrierung) |
| **Claude Code** | Remote-Server mit `Authorization: Bearer <MCP_API_TOKEN>` |
| **Lokal (stdio)** | `python -m mcp_server.server` mit `REZEPTIFY_BASE_URL` und `REZEPTIFY_API_TOKEN` |

Details, Konfigurationsbeispiele und Hinweise stehen in [`mcp_server/README.md`](mcp_server/README.md).

**nginx/CloudPanel:** Die OAuth-Discovery unter `/.well-known/oauth-*` muss an die App durchgereicht werden (sonst antwortet nginx mit 404 und claude.ai meldet „Autorisierung fehlgeschlagen"). Außerdem sollte `/mcp` ohne Response-Puffer laufen (`proxy_buffering off`).

## API-Endpunkte

Alle Endpunkte außer den als „öffentlich" markierten unterliegen dem Zugangsschutz.

```
Rezepte
GET    /api/rezepte                       Liste + Suche + Filter + Sortierung
GET    /api/rezepte/vorschlag             „Was kochen wir?" – Vorschläge aus eigenen Rezepten
GET    /api/rezepte/slug/{slug}           Rezept per URL-Slug (Deep Links)
GET    /api/rezepte/{id}                  Einzelrezept
POST   /api/rezepte                       Erstellen
PUT    /api/rezepte/{id}                  Aktualisieren
DELETE /api/rezepte/{id}                  Löschen
PATCH  /api/rezepte/{id}/bewertung        Sterne setzen (1–5 oder null)
PATCH  /api/rezepte/{id}/favorit          Favorit setzen

Bilder
POST   /api/rezepte/{id}/bilder           Bild hochladen (auto-resize)
POST   /api/rezepte/{id}/bilder/attach    Bereits gespeichertes Bild zuweisen
POST   /api/bilder/from-url               Bild von URL laden
POST   /api/rezepte/{id}/fetch-bild       Internet-Bild automatisch suchen
PUT    /api/bilder/{id}/haupt             Als Hauptbild setzen
DELETE /api/bilder/{id}                   Bild löschen

KI & Import
POST   /api/analysiere-url                URL via Claude analysieren
POST   /api/analysiere-bild               Foto/Screenshot/PDF via Claude; .json deterministisch ohne KI
POST   /api/rezept-suche                  Rezepte im Internet suchen (Suchbot)

Kochmodus
GET    /api/rezepte/{id}/schritte         Schritte lesen
POST   /api/rezepte/{id}/schritte/auto    Schritte aus der Zubereitung erzeugen
PUT    /api/rezepte/{id}/schritte         Schritte speichern
POST   /api/rezepte/{id}/kochen           Als gekocht festhalten

Einkaufsliste
GET    /api/einkaufsliste                 Liste
POST   /api/einkaufsliste                 Eintrag hinzufügen
PATCH  /api/einkaufsliste/{id}            Eintrag ändern / abhaken
DELETE /api/einkaufsliste/{id}            Eintrag löschen
POST   /api/rezepte/{id}/zu-einkaufsliste Zutaten eines Rezepts hinzufügen
POST   /api/einkaufsliste/aufraeumen      Erledigte entfernen

Wochenplan
GET    /api/wochenplan                    Zeitraum lesen
POST   /api/wochenplan                    Rezept einplanen
PATCH  /api/wochenplan/{id}               Eintrag ändern
DELETE /api/wochenplan/{id}               Eintrag löschen
POST   /api/wochenplan/einkaufsliste      Einkaufsliste aus dem Plan erzeugen

Meta
GET    /api/kategorien                    Kategorieliste
GET    /api/tags                          Alle verwendeten Tags
GET    /api/stats                         Statistiken

System
GET    /api/health                        Status, Version, DB (öffentlich)
GET    /api/system/update-log             Update-Protokoll (öffentlich, bereinigt)
GET    /api/system/error-log              Fehlerprotokoll (öffentlich, bereinigt)
GET    /api/system/update-check           Neuere Version verfügbar?
POST   /api/system/update                 Update starten (Passwort-Bestätigung)
GET    /api/system/update-status/{id}     Status eines Updates
GET    /api/system/update-historie        Update-Historie

MCP / OAuth
       /mcp                               MCP (Streamable HTTP)
GET/POST /mcp/login                       Login-Seite der OAuth-Anmeldung
       /authorize, /token, /register, /revoke
       /.well-known/oauth-*               OAuth-Discovery
```

## Strukturierte Rezeptdateien (JSON)

Neben PDF und Bildern akzeptiert der Datei-Import UTF-8-kodierte `.json`-Dateien. Diese werden lokal validiert und nie an Claude gesendet. Das vollständige Feld- und Beispieldokument ist in der App über **Import → Rezept-JSON-Format ansehen** erreichbar.

```json
{
  "format": "rezeptify-recipe/v1",
  "title": "Tomatensuppe",
  "ingredients": [{"amount": 800, "unit": "g", "name": "Tomaten"}],
  "steps": ["Tomaten kochen.", "Pürieren."],
  "servings": 4,
  "tags": ["vegetarisch"]
}
```

Pflichtfelder sind `format`, `title` und eine nicht leere `steps`-Liste. Optional: `description`, `prep_minutes`, `cook_minutes`, `difficulty` (`leicht`/`mittel`/`schwer`), `category`, `source_url`, `calories_per_serving`, `image_url` (Bild, das ohne KI heruntergeladen wird) sowie pro Zutat `group`.

## Metrische Einheiten

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

## Update einspielen

**Im Browser:** Ansicht „System“ (Symbol in der Kopfzeile) → „Nach Update suchen“. Der Ablauf ist fest verdrahtet: Backup (DB + Uploads) → `git fetch/reset` auf `UPDATE_GIT_BRANCH` → `pip install -r requirements.txt` → DB-Migration → Neustart des Dienstes. Fortschritt und Fehler stehen im Update-Log.

**Manuell auf dem Server:**

```bash
cd /home/SITE-USER/htdocs/rezeptify.domain.de
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
# neue Felder aus config.example.py in config.py übernehmen
systemctl --user restart rezeptify
```

`config.py` wird nie überschrieben; neue Einstellungen müssen manuell ergänzt werden.

## Server-Verwaltung

```bash
systemctl --user restart rezeptify   # Neustarten
systemctl --user status rezeptify    # Status
journalctl --user -u rezeptify -f    # Logs live
```

Als root (z. B. wenn die User-Session keinen Bus hat):

```bash
systemctl --user -M SITE-USER@ restart rezeptify
```

## Releases

Jede Version hat einen Tag `vX.Y.Z` und ein GitHub-Release mit deutschen Release-Notes („Neu" / „Behoben"). Das Browser-Update orientiert sich am neuesten Release. Ablauf pro Änderung: Feature-Commit, danach ein eigener Commit `Bump version to X.Y.Z` (Datei `VERSION`), dann Tag und Release.

## Tests

Die Tests laufen gegen eine echte MariaDB (kein SQLite-Ersatz, wegen JSON/FULLTEXT/ENUM):

```bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit
```

Die MCP-Client-Tests ohne Datenbank laufen separat:

```bash
python3 -m venv .venv-mcp && source .venv-mcp/bin/activate
pip install -r mcp_server/requirements.txt
pytest mcp_server/tests -q
```

Es gibt keine CI für die Tests; sie werden lokal vor dem Merge ausgeführt.

## Kosten

| Aktion | Kosten |
|--------|--------|
| URL/Bild analysieren | ~$0.003 |
| KI-Suchbot | ~$0.01–0.02 |
| Prompt Caching | ~80 % günstiger bei Wiederholung |

## PWA installieren

**iOS (Safari):** Teilen ⎙ → „Zum Home-Bildschirm"  
**Android (Chrome):** Installations-Banner oder Menü → „App installieren"
