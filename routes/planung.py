"""Authenticated weekly meal-plan endpoints."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from auth import require_auth
from db import get_db, get_bilder_batch
from services.shopping_service import merge_or_add, zutaten_fuer_einkauf

router = APIRouter(dependencies=[Depends(require_auth)])
_MEALS = {"fruehstueck", "mittag", "abend", "snack"}


def _range(von, bis, max_days=31):
    try:
        start, end = date.fromisoformat(str(von)), date.fromisoformat(str(bis))
    except (TypeError, ValueError):
        raise HTTPException(400, "Ungültiger Datumsbereich")
    if end < start or (end - start).days + 1 > max_days:
        raise HTTPException(400, "Datumsbereich muss zwischen 1 und 31 Tagen liegen")
    return start, end


def _serialize(row, bilder):
    row["datum"] = row["datum"].isoformat()
    if row.get("erstellt_am") and not isinstance(row["erstellt_am"], str):
        row["erstellt_am"] = row["erstellt_am"].isoformat()
    row["haupt_bild"] = next((b["url"] for b in bilder.get(row["rezept_id"], []) if b["ist_haupt"]), None)
    return row


@router.get("/api/wochenplan")
def get_wochenplan(von: str, bis: str):
    start, end = _range(von, bis)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT w.*, r.titel FROM wochenplan w
                JOIN rezepte r ON r.id=w.rezept_id WHERE w.datum BETWEEN %s AND %s
                ORDER BY w.datum, FIELD(w.mahlzeit,'fruehstueck','mittag','abend','snack'), w.id""", (start, end))
            rows = cur.fetchall()
            bilder = get_bilder_batch(cur, [r["rezept_id"] for r in rows])
            return {"eintraege": [_serialize(row, bilder) for row in rows]}


@router.post("/api/wochenplan", status_code=201)
def add_wochenplan(body: dict):
    rid, meal = body.get("rezept_id"), body.get("mahlzeit", "abend")
    try: planned = date.fromisoformat(str(body.get("datum")))
    except (TypeError, ValueError): raise HTTPException(400, "Ungültiges Datum")
    if not isinstance(rid, int) or rid <= 0: raise HTTPException(400, "Rezept fehlt")
    if meal not in _MEALS: raise HTTPException(400, "Ungültige Mahlzeit")
    portions = body.get("portionen")
    if portions is not None and (not isinstance(portions, int) or portions <= 0): raise HTTPException(400, "Portionen müssen positiv sein")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM rezepte WHERE id=%s", (rid,))
            if not cur.fetchone(): raise HTTPException(404, "Rezept nicht gefunden")
            cur.execute("INSERT INTO wochenplan (rezept_id, datum, mahlzeit, portionen) VALUES (%s,%s,%s,%s)", (rid, planned, meal, portions))
            return {"id": cur.lastrowid, "rezept_id": rid, "datum": planned.isoformat(), "mahlzeit": meal, "portionen": portions}


@router.patch("/api/wochenplan/{eid}")
def update_wochenplan(eid: int, body: dict):
    values = {}
    if "datum" in body:
        try: values["datum"] = date.fromisoformat(str(body["datum"]))
        except (TypeError, ValueError): raise HTTPException(400, "Ungültiges Datum")
    if "mahlzeit" in body:
        if body["mahlzeit"] not in _MEALS: raise HTTPException(400, "Ungültige Mahlzeit")
        values["mahlzeit"] = body["mahlzeit"]
    if "portionen" in body:
        if body["portionen"] is not None and (not isinstance(body["portionen"], int) or body["portionen"] <= 0): raise HTTPException(400, "Portionen müssen positiv sein")
        values["portionen"] = body["portionen"]
    if not values: raise HTTPException(400, "Keine gültigen Felder")
    with get_db() as conn:
        with conn.cursor() as cur:
            columns = ", ".join(f"{key}=%s" for key in values)
            cur.execute(f"UPDATE wochenplan SET {columns} WHERE id=%s", [*values.values(), eid])
            if not cur.rowcount: raise HTTPException(404, "Eintrag nicht gefunden")
            cur.execute("SELECT * FROM wochenplan WHERE id=%s", (eid,)); row = cur.fetchone(); row["datum"] = row["datum"].isoformat()
            return row


@router.delete("/api/wochenplan/{eid}")
def delete_wochenplan(eid: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM wochenplan WHERE id=%s", (eid,))
            if not cur.rowcount: raise HTTPException(404, "Eintrag nicht gefunden")
    return {"ok": True}


@router.post("/api/wochenplan/einkaufsliste")
def wochenplan_einkaufsliste(body: dict):
    start, end = _range(body.get("von"), body.get("bis"))
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT w.rezept_id, w.portionen AS plan_portionen, r.id, r.titel, r.portionen, r.zutaten
                FROM wochenplan w JOIN rezepte r ON r.id=w.rezept_id WHERE w.datum BETWEEN %s AND %s""", (start, end))
            items = []
            for recipe in cur.fetchall():
                items.extend(zutaten_fuer_einkauf(recipe, recipe["plan_portionen"] or recipe["portionen"] or 1))
            changed = merge_or_add(cur, items)
    return {"anzahl": len(changed)}
