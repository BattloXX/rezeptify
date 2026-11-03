# 🌿 Rezeptify – Setup-Anleitung für CloudPanel

## Voraussetzungen
- CloudPanel mit Python 3.11 Unterstützung und MariaDB
- `mysqldump` für die Sicherung vor Browser-Updates
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

Das vollständige Repository bereitstellen (einschließlich `routes/`, `services/`, `mcp_server/`, `static/`, `db.py` und `VERSION`), z. B. per Git-Checkout. Uploads liegen in `static/uploads/` und werden automatisch angelegt. Für Browser-Updates muss die Installation ein Git-Checkout mit konfiguriertem Remote sein.

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

## Schritt 4: Konfiguration

```bash
cp config.example.py config.py
nano config.py
```

In der ungetrackten `config.py` die MariaDB-Verbindung (`DB_*`), `ANTHROPIC_API_KEY`, Auth-Passwörter und `PUBLIC_BASE_URL` eintragen. `CORS_ORIGINS` auf die eigene öffentliche Origin setzen. MariaDB-Datenbank und Benutzer müssen vorhanden sein; `init_db()` legt beim Start Tabellen an und migriert sie. Alle Schlüssel stehen in `config.example.py`.

---

## Schritt 5: ASGI-Startup konfigurieren

FastAPI benötigt einen ASGI-Server. CloudPanel muss den lokalen App-Port über nginx an diesen Prozess weiterleiten. Startbefehl (z. B. im systemd User Service `rezeptify`):

```bash
/home/SITE-USER/htdocs/deine-domain.de/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --workers 2
```

Alternativ ist `wsgi:application` derselbe ASGI-Callable: mit uvicorn oder im uWSGI-ASGI-Modus starten, **nicht als WSGI**. Eine CloudPanel-Einstellung für reine WSGI-Anwendungen reicht dafür nicht.

`uvicorn --workers 2` ist möglich: MCP nutzt `stateless_http=True` und braucht keine Sitzung im Worker. Die MCP-Login-Sperre zählt im Speicher pro Worker (effektiv Limit × Worker); das KI-Limit zählt in der Datenbank und gilt gemeinsam für alle Worker.

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
| Datenbank | MariaDB gemäß `DB_*` in `config.py`; Tabellen werden beim Start angelegt/migriert |
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
# MariaDB sichern (Werte aus config.py einsetzen; -p fragt das Passwort ab):
mysqldump --host=localhost --port=3306 --user=rezeptify -p --single-transaction rezeptify > rezeptify_backup.sql

# Uploads sichern:
tar -czf uploads_backup_$(date +%Y%m%d).tar.gz static/uploads/
```


## Reverse Proxy (nginx/CloudPanel)

Alle App-Pfade müssen am lokalen ASGI-Port ankommen. OAuth registriert am Domain-Root `/.well-known/oauth-authorization-server`, `/.well-known/oauth-protected-resource/mcp` sowie `/authorize`, `/token`, `/register` und `/revoke`. Auch `/mcp` und `/mcp/login` müssen weitergereicht werden. Eine CloudPanel-Regel, die `/.well-known/` selbst beantwortet, verhindert die OAuth-Anmeldung.

Beispiel für den CloudPanel-Vhost (innerhalb des bestehenden `server`-Blocks; vorhandene Locations zusammenführen/ersetzen, Port gegebenenfalls anpassen). Eine benötigte ACME-Challenge-Location beibehalten; sie darf die OAuth-Discovery nicht abfangen:

```nginx
client_max_body_size 12m;

location ^~ /.well-known/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Host $host;
}

location ^~ /mcp {
    proxy_pass http://127.0.0.1:8000;
    proxy_buffering off;
    proxy_read_timeout 300s;
    proxy_http_version 1.1;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Host $host;
}

# Schließt /authorize, /token, /register, /revoke und /api/health ein.
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Host $host;
}
```

`request_utils.TRUSTED_PROXIES` vertraut standardmäßig nur `127.0.0.1` und `::1`. `X-Real-IP` muss die tatsächliche Client-IP enthalten. Fehlen nutzbare IP-Header, sehen Login-Sperre und KI-Limit bei lokalem Proxy alle Nutzer als `127.0.0.1`; ohne `X-Real-IP` wird ersatzweise der letzte Eintrag aus `X-Forwarded-For` verwendet. Bei einem anderen Proxy-Absender muss die Vertrauensliste zur Installation passen.

`client_max_body_size 12m;` erlaubt `MAX_UPLOAD_MB=10` plus Multipart-Overhead. Ein kleineres nginx-Limit kann Uploads bereits mit HTTP 413 abweisen, bevor die App sie erhält; die Fehlermeldung im Frontend verweist darauf.

Für Monitoring und nach jedem Update/Neustart `GET /api/health` prüfen: `version`, `database`, `mcp`, `status`, `schema_version`. Nur wenn Datenbank und MCP bereit sind, ist `status` gleich `ok`, sonst `degraded`. HTTP bleibt auch bei `degraded` auf 200; Monitoring muss das JSON auswerten.

```bash
systemctl --user restart rezeptify
journalctl --user -u rezeptify -f
journalctl --user -u rezeptify | grep "MCP "
curl -sS https://deine-domain.de/api/health
```

| Problem | Prüfen |
|---------|--------|
| MCP 401 | Token, `MCP_LOGIN_PASSWORD` (Fallback `AUTH_PASSWORD`) und `PUBLIC_BASE_URL` prüfen. `journalctl --user -u rezeptify \| grep "MCP "` zeigt jede abgelehnte Anfrage am MCP-Endpunkt mit Status und `auth=none` oder `auth=bearer`. |
| „Autorisierung fehlgeschlagen“ in claude.ai | Wird `/.well-known/` an die App durchgereicht? Discovery muss JSON liefern. |
| Browser-Update deaktiviert | `ADMIN_PASSWORD` fehlt und `AUTH_PASSWORD` ist ebenfalls leer. |
| 429 bei KI | `KI_LIMIT_PRO_IP_STUNDE` / `KI_LIMIT_GESAMT_TAG` erreicht; auf Ablauf des Zeitfensters warten oder Limits in `config.py` anpassen. |
