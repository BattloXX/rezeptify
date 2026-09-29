"""Simple password-based auth. Disable by setting AUTH_ENABLED=False in config.py."""
import secrets
from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

try:
    from config import AUTH_PASSWORD, AUTH_ENABLED
except ImportError:
    AUTH_PASSWORD = ""
    AUTH_ENABLED = False

try:
    from config import MCP_API_TOKEN
except ImportError:
    MCP_API_TOKEN = ""

security = HTTPBasic(auto_error=False)


def require_auth(request: Request, credentials: Optional[HTTPBasicCredentials] = Depends(security)):
    if not AUTH_ENABLED:
        return
    basic_ok = (
        credentials is not None
        and secrets.compare_digest(credentials.password.encode(), AUTH_PASSWORD.encode())
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
        headers={"WWW-Authenticate": 'Basic realm=""'},
    )
