"""Authenticated shopping-list endpoints."""
import time
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException

from auth import require_auth
from db import get_db, parse_json_field
from services.einkauf_sync import (
    ListeNichtGefunden, aenderungen_seit, apply_ops, parse_hlc, rang_zwischen,
    server_hlc, server_op, standard_liste,
)
from services.shopping_service import merge_or_add, zutaten_fuer_einkauf

router = APIRouter(dependencies=[Depends(require_auth)])


def _serialize(row):
    row["menge"] = float(row["menge"]) if isinstance(row.get("menge"), Decimal) else row.get("menge")
    row["erledigt"] = bool(row.get("erledigt")); row["manuell"] = bool(row.get("manuell"))
    row["herkunft"] = parse_json_field(row.get("herkunft"))
    for field in ("erstellt_am", "geaendert_am"):
        if row.get(field) and not isinstance(row[field], str): row[field] = row[field].isoformat()
    return row


def _listen(cur):
    cur.execute("SELECT uuid, name, ist_standard FROM einkaufslisten WHERE archiviert=0 ORDER BY erstellt_am, uuid")
    return [{**row, "ist_standard": bool(row["ist_standard"])} for row in cur.fetchall()]


@router.get("/api/einkauf/listen")
def get_listen():
    with get_db() as conn:
        with conn.cursor() as cur:
            standard_liste(cur)
            return {"listen": _listen(cur)}


@router.post("/api/einkauf/sync")
def sync_einkauf(body: dict):
    seit, ops = body.get("seit"), body.get("ops", [])
    if type(seit) is not int or seit < 0:
        raise HTTPException(400, "Seit muss eine nicht negative ganze Zahl sein")
    if not isinstance(ops, list):
        raise HTTPException(400, "Ops muss eine Liste sein")
    if len(ops) > 500:
        raise HTTPException(413, "Höchstens 500 Operationen pro Anfrage erlaubt")
    seen = body.get("hlc")
    try:
        if parse_hlc(seen)[0] > int(time.time() * 1000) + 86400000:
            seen = None
    except ValueError:
        seen = None
    with get_db() as conn:
        with conn.cursor() as cur:
            liste = body.get("liste")
            if liste is None:
                liste = standard_liste(cur)
            if not isinstance(liste, str):
                raise HTTPException(404, "Liste nicht gefunden")
            try:
                results = apply_ops(cur, liste, ops)["ergebnisse"] if ops else []
                changes = aenderungen_seit(cur, liste, seit)
            except ListeNichtGefunden:
                raise HTTPException(404, "Liste nicht gefunden")
            return {"liste": liste, **changes, "hlc": server_hlc(seen),
                    "ergebnisse": results, "listen": _listen(cur)}


@router.get("/api/einkaufsliste")
def get_einkaufsliste():
    with get_db() as conn:
        with conn.cursor() as cur:
            liste = standard_liste(cur)
            cur.execute("""SELECT * FROM einkaufsliste_eintraege WHERE liste_uuid=%s AND geloescht_am IS NULL
                ORDER BY erledigt, BINARY rang, id""", (liste,))
            return {"eintraege": [_serialize(row) for row in cur.fetchall()]}


@router.post("/api/einkaufsliste", status_code=201)
def add_eintrag(body: dict):
    name = str(body.get("name") or "").strip()
    if not name: raise HTTPException(400, "Name fehlt")
    with get_db() as conn:
        with conn.cursor() as cur:
            try:
                rows = merge_or_add(cur, [{"name": name, "menge": body.get("menge"), "einheit": body.get("einheit"),
                                            "menge_text": body.get("menge_text"), "manuell": True}])
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            return _serialize(rows[0])


