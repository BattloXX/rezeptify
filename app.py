"""Rezeptify v2.0 — FastAPI entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config import BASE_DIR, UPLOAD_DIR, APP_TITLE, DEBUG
from db import init_db
from routes import rezepte, bilder, ai, meta

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=APP_TITLE,
    docs_url="/api/docs" if DEBUG else None,
    redoc_url=None,
    lifespan=lifespan,
)

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

app.include_router(rezepte.router)
app.include_router(bilder.router)
app.include_router(ai.router)
app.include_router(meta.router)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/{full_path:path}")
def spa(full_path: str):
    return FileResponse(str(BASE_DIR / "static" / "index.html"))
