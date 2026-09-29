# Rezeptify MCP-Server

Der MCP-Server erlaubt Claude Desktop oder Claude Code, Rezepte in der privaten
Rezeptify-Installation zu suchen und anzulegen. Er kann lokal über stdio laufen
oder als Remote-Server unter `/mcp` der Rezeptify-Installation angesprochen werden.

## Installation

```bash
cd /pfad/zu/rezeptify
python3 -m venv .venv-mcp
source .venv-mcp/bin/activate
pip install -r mcp_server/requirements.txt
```

## Bearer-Token einrichten

Auf dem Produktionsserver ein separates Token erzeugen:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Den erzeugten Wert in der dortigen `config.py` ergänzen (nicht in Git einchecken):

```python
MCP_API_TOKEN = "hier-das-erzeugte-token-eintragen"
```

Danach die Anwendung neu starten:

```bash
systemctl --user restart rezeptify
```

## Claude Desktop / Claude Code konfigurieren

Den folgenden Eintrag in die MCP-Konfiguration einfügen. `command` muss auf den
Python-Interpreter des oben angelegten venv zeigen, `cwd` auf den lokalen Checkout
dieses Repositories.

```json
{
  "mcpServers": {
    "rezeptify": {
      "command": "/pfad/zu/rezeptify/.venv-mcp/bin/python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/pfad/zu/rezeptify",
      "env": {
        "REZEPTIFY_BASE_URL": "https://rezeptify.battlogg.at",
        "REZEPTIFY_API_TOKEN": "HIER_DAS_MCP_API_TOKEN_EINTRAGEN"
      }
    }
  }
}
```

Der Server bietet `search_recipes`, `get_recipe`, `add_recipe`, `update_recipe`,
`list_categories` und `list_tags`. Vor dem Anlegen oder Ändern soll Claude immer
zuerst nach ähnlichen Rezepten suchen. Vor `update_recipe` muss Claude
`get_recipe` aufrufen und nur die zu ändernden Felder übergeben; leere Zutaten-
oder Tag-Listen löschen diese gezielt.

MCP ist immer geschützt, auch wenn die Website und REST-API mit
`AUTH_ENABLED=False` öffentlich betrieben werden. Ein statisches Token ist nur
für MCP gültig; für OAuth wird `MCP_LOGIN_PASSWORD` verwendet, falls gesetzt,
sonst `AUTH_PASSWORD`.

## Remote-Verbindung

Die laufende Rezeptify-Installation stellt den Streamable-HTTP-Endpunkt unter
`https://rezeptify.battlogg.at/mcp` bereit. Für Claude Code kann derselbe
Remote-Server per JSON-Konfiguration eingebunden werden; das Token bleibt dabei
in einer Umgebungsvariable:

```json
{
  "mcpServers": {
    "rezeptify-remote": {
      "type": "http",
      "url": "https://rezeptify.battlogg.at/mcp",
      "headers": {
        "Authorization": "Bearer ${REZEPTIFY_MCP_API_TOKEN}"
      }
    }
  }
}
```

Alternativ erzeugt Claude Code denselben Eintrag über die Kommandozeile:

```bash
claude mcp add --transport http rezeptify-remote https://rezeptify.battlogg.at/mcp \
  --header "Authorization: Bearer $REZEPTIFY_MCP_API_TOKEN"
```

Für einen Remote-Connector in Claude Desktop oder claude.ai wird unter
**Customize → Connectors → Add custom connector** nur die MCP-URL eingetragen.
Beim anschließenden **Connect** läuft die OAuth-Anmeldung über die Rezeptify-
Loginseite; ein Bearer-Token wird dort nicht manuell eingegeben. Die obige
Header-Konfiguration ist für Claude Code gedacht. [Claude dokumentiert den
OAuth-Connect-Ablauf für Remote-Connectoren](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).

## claude.ai / ChatGPT verbinden

Für die Web-Connectoren von claude.ai und ChatGPT wird kein Token manuell
eingetragen. Stattdessen die MCP-URL `https://rezeptify.battlogg.at/mcp` als
Custom Connector/App hinzufügen. Beim ersten Zugriff erscheint die Rezeptify-
Loginseite; dort wird das bestehende Familienpasswort eingegeben. Danach erhält
der Connector ein eigenes OAuth-Token mit PKCE und kann Rezepte abrufen oder
anlegen. Die Verbindung kann jederzeit in den Connector-Einstellungen getrennt
werden.

Wenn `AUTH_ENABLED=True` und `MCP_API_TOKEN` leer ist, kann der MCP-Server zwar
authentifizieren, seine Tools können die REST-API aber nicht aufrufen und
liefern einen klaren API-Fehler. Daher bei aktivierter REST-Auth immer auch ein
`MCP_API_TOKEN` setzen.
