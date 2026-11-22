"""Authenticated shopping-list endpoints."""
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException

from auth import require_auth
from db import get_db, parse_json_field
from services.einkauf_sync import (
    ListeNichtGefunden, _entry, aenderungen_seit, apply_ops, parse_hlc, rang_initial, rang_zwischen,
    server_hlc, server_op, standard_liste,
)
from services.shopping_service import merge_or_add, zutaten_fuer_einkauf
from services.mengen_parser import parse_eintrag, split_mehrfach

router = APIRouter(dependencies=[Depends(require_auth)])


def _serialize(row):
    row["menge"] = float(row["menge"]) if isinstance(row.get("menge"), Decimal) else row.get("menge")
    row["erledigt"] = bool(row.get("erledigt")); row["manuell"] = bool(row.get("manuell"))
    row["herkunft"] = parse_json_field(row.get("herkunft"))
    for field in ("erstellt_am", "geaendert_am"):
        if row.get(field) and not isinstance(row[field], str): row[field] = row[field].isoformat()
    return row


def _listen(cur):
    cur.execute("SELECT uuid, name, ist_standard, laden_id FROM einkaufslisten WHERE archiviert=0 ORDER BY erstellt_am, uuid")
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
            vorrat = []
            items = zutaten_fuer_einkauf(recipe, portionen, cur, vorrat)
            liste = _uuid_liste(cur, body.get("liste"))
            return {"eintraege": [_serialize(row) for row in merge_or_add(cur, items, liste)], "vorrat": vorrat}


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


def _uuid_liste(cur, liste):
    if liste is None:
        liste = standard_liste(cur)
    try:
        if not isinstance(liste, str) or str(UUID(liste)) != liste:
            raise ValueError()
    except ValueError:
        raise HTTPException(404, "Liste nicht gefunden")
    cur.execute("SELECT seq FROM einkaufslisten WHERE uuid=%s FOR UPDATE", (liste,))
    if not cur.fetchone():
        raise HTTPException(404, "Liste nicht gefunden")
    return liste


def _uuid_existing(cur, ident):
    try:
        if str(UUID(ident)) != ident:
            raise ValueError()
    except ValueError:
        raise HTTPException(404, "Eintrag nicht gefunden")
    cur.execute("""SELECT liste_uuid FROM einkaufsliste_eintraege WHERE uuid=%s
        UNION SELECT liste_uuid FROM einkauf_aliase WHERE alt_uuid=%s""", (ident, ident))
    found = cur.fetchone()
    if not found:
        raise HTTPException(404, "Eintrag nicht gefunden")
    liste = _uuid_liste(cur, found["liste_uuid"])
    _, row = _entry(cur, ident, liste)
    if not row or row["geloescht_am"]:
        raise HTTPException(404, "Eintrag nicht gefunden")
    server_hlc(max(row[key] for key in ("hlc_inhalt", "hlc_menge", "hlc_status", "hlc_position")))
    return liste, row


def _uuid_apply(cur, liste, ops):
    results = apply_ops(cur, liste, ops)["ergebnisse"]
    for result in results:
        if result["ergebnis"] == "abgelehnt":
            raise HTTPException(400, result["grund"])
    return results


@router.get("/api/einkauf/eintraege")
def get_uuid_eintraege(liste: str | None = None, erledigte: bool = False):
    with get_db() as conn:
        with conn.cursor() as cur:
            liste = _uuid_liste(cur, liste)
            cur.execute("""SELECT * FROM einkaufsliste_eintraege WHERE liste_uuid=%s
                AND geloescht_am IS NULL AND (%s OR erledigt=0) ORDER BY erledigt, BINARY rang, id""",
                        (liste, erledigte))
            return {"eintraege": [_serialize(row) for row in cur.fetchall()]}


