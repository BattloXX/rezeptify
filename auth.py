"""Simple password-based auth. Disable by setting AUTH_ENABLED=False in config.py."""
import base64
import binascii
import secrets
from typing import Optional
from fastapi import HTTPException, Request, status

try:
    from config import AUTH_PASSWORD, AUTH_ENABLED
except ImportError:
    AUTH_PASSWORD = ""
    AUTH_ENABLED = False

try:
    from config import MCP_API_TOKEN
except ImportError:
    MCP_API_TOKEN = ""

def _basic_password(request: Request) -> Optional[str]:
    """Return the Basic-auth password, or None for a missing/malformed header.

    FastAPI's HTTPBasic raises 401 with ``WWW-Authenticate: Basic`` for a
    malformed header even with auto_error=False. That popped up the browser's
    native login dialog, even when AUTH_ENABLED=False, for a stale stored header.
    """
    scheme, _, value = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "basic" or not value:
        return None
    try:
        decoded = base64.b64decode(value.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    _, sep, password = decoded.partition(":")
    return password if sep else None


def require_auth(request: Request):
    # Only the in-process MCP bridge can set this ASGI scope key; HTTP clients cannot.
    if request.scope.get("rezeptify_internal"):
        return
    if not AUTH_ENABLED:
        return
    password = _basic_password(request)
    basic_ok = (
        password is not None
        and secrets.compare_digest(password.encode(), AUTH_PASSWORD.encode())
    )
    if basic_ok:
        return

    authorization = request.headers.get("Authorization", "")
    if MCP_API_TOKEN and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):]
        if secrets.compare_digest(token.encode(), MCP_API_TOKEN.encode()):
            return

    # Return 401 without WWW-Authenticate so the browser doesn't show a native dialog.
    # The frontend handles the 401 by showing its own login screen.
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Nicht autorisiert",
    )
