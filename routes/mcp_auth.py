"""Family-password login page for OAuth-authorizing the Rezeptify MCP server."""
import asyncio
import html
import secrets
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from mcp_server.oauth_provider import RezeptifyOAuthProvider

try:
    from config import AUTH_PASSWORD
except ImportError:
    AUTH_PASSWORD = ""
try:
    from config import MCP_LOGIN_PASSWORD
except ImportError:
    MCP_LOGIN_PASSWORD = ""


router = APIRouter()
_attempts: dict[str, deque[float]] = defaultdict(deque)


def _page(pending: str, error: bool = False) -> HTMLResponse:
    message = "<p class=\"error\">Anmeldung nicht möglich. Bitte erneut versuchen.</p>" if error else ""
    return HTMLResponse(f"""<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\">
    <title>Rezeptify verbinden</title><style>body{{font-family:system-ui;max-width:28rem;margin:4rem auto;padding:1rem}}
    input,button{{box-sizing:border-box;width:100%;padding:.7rem;margin:.4rem 0}}button{{background:#41734e;color:white;border:0}}
    .error{{color:#9b2226}}</style></head><body><h1>Rezeptify verbinden</h1>
    <p>Bitte gib das Familienpasswort ein, um den Rezeptify-MCP-Server zu verbinden.</p>{message}
    <form method=\"post\" action=\"/mcp/login\"><input type=\"hidden\" name=\"pending\" value=\"{html.escape(pending, quote=True)}\">
    <label>Passwort<input type=\"password\" name=\"password\" autocomplete=\"current-password\" required autofocus></label>
    <button type=\"submit\">Verbinden</button></form></body></html>""", headers={"Cache-Control": "no-store"})


def _provider() -> RezeptifyOAuthProvider:
    from mcp_server.server import get_production_oauth_provider
    return get_production_oauth_provider()


def _effective_password() -> str:
    """Prefer the MCP-specific password while retaining existing installations."""
    return MCP_LOGIN_PASSWORD or AUTH_PASSWORD


@router.get("/mcp/login", response_class=HTMLResponse)
async def login_page(pending: str = ""):
    if not pending or not await _provider().get_pending(pending):
        return HTMLResponse("Ungültige oder abgelaufene Anmeldung.", status_code=400)
    return _page(pending)


@router.post("/mcp/login", response_class=HTMLResponse)
async def login_submit(request: Request, pending: str = Form(""), password: str = Form("")):
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    attempts = _attempts[ip]
    while attempts and now - attempts[0] > 60:
        attempts.popleft()
    if len(attempts) >= 5:
        await asyncio.sleep(1)
        return _page(pending, error=True)
    effective_password = _effective_password()
    if (not effective_password
            or not secrets.compare_digest(password.encode(), effective_password.encode())):
        attempts.append(now)
        await asyncio.sleep(0.2)
        return _page(pending, error=True)
    redirect_url = await _provider().complete_login(pending)
    if not redirect_url:
        return HTMLResponse("Ungültige oder abgelaufene Anmeldung.", status_code=400)
    _attempts.pop(ip, None)
    return RedirectResponse(redirect_url, status_code=302, headers={"Cache-Control": "no-store"})
