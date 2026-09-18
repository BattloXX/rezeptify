"""Rezeptify v2.0 — FastAPI entry point."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from config import BASE_DIR, UPLOAD_DIR, APP_TITLE, DEBUG
from db import get_db, init_db
from routes import rezepte, bilder, ai, meta, kochen, einkauf, planung, vorschlag, system

logger = logging.getLogger(__name__)


def _read_version() -> str:
    try:
        return (Path(BASE_DIR) / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


APP_VERSION = _read_version()

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Reaching startup after systemctl proves the requested restart completed.
    from db import get_db
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE system_updates SET status='abgeschlossen', beendet_am=NOW()
                WHERE status='neustart_ausgeloest'""")
    yield


app = FastAPI(
    title=APP_TITLE,
    docs_url="/api/docs" if DEBUG else None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Log unexpected errors without exposing their details to clients."""
    logger.exception("Unbehandelter Fehler bei %s %s", request.method, request.url.path)
    try:
        message = system._redact_secrets(str(exc)[:1000])
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO error_log (methode, pfad, exception_typ, nachricht)
                    VALUES (%s, %s, %s, %s)""", (
                    request.method[:10], request.url.path[:500],
                    type(exc).__name__[:255], message,
                ))
    except Exception:
        # A database outage must not prevent a safe error response.
        logger.exception("Fehler konnte nicht im error_log gespeichert werden")
    return JSONResponse(status_code=500, content={"detail": "Serverfehler, bitte erneut versuchen"})

try:
    from config import CORS_ORIGINS
except ImportError:
    CORS_ORIGINS = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(vorschlag.router)
app.include_router(rezepte.router)
app.include_router(bilder.router)
app.include_router(ai.router)
app.include_router(meta.router)
app.include_router(kochen.router)
app.include_router(einkauf.router)
app.include_router(planung.router)
app.include_router(system.public_router)
app.include_router(system.router)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/{full_path:path}")
def spa(full_path: str):
    return FileResponse(str(BASE_DIR / "static" / "index.html"))
