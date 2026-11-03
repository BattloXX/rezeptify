# Repository guidance

## Commands
```bash
cp config.example.py config.py
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
# Full container suite / one test file:
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from app
docker compose -f docker-compose.test.yml run --rm app pytest -q tests/test_x.py
# Production (systemd user service):
systemctl --user restart rezeptify
journalctl --user -u rezeptify -f
journalctl --user -u rezeptify | grep "MCP "
```
`wsgi:application` is also an ASGI callable; run it with uvicorn or an ASGI-capable server mode, never as WSGI.

## Configuration
`config.py` is untracked; copy `config.example.py` and fill in local values. Never commit secrets.
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_CHARSET`: MariaDB connection settings.
- `ANTHROPIC_API_KEY`: Claude imports and recipe search.
- `AUTH_ENABLED`: enables website/REST authentication.
- `AUTH_PASSWORD`: shared website password and fallback for MCP login/admin updates.
- `ADMIN_PASSWORD`: browser-update confirmation; empty falls back to `AUTH_PASSWORD`.
- `MCP_API_TOKEN`: static bearer token for MCP (also accepted by protected REST routes).
- `MCP_LOGIN_PASSWORD`: OAuth login password; empty falls back to `AUTH_PASSWORD`.
- `PUBLIC_BASE_URL`: public installation URL used for OAuth and recipe links.
- `CORS_ORIGINS`: allowed browser origins; use the installation's own origin in production.
- `KI_LIMIT_PRO_IP_STUNDE`: AI calls per IP/hour; default 30, zero means unlimited.
- `KI_LIMIT_GESAMT_TAG`: AI calls across all IPs over 24 hours; default 300, zero means unlimited.

## Architecture
- `app.py`: FastAPI wiring, CORS, router order, MCP mount/lifespan, static files, SPA catch-all.
- `routes/rezepte.py`: recipe CRUD, search, ratings, favorites; `aehnlich.py`: similar titles/duplicates.
- `routes/bilder.py`, `ai.py`, `meta.py`: images, AI/JSON imports/search, categories/tags/statistics.
- `routes/kochen.py`, `einkauf.py`, `planung.py`, `vorschlag.py`: cooking, shopping, planning, suggestions.
- `routes/mcp_auth.py`: OAuth login page and in-memory login throttling; `system.py`: health/updates/logs.
- `services/claude_service.py`, `image_service.py`: Claude prompts/parsing and image processing.
- `services/http_guard.py`: SSRF checks for server-side HTTP downloads, including redirects and size limits.
- `services/rate_limit.py`: database-backed AI quotas in `ki_nutzung`, shared across workers.
- `services/duplicate_service.py`, `structured_recipe_service.py`: title similarity and deterministic recipe JSON validation.
- `services/kochmodus_service.py`, `shopping_service.py`: cooking steps/timers and ingredient merging.
- `services/update_service.py`, `backup_service.py`: fixed update workflow and private DB/config/upload backups.
- `request_utils.py`: `client_ip()` trusts forwarded headers only from `TRUSTED_PROXIES` (loopback by default).
- `auth.py`: REST Basic/bearer authentication and internal bridge scope check.
- `db.py`: raw PyMySQL, JSON helpers, schema plus idempotent `init_db()` migrations/backfills, `suchtext` builder.
- `mcp_server/server.py`: stdio/Streamable HTTP tools, OAuth routes, protected MCP lifespan.
- `mcp_server/client.py`: REST bridge; `oauth_provider.py`: database-backed OAuth; `auth.py`: static bearer verifier.
- Frontend: vanilla ES modules in `static/js/` and `views/`, with `static/index.html` as the single page.
- `static/sw.js`: network-first for page navigation and assets; API/uploads are never cached.
  Increment the cache name when changing the application shell.

## Authentication and operations
- With `AUTH_ENABLED=False`, website/REST need no login; frontend reads `/api/config`.
- `/mcp` is always protected: OAuth 2.1 or static `MCP_API_TOKEN`, independent of public website mode.
- The in-process MCP → REST bridge sets the ASGI scope flag `rezeptify_internal`; HTTP headers cannot set it.
- Browser updates require `ADMIN_PASSWORD` or fallback `AUTH_PASSWORD`; disabled if both are empty.
- MCP uses `stateless_http=True` and supports multiple workers; login throttle memory is per worker.
- nginx must forward OAuth discovery/endpoints and `/mcp`, preserve client IP headers, and disable MCP buffering (see `SETUP.md`).
- `/api/health` is public: version, database, mcp, status, schema_version; failures report degraded with HTTP 200.

## Key patterns
- Generate recipe slugs with `slug_utils.make_slug()` (normalized title plus recipe ID).
- Serialize JSON columns on writes and parse them on reads with DB helpers (`zutaten`, `tags`, etc.).
- Maintain `suchtext` on every write path changing title, description, category, tags or ingredients; use `build_suchtext()`.
- Search combines escaped `LIKE` predicates with AND for every token, including ingredient/tag text.
- Escape every dynamic string inserted into HTML with `x()`; convert IDs with `Number()`.
  Keep user data out of inline handlers: use escaped `data-*` attributes and event delegation.
  Validate links/images with `safeUrl()`/`safeImageUrl()` before escaping them into HTML.
- Register `aehnlich` before `rezepte`: its literal paths must precede `/{rid}` (Python `rid: int`, not a path converter).
- Use UTC for DB timestamps (`UTC_TIMESTAMP()` for SQL time calculations, as in quotas/OAuth).
- Keep schema migrations idempotent inside `init_db()`.

## Releases and testing
- Increment `VERSION` using SemVer, squash-merge the PR, then create GitHub Release `vX.Y.Z`.
  Browser update discovery reads GitHub `releases/latest`; a tag alone is insufficient.
- Tests use real MariaDB in `docker-compose.test.yml`, never SQLite.
- The `client` fixture in `tests/conftest.py` starts the lifespan and clears tables; add new tables to its cleanup.
- `mcp_server/tests` need `pytest-asyncio`, see `requirements-dev.txt`.
