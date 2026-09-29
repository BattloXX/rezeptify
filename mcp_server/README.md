# Rezeptify MCP-Server

Dieser eigenständige lokale MCP-Server erlaubt Claude Desktop oder Claude Code,
Rezepte in der privaten Rezeptify-Installation zu suchen und anzulegen. Er läuft
nicht auf dem Produktionsserver, sondern auf dem Rechner, auf dem Claude läuft.

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

Der Server bietet `search_recipes`, `list_categories`, `list_tags` und
`add_recipe`. Vor dem Anlegen soll Claude immer zuerst nach ähnlichen Rezepten
suchen, damit keine Duplikate entstehen.