def _existing(cur, eid):
    liste = standard_liste(cur)
    cur.execute("SELECT seq FROM einkaufslisten WHERE uuid=%s FOR UPDATE", (liste,))
    cur.fetchone()
    cur.execute("""SELECT * FROM einkaufsliste_eintraege
        WHERE id=%s AND liste_uuid=%s AND geloescht_am IS NULL FOR UPDATE""", (eid, liste))
    row = cur.fetchone()
    if not row: raise HTTPException(404, "Eintrag nicht gefunden")
    server_hlc(max(row[key] for key in ("hlc_inhalt", "hlc_menge", "hlc_status", "hlc_position")))
    return liste, row


@router.patch("/api/einkaufsliste/{eid}")
def update_eintrag(eid: int, body: dict):
    allowed = {"name", "menge", "einheit", "menge_text", "erledigt", "sortierung"}
    values = {key: value for key, value in body.items() if key in allowed}
    if not values: raise HTTPException(400, "Keine gültigen Felder")
    if "name" in values and not str(values["name"]).strip(): raise HTTPException(400, "Name fehlt")
    with get_db() as conn:
        with conn.cursor() as cur:
            liste, row = _existing(cur, eid)
            ops = []
            if "name" in values:
                ops.append(server_op("inhalt_setzen", row["uuid"], {"name": values["name"]}))
            if any(key in values for key in ("menge", "einheit", "menge_text")):
                ops.append(server_op("menge_setzen", row["uuid"],
                                     {key: values.get(key, row[key]) for key in ("menge", "einheit", "menge_text")}))
            if "erledigt" in values:
                ops.append(server_op("status_setzen", row["uuid"], {"erledigt": bool(values["erledigt"])}))
            if "sortierung" in values:
                position = values["sortierung"]
                if position is not None and type(position) is not int:
                    raise HTTPException(400, "Sortierung muss eine ganze Zahl sein")
                cur.execute("""SELECT rang FROM einkaufsliste_eintraege
                    WHERE liste_uuid=%s AND geloescht_am IS NULL AND id<>%s ORDER BY BINARY rang, id FOR UPDATE""", (liste, eid))
                ranks = [entry["rang"] for entry in cur.fetchall()]
                index = min(max(position, 0), len(ranks)) if position is not None else len(ranks)
                rank = rang_zwischen(ranks[index - 1] if index else None, ranks[index] if index < len(ranks) else None)
                ops.append(server_op("verschieben", row["uuid"], {"rang": rank}))
            result = apply_ops(cur, liste, ops)
            if any(item["ergebnis"] == "abgelehnt" for item in result["ergebnisse"]):
                raise HTTPException(400, "Ungültige Eintragsdaten")
            if "sortierung" in values:
                cur.execute("UPDATE einkaufsliste_eintraege SET sortierung=%s WHERE id=%s", (values["sortierung"], eid))
            cur.execute("SELECT * FROM einkaufsliste_eintraege WHERE id=%s", (eid,))
            return _serialize(cur.fetchone())


@router.delete("/api/einkaufsliste/{eid}")
def delete_eintrag(eid: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            liste, row = _existing(cur, eid)
            apply_ops(cur, liste, [server_op("loeschen", row["uuid"], {})])
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
            return {"eintraege": [_serialize(row) for row in merge_or_add(cur, zutaten_fuer_einkauf(recipe, portionen))]}


@router.post("/api/einkaufsliste/aufraeumen")
def aufraeumen():
    with get_db() as conn:
        with conn.cursor() as cur:
            liste = standard_liste(cur)
            cur.execute("SELECT seq FROM einkaufslisten WHERE uuid=%s FOR UPDATE", (liste,))
            before = cur.fetchone()["seq"]
            cur.execute("""SELECT uuid, hlc_status FROM einkaufsliste_eintraege
                WHERE liste_uuid=%s AND erledigt=1 AND geloescht_am IS NULL FOR UPDATE""", (liste,))
            entries = list(cur.fetchall())
            for start in range(0, len(entries), 500):
                apply_ops(cur, liste, [server_op("erledigte_loeschen", None, {"eintraege": entries[start:start + 500]})])
            cur.execute("SELECT seq FROM einkaufslisten WHERE uuid=%s", (liste,))
            return {"geloescht": cur.fetchone()["seq"] - before}