@router.post("/api/einkauf/eintraege", status_code=201)
def add_uuid_eintraege(body: dict):
    entries = body.get("eintraege")
    if "text" in body:
        text = body["text"]
        if "eintraege" in body or not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise HTTPException(400, "Text oder Einträge erforderlich, Text maximal 2000 Zeichen")
        entries = [parse_eintrag(part) for part in split_mehrfach(text)]
    allowed = {"name", "menge", "einheit", "menge_text", "notiz", "kategorie_id"}
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise HTTPException(400, "1 bis 100 Einträge erforderlich")
    if any(not isinstance(entry, dict) or set(entry) - allowed for entry in entries):
        raise HTTPException(400, "Ungültige Eintragsdaten")
    with get_db() as conn:
        with conn.cursor() as cur:
            liste = _uuid_liste(cur, body.get("liste"))
            rows = []
            for entry in entries:
                ident = str(uuid4())
                result = _uuid_apply(cur, liste, [server_op("anlegen", ident, {**entry, "manuell": True})])[0]
                cur.execute("SELECT * FROM einkaufsliste_eintraege WHERE uuid=%s FOR UPDATE", (result["eintrag_uuid"],))
                row = _serialize(cur.fetchone())
                if result["eintrag_uuid"] != ident:
                    row["zusammengefuehrt"] = True
                rows.append(row)
            return {"eintraege": rows}


@router.patch("/api/einkauf/eintraege/{ident}")
def update_uuid_eintrag(ident: str, body: dict):
    allowed = {"name", "notiz", "menge", "einheit", "menge_text", "erledigt", "kategorie_id"}
    if not body or set(body) - allowed:
        raise HTTPException(400, "Ungültige Eintragsdaten")
    with get_db() as conn:
        with conn.cursor() as cur:
            liste, row = _uuid_existing(cur, ident)
            ops = []
            content = {key: body[key] for key in ("name", "notiz", "kategorie_id") if key in body}
            if content:
                ops.append(server_op("inhalt_setzen", row["uuid"], content))
            if any(key in body for key in ("menge", "einheit", "menge_text")):
                ops.append(server_op("menge_setzen", row["uuid"],
                                     {key: body.get(key, row[key]) for key in ("menge", "einheit", "menge_text")}))
            if "erledigt" in body:
                ops.append(server_op("status_setzen", row["uuid"], {"erledigt": body["erledigt"]}))
            _uuid_apply(cur, liste, ops)
            cur.execute("SELECT * FROM einkaufsliste_eintraege WHERE uuid=%s FOR UPDATE", (row["uuid"],))
            return _serialize(cur.fetchone())


