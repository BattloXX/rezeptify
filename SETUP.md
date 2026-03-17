# 🌿 Rezeptify – Setup-Anleitung für CloudPanel

## Voraussetzungen
- CloudPanel mit Python 3.11 Unterstützung
- Anthropic API Key: https://console.anthropic.com/settings/keys

---

## Schritt 1: CloudPanel – Python-Site anlegen

1. CloudPanel öffnen → **+ Add Site**
2. **Site Type:** Python
3. **Domain:** deine-domain.de (oder Subdomain: rezeptify.deine-domain.de)
4. **Python Version:** 3.11
5. **App Port:** 8000 (oder was CloudPanel vorgibt)
6. Site erstellen → SSH-Zugangsdaten notieren

---

## Schritt 2: Dateien hochladen

Per **SFTP** (FileZilla, WinSCP etc.) oder SSH:

```bash
# Per SSH verbinden
ssh user@deine-domain.de

# In das App-Verzeichnis wechseln (CloudPanel Standard)
cd /home/SITE-USER/htdocs/deine-domain.de
# ODER: je nach CloudPanel-Konfiguration
cd ~/htdocs
```

Alle Dateien aus diesem ZIP-Paket in das App-Verzeichnis hochladen:
```
app.py
wsgi.py
requirements.txt
static/
  index.html
  manifest.json
  sw.js
  icons/
uploads/          ← wird automatisch erstellt
```

---

## Schritt 3: Virtuelle Umgebung & Pakete installieren

```bash
# Im App-Verzeichnis:
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Schritt 4: Umgebungsvariable setzen (API Key)

In CloudPanel unter **Site → Environment Variables** ODER:

```bash
# .env Datei anlegen (im App-Verzeichnis):
echo "ANTHROPIC_API_KEY=sk-ant-DEIN-KEY-HIER" > .env
```

Dann in `app.py` oben ergänzen (falls .env-Datei verwendet):
```python
# Ganz oben nach den imports ergänzen:
from dotenv import load_dotenv
load_dotenv()
```
Und `python-dotenv` in requirements.txt hinzufügen.

**Empfohlen: Direkt in CloudPanel als Environment Variable setzen**
(Site → Python App → Environment Variables → ANTHROPIC_API_KEY)

---

## Schritt 5: uWSGI / Startup konfigurieren

In CloudPanel unter **Python App Konfiguration**:

- **Entry point / Module:** `app:app`
- **WSGI-Datei:** `app.py`

Wenn CloudPanel nach einer `wsgi.py` fragt:
- **Module:** `wsgi:application`

### Alternativ: Startup Command mit Uvicorn
Falls CloudPanel einen Startbefehl erwartet:
```bash
/home/SITE-USER/htdocs/deine-domain.de/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --workers 2
```

---

## Schritt 6: Uploads-Ordner Berechtigungen

```bash
mkdir -p static/uploads
chmod 755 static/uploads
```

---

## Schritt 7: Testen

```bash
# Manuell starten zum Testen:
source venv/bin/activate
uvicorn app:app --host 127.0.0.1 --port 8000

# Im Browser: http://127.0.0.1:8000
```

---

## Wichtige Pfade

| Was | Wo |
|-----|----|
| Datenbank | `rezeptify.db` (im App-Verzeichnis, wird auto-erstellt) |
| Uploads | `static/uploads/` |
| Logs | CloudPanel → Site → Logs |

---

## PWA am Smartphone installieren

**iOS (Safari):** Teilen → "Zum Home-Bildschirm"
**Android (Chrome):** Menü → "App installieren"

---

## API Endpunkte (Übersicht)

```
GET    /api/rezepte              Liste + Suche + Filter
GET    /api/rezepte/{id}         Einzelrezept
POST   /api/rezepte              Erstellen
PUT    /api/rezepte/{id}         Aktualisieren
DELETE /api/rezepte/{id}         Löschen
POST   /api/rezepte/{id}/bilder  Bild hochladen
DELETE /api/bilder/{id}          Bild löschen
PUT    /api/bilder/{id}/haupt    Als Hauptbild setzen
POST   /api/analysiere-url       URL via Claude analysieren
POST   /api/analysiere-bild      Screenshot via Claude analysieren
GET    /api/kategorien           Kategorieliste
GET    /api/tags                 Alle verwendeten Tags
GET    /api/stats                Statistiken
```

---

## Backup

```bash
# Datenbank sichern:
cp rezeptify.db rezeptify_backup_$(date +%Y%m%d).db

# Uploads sichern:
tar -czf uploads_backup_$(date +%Y%m%d).tar.gz static/uploads/
```
