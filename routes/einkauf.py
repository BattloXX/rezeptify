"""Authenticated shopping-list endpoints."""
import json
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException

from auth import require_auth
from db import get_db, parse_json_field
from services.shopping_service import merge_or_add, scale_amount, _decimal_amount

router = APIRouter(dependencies=[Depends(require_auth)])


def _serialize(row):
    row["menge"] = float(row["menge"]) if isinstance(row.get("menge"), Decimal) else row.get("menge")
    row["erledigt"] = bool(row.get("erledigt")); row["manuell"] = bool(row.get("manuell"))
    row["herkunft"] = parse_json_field(row.get("herkunft"))
    for field in ("erstellt_am", "geaendert_am"):
        if row.get(field) and not isinstance(row[field], str): row[field] = row[field].isoformat()
    return row


@router.get("/api/einkaufsliste")
def get_einkaufsliste():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM einkaufsliste_eintraege ORDER BY erledigt, sortierung IS NULL, sortierung, id")
            return {"eintraege": [_serialize(row) for row in cur.fetchall()]}


@router.post("/api/einkaufsliste", status_code=201)
def add_eintrag(body: dict):
    name = str(body.get("name") or "").strip()
    if not name: raise HTTPException(400, "Name fehlt")
    with get_db() as conn:
        with conn.cursor() as cur:
            rows = merge_or_add(cur, [{"name": name, "menge": body.get("menge"), "einheit": body.get("einheit"),
                                        "menge_text": body.get("menge_text"), "manuell": True}])
            return _serialize(rows[0])


@router.patch("/api/einkaufsliste/{eid}")
def update_eintrag(eid: int, body: dict):
    allowed = {"name", "menge", "einheit", "menge_text", "erledigt", "sortierung"}
    values = {key: value for key, value in body.items() if key in allowed}
    if not values: raise HTTPException(400, "Keine gültigen Felder")
    if "name" in values and not str(values["name"]).strip(): raise HTTPException(400, "Name fehlt")
    columns = ", ".join(f"{key}=%s" for key in values)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE einkaufsliste_eintraege SET {columns} WHERE id=%s", list(values.values()) + [eid])
            if not cur.rowcount: raise HTTPException(404, "Eintrag nicht gefunden")
            cur.execute("SELECT * FROM einkaufsliste_eintraege WHERE id=%s", (eid,))
            return _serialize(cur.fetchone())


@router.delete("/api/einkaufsliste/{eid}")
def delete_eintrag(eid: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM einkaufsliste_eintraege WHERE id=%s", (eid,))
            if not cur.rowcount: raise HTTPException(404, "Eintrag nicht gefunden")
    return {"ok": True}


@router.post("/api/rezepte/{rid}/zu-einkaufsliste")
def rezept_hinzufuegen(rid: int, body: dict):
    portionen = body.get("portionen")
    if not isinstance(portionen, (int, float)) or portionen <= 0: raise HTTPException(400, "Portionen müssen positiv sein")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, titel, portionen, zutaten FROM rezepte WHERE id=%s", (rid,))
            recipe = cur.fetchone()
            if not recipe: raise HTTPException(404, "Rezept nicht gefunden")
            factor = portionen / recipe["portionen"] if recipe["portionen"] else 1
            items = []
            for ingredient in parse_json_field(recipe["zutaten"]):
                if ingredient.get("gruppe") or not ingredient.get("name"): continue
                raw = ingredient.get("menge") or ""
                scaled = scale_amount(raw, ingredient.get("einheit"), factor)
                amount = _decimal_amount(scaled)
                items.append({"name": ingredient["name"], "menge": amount, "einheit": ingredient.get("einheit"),
                              "menge_text": None if amount is not None else (scaled or None),
                              "herkunft": [{"rezept_id": rid, "rezept_titel": recipe["titel"], "menge": scaled, "einheit": ingredient.get("einheit") or ""}]})
            return {"eintraege": [_serialize(row) for row in merge_or_add(cur, items)]}


@router.post("/api/einkaufsliste/aufraeumen")
def aufraeumen():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM einkaufsliste_eintraege WHERE erledigt=1")
            return {"geloescht": cur.rowcount}