@router.delete("/api/einkauf/eintraege/{ident}")
def delete_uuid_eintrag(ident: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            liste, row = _uuid_existing(cur, ident)
            _uuid_apply(cur, liste, [server_op("loeschen", row["uuid"], {})])
    return {"ok": True}


@router.post("/api/einkauf/erledigte-loeschen")
def clear_uuid_erledigte(body: dict):
    with get_db() as conn:
        with conn.cursor() as cur:
            liste = _uuid_liste(cur, body.get("liste"))
            cur.execute("""SELECT uuid, hlc_status FROM einkaufsliste_eintraege
                WHERE liste_uuid=%s AND erledigt=1 AND geloescht_am IS NULL FOR UPDATE""", (liste,))
            entries = list(cur.fetchall())
            for start in range(0, len(entries), 500):
                _uuid_apply(cur, liste, [server_op("erledigte_loeschen", None, {"eintraege": entries[start:start + 500]})])
            return {"geloescht": len(entries)}


@router.get("/api/einkauf/kategorien")
def get_kategorien(laden: int | None = None):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT k.id,k.name,k.icon,k.standard_rang,k.aktiv,
                COALESCE(r.rang,k.standard_rang) AS rang FROM einkauf_kategorien k
                LEFT JOIN laden_kategorie_rang r ON r.kategorie_id=k.id AND r.laden_id=%s
                WHERE k.aktiv=1 ORDER BY BINARY COALESCE(r.rang,k.standard_rang),k.id""", (laden,))
            return {"kategorien": list(cur.fetchall())}


def _laeden(cur):
    cur.execute("SELECT id,name,aktiv,standard FROM laeden ORDER BY name,id")
    return [{**row, "aktiv": bool(row["aktiv"]), "standard": bool(row["standard"])} for row in cur.fetchall()]


@router.get("/api/einkauf/laeden")
def get_laeden():
    with get_db() as conn:
        with conn.cursor() as cur:
            return {"laeden": _laeden(cur)}


def _laden_daten(body, neu=False):
    if not body or set(body) - {"name", "aktiv", "standard"} or (neu and "name" not in body):
        raise HTTPException(400, "Ungültige Ladendaten")
    values = dict(body)
    if "name" in values:
        if not isinstance(values["name"], str) or not values["name"].strip() or len(values["name"].strip()) > 80:
            raise HTTPException(400, "Name muss 1 bis 80 Zeichen haben")
        values["name"] = values["name"].strip()
    for key in ("aktiv", "standard"):
        if key in values and type(values[key]) is not bool:
            raise HTTPException(400, "Ungültige Ladendaten")
    return values


def _laden(cur, ident):
    cur.execute("SELECT id FROM laeden WHERE id=%s FOR UPDATE", (ident,))
    if not cur.fetchone():
        raise HTTPException(404, "Laden nicht gefunden")


def _laden_name_frei(cur, name, ident=0):
    cur.execute("SELECT id FROM laeden WHERE name=%s AND id<>%s", (name, ident))
    if cur.fetchone():
        raise HTTPException(409, "Ladenname bereits vorhanden")


@router.post("/api/einkauf/laeden", status_code=201)
def create_laden(body: dict):
    values = _laden_daten(body, neu=True)
    with get_db() as conn:
        with conn.cursor() as cur:
            _laden_name_frei(cur, values["name"])
            if values.get("standard"):
                cur.execute("UPDATE laeden SET standard=0")
            cur.execute("INSERT INTO laeden (name,aktiv,standard) VALUES (%s,%s,%s)",
                        (values["name"], values.get("aktiv", True), values.get("standard", False)))
            ident = cur.lastrowid
            return next(row for row in _laeden(cur) if row["id"] == ident)


@router.patch("/api/einkauf/laeden/{ident}")
def update_laden(ident: int, body: dict):
    values = _laden_daten(body)
    with get_db() as conn:
        with conn.cursor() as cur:
            _laden(cur, ident)
            if "name" in values:
                _laden_name_frei(cur, values["name"], ident)
            if values.get("standard"):
                cur.execute("UPDATE laeden SET standard=0")
            cur.execute("UPDATE laeden SET " + ",".join(key + "=%s" for key in values) + " WHERE id=%s",
                        (*values.values(), ident))
            return next(row for row in _laeden(cur) if row["id"] == ident)


@router.delete("/api/einkauf/laeden/{ident}")
def delete_laden(ident: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            _laden(cur, ident)
            cur.execute("UPDATE einkaufslisten SET laden_id=NULL WHERE laden_id=%s", (ident,))
            cur.execute("DELETE FROM laden_kategorie_rang WHERE laden_id=%s", (ident,))
            cur.execute("DELETE FROM laeden WHERE id=%s", (ident,))
    return {"ok": True}


@router.put("/api/einkauf/laeden/{ident}/reihenfolge")
def set_reihenfolge(ident: int, body: dict):
    ids = body.get("kategorien")
    if set(body) != {"kategorien"} or not isinstance(ids, list) or any(type(i) is not int for i in ids) or len(ids) != len(set(ids)):
        raise HTTPException(400, "Ungültige Kategorien")
    with get_db() as conn:
        with conn.cursor() as cur:
            _laden(cur, ident)
            cur.execute("SELECT id FROM einkauf_kategorien WHERE aktiv=1")
            if set(ids) != {row["id"] for row in cur.fetchall()}:
                raise HTTPException(400, "Alle aktiven Kategorien erforderlich")
            cur.execute("DELETE FROM laden_kategorie_rang WHERE laden_id=%s", (ident,))
            cur.executemany("INSERT INTO laden_kategorie_rang (laden_id,kategorie_id,rang) VALUES (%s,%s,%s)",
                            [(ident, cat, rang_initial(i)) for i, cat in enumerate(ids)])
    return {"ok": True}


@router.patch("/api/einkauf/listen/{ident}")
def set_listen_laden(ident: str, body: dict):
    laden = body.get("laden_id")
    if set(body) != {"laden_id"} or (laden is not None and (type(laden) is not int or laden <= 0)):
        raise HTTPException(400, "Ungültiger Laden")
    with get_db() as conn:
        with conn.cursor() as cur:
            _uuid_liste(cur, ident)
            if laden is not None:
                _laden(cur, laden)
            cur.execute("UPDATE einkaufslisten SET laden_id=%s WHERE uuid=%s", (laden, ident))
            return next(row for row in _listen(cur) if row["uuid"] == ident)


@router.get("/api/einkauf/artikel")
def get_artikel(q: str = "", limit: int = 20):
    if not 1 <= limit <= 500 or len(q) > 255:
        raise HTTPException(400, "Ungültige Suche")
    pattern = q.strip().replace("!", "!!").replace("%", "!%").replace("_", "!_")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT name_norm,anzeigename,kategorie_id,letzte_menge,letzte_einheit,vorrat,anzahl_gekauft,ausgeblendet,ausgeblendet_bis
                FROM einkauf_artikel WHERE anzeigename LIKE %s ESCAPE '!'
                ORDER BY anzahl_gekauft DESC,zuletzt_gekauft DESC,anzeigename LIMIT %s""", ('%' + pattern + '%', limit))
            return {"artikel": list(cur.fetchall())}


