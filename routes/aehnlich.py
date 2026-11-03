"""Authenticated, read-only duplicate candidate endpoints."""
from fastapi import APIRouter, Depends

from auth import require_auth
from db import get_db
from services.duplicate_service import find_duplicate_pairs, find_similar


router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/api/rezepte/aehnlich")
def get_aehnlich(titel: str = "", exclude_id: int | None = None):
    if not titel.strip():
        return {"treffer": []}
    with get_db() as conn:
        with conn.cursor() as cur:
            return {"treffer": find_similar(cur, titel, exclude_id)}


@router.get("/api/rezepte/duplikate")
def get_duplikate():
    with get_db() as conn:
        with conn.cursor() as cur:
            return {"paare": find_duplicate_pairs(cur)}
