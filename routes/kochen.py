"""Authenticated API endpoints for recipe cooking steps."""
import json
from fastapi import APIRouter, Depends, HTTPException, Query

from auth import require_auth
from db import get_db
from services.kochmodus_service import parse_zeit, split_zubereitung

router = APIRouter(dependencies=[Depends(require_auth)])


def _get_recipe(cur, rid: int) -> dict:
    cur.execute("SELECT id, zubereitung, schritte_quelle FROM rezepte WHERE id=%s", (rid,))
    recipe = cur.fetchone()
    if not recipe:
        raise HTTPException(404, "Rezept nicht gefunden")
    return recipe


def _read_steps(cur, rid: int) -> list[dict]:
    cur.execute("""
        SELECT id, position, text, zutaten_indices, timer_sekunden
        FROM rezept_schritte WHERE rezept_id=%s ORDER BY position
    """, (rid,))
    steps = cur.fetchall()
    for step in steps:
        raw = step.get("zutaten_indices")
        step["zutaten_indices"] = json.loads(raw) if isinstance(raw, str) else raw
    return steps


def _store_steps(cur, rid: int, texts: list[str], source: str) -> None:
    cur.execute("DELETE FROM rezept_schritte WHERE rezept_id=%s", (rid,))
    for position, text in enumerate(texts, start=1):
        cur.execute("""
            INSERT INTO rezept_schritte (rezept_id, position, text, timer_sekunden)
            VALUES (%s, %s, %s, %s)
        """, (rid, position, text, parse_zeit(text)))
    cur.execute("UPDATE rezepte SET schritte_quelle=%s WHERE id=%s", (source, rid))


@router.get("/api/rezepte/{rid}/schritte")
def get_schritte(rid: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            recipe = _get_recipe(cur, rid)
            if recipe["schritte_quelle"] == "keine":
                _store_steps(cur, rid, split_zubereitung(recipe["zubereitung"]), "auto")
            return {"schritte": _read_steps(cur, rid), "quelle": recipe["schritte_quelle"] if recipe["schritte_quelle"] != "keine" else "auto"}


@router.post("/api/rezepte/{rid}/schritte/auto")
def auto_schritte(rid: int, force: bool = Query(False)):
    with get_db() as conn:
        with conn.cursor() as cur:
            recipe = _get_recipe(cur, rid)
            if recipe["schritte_quelle"] == "manuell" and not force:
                raise HTTPException(409, "Manuelle Schritte werden nicht überschrieben")
            _store_steps(cur, rid, split_zubereitung(recipe["zubereitung"]), "auto")
            return {"schritte": _read_steps(cur, rid), "quelle": "auto"}


@router.put("/api/rezepte/{rid}/schritte")
def put_schritte(rid: int, body: dict):
    incoming = body.get("schritte")
    if not isinstance(incoming, list):
        raise HTTPException(400, "schritte muss eine Liste sein")
    texts = []
    for item in incoming:
        text = item.get("text") if isinstance(item, dict) else item
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(400, "Jeder Schritt braucht Text")
        texts.append(text.strip())
    with get_db() as conn:
        with conn.cursor() as cur:
            _get_recipe(cur, rid)
            _store_steps(cur, rid, texts, "manuell")
            return {"schritte": _read_steps(cur, rid), "quelle": "manuell"}


@router.post("/api/rezepte/{rid}/kochen", status_code=201)
def rezept_gekocht(rid: int, body: dict = None):
    body = body or {}
    portionen = body.get("portionen")
    notiz = body.get("notiz")
    bewertung = body.get("nachtraegliche_bewertung")
    if portionen is not None and (not isinstance(portionen, int) or isinstance(portionen, bool) or portionen < 1):
        raise HTTPException(400, "portionen muss eine positive Ganzzahl sein")
    if notiz is not None and not isinstance(notiz, str):
        raise HTTPException(400, "notiz muss Text sein")
    if bewertung is not None and (not isinstance(bewertung, int) or isinstance(bewertung, bool) or bewertung not in range(1, 6)):
        raise HTTPException(400, "nachtraegliche_bewertung muss zwischen 1 und 5 liegen")
    with get_db() as conn:
        with conn.cursor() as cur:
            _get_recipe(cur, rid)
            cur.execute("""INSERT INTO kochhistorie
                (rezept_id, portionen_verwendet, notiz, nachtraegliche_bewertung)
                VALUES (%s, %s, %s, %s)""", (rid, portionen, notiz, bewertung))
            history_id = cur.lastrowid
            cur.execute("SELECT gekocht_am FROM kochhistorie WHERE id=%s", (history_id,))
            gekocht_am = cur.fetchone()["gekocht_am"]
            cur.execute("SELECT COUNT(*) AS anzahl_gekocht, MAX(gekocht_am) AS zuletzt_gekocht FROM kochhistorie WHERE rezept_id=%s", (rid,))
            aggregate = cur.fetchone()
    return {"ok": True, "id": history_id, "gekocht_am": gekocht_am, **aggregate}