@router.get("/api/einkauf/vorschlaege")
def get_vorschlaege(liste: str | None = None):
    with get_db() as conn:
        with conn.cursor() as cur:
            liste = _uuid_liste(cur, liste)
            cur.execute("SELECT UTC_TIMESTAMP() AS zeit")
            jetzt = cur.fetchone()["zeit"]
            cur.execute("""SELECT name_norm,herkunft,erledigt FROM einkaufsliste_eintraege
                WHERE liste_uuid=%s AND geloescht_am IS NULL""", (liste,))
            rows = cur.fetchall()
            offen = {row["name_norm"] for row in rows if not row["erledigt"]}
            recipes = {origin.get("rezept_id") for row in rows for origin in parse_json_field(row["herkunft"]) or []}
            cur.execute("""SELECT * FROM einkauf_artikel WHERE anzahl_gekauft>0
                AND (ausgeblendet=0 OR (ausgeblendet_bis IS NOT NULL AND ausgeblendet_bis<=%s))""", (jetzt,))
            articles = [row for row in cur.fetchall() if row["name_norm"] not in offen]
            due = []
            for row in articles:
                interval = float(row["intervall_tage"] or 0)
                if row["anzahl_gekauft"] >= 3 and row["zuletzt_gekauft"] and interval > 0:
                    elapsed = (jetzt - row["zuletzt_gekauft"]).total_seconds() / 86400
                    if elapsed >= interval:
                        due.append({**row, "tage_ueber": elapsed - interval, "_ratio": elapsed / interval})
            due.sort(key=lambda row: (-row["_ratio"], row["name_norm"]))
            for row in due:
                del row["_ratio"]
            recent = sorted((row for row in articles if row["zuletzt_gekauft"]),
                            key=lambda row: (row["zuletzt_gekauft"], row["name_norm"]), reverse=True)
            frequent = sorted(articles, key=lambda row: (row["anzahl_gekauft"], row["zuletzt_gekauft"] or datetime.min, row["name_norm"]), reverse=True)
            today = datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Vienna")).date()
            cur.execute("""SELECT w.rezept_id,r.titel,w.datum,COALESCE(w.portionen,r.portionen,1) AS portionen
                FROM wochenplan w JOIN rezepte r ON r.id=w.rezept_id WHERE w.datum BETWEEN %s AND %s
                ORDER BY w.datum,w.id""", (today, today + timedelta(days=6)))
            planned = [row for row in cur.fetchall() if row["rezept_id"] not in recipes]
            return {"faellig": due[:12], "haeufig": frequent[:20], "zuletzt": recent[:20], "wochenplan": planned}


def _artikel_name(body):
    name = body.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 255:
        raise HTTPException(400, "Name fehlt oder ist zu lang")
    from services.shopping_service import normalize_name
    return name.strip(), normalize_name(name)


@router.post("/api/einkauf/vorschlaege/ausblenden")
def vorschlag_ausblenden(body: dict):
    name, norm = _artikel_name(body)
    days = body.get("tage")
    if days is not None and (type(days) is not int or not 0 <= days <= 36500):
        raise HTTPException(400, "Ungültige Anzahl Tage")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO einkauf_artikel (name_norm,anzeigename,ausgeblendet,ausgeblendet_bis)
                VALUES (%s,%s,%s,DATE_ADD(UTC_TIMESTAMP(), INTERVAL %s DAY)) ON DUPLICATE KEY UPDATE
                ausgeblendet=VALUES(ausgeblendet),ausgeblendet_bis=VALUES(ausgeblendet_bis)""", (norm, name, days != 0, days))
    return {"ok": True}


@router.post("/api/einkauf/artikel/vorrat")
def artikel_vorrat(body: dict):
    name, norm = _artikel_name(body)
    if type(body.get("vorrat")) is not bool:
        raise HTTPException(400, "Vorrat muss ein Wahrheitswert sein")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO einkauf_artikel (name_norm,anzeigename,vorrat) VALUES (%s,%s,%s)
                ON DUPLICATE KEY UPDATE vorrat=VALUES(vorrat)""", (norm, name, body["vorrat"]))
    return {"ok": True}
