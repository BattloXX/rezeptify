"""Transactional shopping-list operations and offline synchronisation primitives."""
import json
import re
import threading
import time
from decimal import Decimal
from uuid import UUID, uuid4

from db import parse_json_field
from services.shopping_service import normalize_name, normalize_unit, _unit_multiplier, _decimal_amount


_HLC = re.compile(r"([0-9]{13})-([0-9a-f]{4})-([A-Za-z0-9_-]{1,36})", re.ASCII)
_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_clock_lock = threading.Lock()
_last_clock = (0, 0)
_HLC_FIELDS = ("hlc_inhalt", "hlc_menge", "hlc_status", "hlc_position", "hlc_geloescht")


class ListeNichtGefunden(Exception):
    pass


def parse_hlc(s):
    match = _HLC.fullmatch(s) if isinstance(s, str) and len(s) <= 64 else None
    if not match:
        raise ValueError("hlc_format")
    return int(match[1]), int(match[2], 16), match[3]


def server_hlc(seen=None):
    global _last_clock
    observed = parse_hlc(seen)[:2] if seen is not None else (0, 0)
    with _clock_lock:
        now = int(time.time() * 1000)
        ms = max(now, observed[0], _last_clock[0])
        counters = [counter for stamp, counter in (observed, _last_clock) if stamp == ms]
        counter = max(counters) + 1 if counters else 0
        if counter > 0xffff:
            ms, counter = ms + 1, 0
        if ms > 9999999999999:
            raise ValueError("hlc_ueberlauf")
        _last_clock = ms, counter
        return f"{ms:013d}-{counter:04x}-server"


def _rang(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9A-Za-z]{1,64}", value, re.ASCII):
        raise ValueError("rang_format")
    return value


def rang_zwischen(a, b):
    """ASCII fractional index; prefix/minimum-digit neighbours have no midpoint."""
    if a is not None:
        _rang(a)
    if b is not None:
        _rang(b)
    if a is not None and b is not None and a >= b:
        raise ValueError("rang_reihenfolge")
    prefix = ""
    lower, upper = a or "", b
    while True:
        lo = _DIGITS.index(lower[0]) if lower else -1
        hi = _DIGITS.index(upper[0]) if upper else 62
        if upper == "":
            candidate = prefix[:-1]
            if candidate and (a is None or a < candidate) and (b is None or candidate < b):
                return _rang(candidate)
            raise ValueError("rang_kein_zwischenraum")
        if hi - lo > 1:
            result = prefix + _DIGITS[(lo + hi) // 2]
            # A trailing minimum digit would create an unfillable left gap.
            if result.endswith("0"):
                result += "U"
            return _rang(result)
        if lo == hi:
            prefix += lower[0]
            lower, upper = lower[1:], upper[1:]
        elif lo == -1:
            prefix += upper[0]
            upper = upper[1:]
        else:
            prefix += lower[0]
            lower, upper = lower[1:], None


def rang_initial(i):
    if type(i) is not int or i < 0:
        raise ValueError("rang_index")
    value = (i + 1) * 1024
    if value >= 62 ** 8:
        raise ValueError("rang_index")
    result = ""
    for _ in range(8):
        result = _DIGITS[value % 62] + result
        value //= 62
    return result + "U"


def rang_nach(a):
    """Rank after a for appends: increments the 8-digit head instead of bisecting, so it never grows."""
    if a is None:
        return rang_initial(0)
    _rang(a)
    head = (a[:8] + "0" * 8)[:8]
    value = 0
    for char in head:
        value = value * 62 + _DIGITS.index(char)
    value = (value // 1024 + 1) * 1024
    if value < 62 ** 8:
        result = ""
        for _ in range(8):
            result = _DIGITS[value % 62] + result
            value //= 62
        result += "U"
        if result > a:
            return result
    return rang_zwischen(a, None)


def standard_liste(cur):
    cur.execute("SELECT uuid FROM einkaufslisten WHERE ist_standard=1 ORDER BY erstellt_am, uuid LIMIT 1")
    row = cur.fetchone()
    if row:
        return row["uuid"]
    ident = str(uuid4())
    cur.execute("INSERT INTO einkaufslisten (uuid, name, ist_standard) VALUES (%s,'Einkauf',1)", (ident,))
    return ident


def server_op(typ, eintrag_uuid, daten):
    return {"op_id": str(uuid4()), "typ": typ, "eintrag": eintrag_uuid,
            "hlc": server_hlc(), "daten": daten}


def _uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("uuid_format")
    return value


def _number(value, nullable=False):
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("menge_format")
    value = Decimal(str(value))
    if not value.is_finite() or abs(value) > Decimal("9999999.999"):
        raise ValueError("menge_bereich")
    return value


def _family(unit):
    """Known units share a family (g/kg); other units only match their own spelling (Bund, Dose)."""
    if not unit or not unit.strip():
        return ""
    return normalize_unit(unit) or " ".join(unit.strip().casefold().rstrip(".").split())


def _multiplier(unit):
    if not unit or not unit.strip():
        return Decimal(1)
    return _unit_multiplier(unit) or Decimal(1)


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError("daten_format")


def _validate(op):
    if not isinstance(op, dict) or set(op) - {"op_id", "typ", "eintrag", "hlc", "daten"}:
        raise ValueError("op_format")
    _uuid(op.get("op_id"))
    ms, _, _ = parse_hlc(op.get("hlc"))
    if ms > int(time.time() * 1000) + 86400000:
        raise ValueError("hlc_zukunft")
    fields = {
        "anlegen": ({"name", "menge", "einheit", "menge_text", "notiz", "rang", "herkunft", "manuell"}, {"name"}),
        "inhalt_setzen": ({"name", "notiz", "kategorie_id"}, set()),
        "menge_setzen": ({"menge", "einheit", "menge_text"}, {"menge", "einheit", "menge_text"}),
        "menge_plus": ({"menge", "einheit"}, {"menge"}),
        "herkunft_entfernen": ({"rezept_id"}, {"rezept_id"}),
        "status_setzen": ({"erledigt"}, {"erledigt"}),
        "verschieben": ({"rang"}, {"rang"}),
        "loeschen": (set(), set()),
        "erledigte_loeschen": ({"eintraege"}, {"eintraege"}),
    }
    typ, data = op.get("typ"), op.get("daten")
    if not isinstance(typ, str) or typ not in fields:
        raise ValueError("typ_unbekannt")
    if not isinstance(data, dict) or set(data) - fields[typ][0] or fields[typ][1] - set(data):
        raise ValueError("daten_format")
    if typ == "erledigte_loeschen":
        if op.get("eintrag") not in (None, ""):
            raise ValueError("eintrag_format")
        entries = data["eintraege"]
        if not isinstance(entries, list) or len(entries) > 500:
            raise ValueError("eintraege_format")
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"uuid", "hlc_status"}:
                raise ValueError("eintraege_format")
            _uuid(entry["uuid"])
            parse_hlc(entry["hlc_status"])
    else:
        _uuid(op.get("eintrag"))
    for key, limit in (("name", 255), ("notiz", 255), ("einheit", 32), ("menge_text", 64)):
        if key in data:
            val = data[key]
            if key != "name" and val is None:
                continue
            if not isinstance(val, str) or len(val) > limit or (key == "name" and not val.strip()):
                raise ValueError(key + "_format")
    if "menge" in data:
        _number(data["menge"], nullable=typ != "menge_plus")
    if "rang" in data:
        _rang(data["rang"])
    for key in ("erledigt", "manuell"):
        if key in data and type(data[key]) is not bool:
            raise ValueError(key + "_format")
    if "herkunft" in data and not isinstance(data["herkunft"], list):
        raise ValueError("herkunft_format")
    if "rezept_id" in data and (type(data["rezept_id"]) is not int or not 0 < data["rezept_id"] <= 2147483647):
        raise ValueError("rezept_id_format")
    if "kategorie_id" in data and data["kategorie_id"] is not None:
        if type(data["kategorie_id"]) is not int or not 0 < data["kategorie_id"] <= 2147483647:
            raise ValueError("kategorie_id_format")
    try:
        json.dumps(data, allow_nan=False, default=_json_default)
    except (TypeError, ValueError):
        raise ValueError("daten_format")


def _resolve(cur, ident, liste):
    visited = set()
    while ident not in visited:
        visited.add(ident)
        cur.execute("SELECT ziel_uuid, liste_uuid FROM einkauf_aliase WHERE alt_uuid=%s FOR UPDATE", (ident,))
        alias = cur.fetchone()
        if not alias:
            return ident
        if alias["liste_uuid"] != liste:
            raise ValueError("andere_liste")
        ident = alias["ziel_uuid"]
    raise ValueError("alias_zyklus")


def _entry(cur, ident, liste):
    ident = _resolve(cur, ident, liste)
    cur.execute("SELECT * FROM einkaufsliste_eintraege WHERE uuid=%s FOR UPDATE", (ident,))
    row = cur.fetchone()
    if row and row["liste_uuid"] != liste:
        raise ValueError("andere_liste")
    return ident, row


def _amount_plus(row, amount, unit):
    family = _family(row["einheit"])
    if row["menge_text"] or family is None or family != _family(unit):
        raise ValueError("einheit_inkompatibel")
    old = row["menge"] if row["menge"] is not None else (1 if family == "" else 0)
    total = max(Decimal(0), Decimal(old) * _multiplier(row["einheit"]) + amount * _multiplier(unit))
    # Keep the entry's own unit (2 kg + 500 g = 2.5 kg), never switch silently to the base unit.
    if row["einheit"] and row["einheit"].strip():
        return _number(total / _multiplier(row["einheit"])), row["einheit"]
    return _number(total / _multiplier(unit)), unit or None


def apply_ops(cur, liste_uuid, ops, geraet_hlc_seen=None):
    cur.execute("SELECT seq FROM einkaufslisten WHERE uuid=%s FOR UPDATE", (liste_uuid,))
    liste = cur.fetchone()
    if not liste:
        raise ListeNichtGefunden(liste_uuid)
    seq = liste["seq"]
    # Locking reads below also see current data if the caller already opened a snapshot.

    def update(ident, values):
        nonlocal seq
        seq += 1
        values["seq"] = seq
        cur.execute("UPDATE einkaufsliste_eintraege SET " + ", ".join(f"{key}=%s" for key in values) + " WHERE uuid=%s",
                    (*values.values(), ident))

    results = []
    for op in ops:
        op_id = op.get("op_id") if isinstance(op, dict) else None
        result = {"op_id": op_id, "ergebnis": "abgelehnt", "eintrag_uuid": None}
        try:
            _uuid(op_id)
        except (ValueError, TypeError, AttributeError):
            result["grund"] = "uuid_format"
            results.append(result)
            continue
        # Reserve the global id before applying any effects, including across lists.
        cur.execute("""INSERT IGNORE INTO einkauf_ops
            (op_id,liste_uuid,typ,hlc,daten,ergebnis) VALUES (%s,%s,'','',NULL,'abgelehnt')""", (op_id, liste_uuid))
        if not cur.rowcount:
            cur.execute("SELECT daten FROM einkauf_ops WHERE op_id=%s FOR UPDATE", (op_id,))
            results.append(parse_json_field(cur.fetchone()["daten"])["_sync_result"])
            continue
        cur.execute("SAVEPOINT einkauf_op")
        old_seq = seq
        try:
            _validate(op)
            typ, hlc, data = op["typ"], op["hlc"], op["daten"]
            removed_delta = None
            if typ == "erledigte_loeschen":
                # Resolve and check every list before making changes.
                entries = [(_entry(cur, item["uuid"], liste_uuid), item["hlc_status"]) for item in data["eintraege"]]
                changed = False
                deleted = set()
                for (ident, row), status in entries:
                    if row and ident not in deleted and not row["geloescht_am"] and row["erledigt"] and row["hlc_status"] <= status:
                        deleted.add(ident)
                        cur.execute("SELECT UTC_TIMESTAMP() AS zeit")
                        update(ident, {"geloescht_am": cur.fetchone()["zeit"], "hlc_geloescht": hlc})
                        changed = True
                result["ergebnis"] = "ok" if changed else "ignoriert"
            else:
                ident, row = _entry(cur, op["eintrag"], liste_uuid)
                result["eintrag_uuid"] = ident
                if row and (row["geloescht_am"] or typ == "anlegen"):
                    result["ergebnis"] = "ignoriert"
                elif typ == "anlegen":
                    target = None
                    family = _family(data.get("einheit"))
                    if not data.get("menge_text") and family is not None:
                        cur.execute("""SELECT * FROM einkaufsliste_eintraege WHERE liste_uuid=%s
                            AND erledigt=0 AND geloescht_am IS NULL AND BINARY name_norm=BINARY %s ORDER BY id FOR UPDATE""",
                                    (liste_uuid, normalize_name(data["name"])))
                        target = next((r for r in cur.fetchall() if not r["menge_text"] and _family(r["einheit"]) == family), None)
                    if target:
                        ident = target["uuid"]
                        amount = data.get("menge")
                        amount = Decimal(str(amount)) if amount is not None else Decimal(1 if family == "" else 0)
                        values = {"herkunft": json.dumps(parse_json_field(target["herkunft"]) + data.get("herkunft", [])),
                                  "manuell": bool(target["manuell"] or data.get("manuell", False))}
                        cur.execute("""SELECT op_id FROM einkauf_ops WHERE eintrag_uuid=%s
                            AND typ='menge_setzen' AND ergebnis='ok' AND BINARY hlc > BINARY %s LIMIT 1 FOR UPDATE""",
                                    (ident, hlc))
                        if not cur.fetchone():
                            values["menge"], values["einheit"] = _amount_plus(target, amount, data.get("einheit"))
                        update(ident, values)
                        seq += 1
                        cur.execute("INSERT INTO einkauf_aliase (alt_uuid,ziel_uuid,liste_uuid,seq) VALUES (%s,%s,%s,%s)",
                                    (op["eintrag"], ident, liste_uuid, seq))
                        result["eintrag_uuid"] = ident
                    else:
                        rank = data.get("rang")
                        if rank is None:
                            cur.execute("SELECT rang FROM einkaufsliste_eintraege WHERE liste_uuid=%s AND rang IS NOT NULL ORDER BY BINARY rang DESC LIMIT 1 FOR UPDATE", (liste_uuid,))
                            last = cur.fetchone()
                            rank = rang_nach(last["rang"] if last else None)
                        seq += 1
                        cur.execute("""INSERT INTO einkaufsliste_eintraege
                            (uuid,liste_uuid,name,name_norm,menge,einheit,menge_text,notiz,manuell,herkunft,rang,
                             hlc_inhalt,hlc_menge,hlc_status,hlc_position,hlc_geloescht,seq)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                                    (ident, liste_uuid, data["name"].strip(), normalize_name(data["name"]), data.get("menge"),
                                     data.get("einheit"), data.get("menge_text"), data.get("notiz"), data.get("manuell", False),
                                     json.dumps(data.get("herkunft", [])), rank, hlc, hlc, hlc, hlc, hlc, seq))
                    result["ergebnis"] = "ok"
                elif not row:
                    raise ValueError("eintrag_nicht_gefunden")
                elif typ == "herkunft_entfernen":
                    origins = parse_json_field(row["herkunft"])
                    removed = [origin for origin in origins if origin.get("rezept_id") == data["rezept_id"]]
                    remaining = [origin for origin in origins if origin.get("rezept_id") != data["rezept_id"]]
                    if not removed:
                        result["ergebnis"] = "ignoriert"
                    else:
                        values = {"herkunft": json.dumps(remaining)}
                        if hlc >= row["hlc_menge"]:
                            from services.mengen_parser import _numeric
                            delta = Decimal(0)
                            for origin in removed:
                                try:
                                    amount = _decimal_amount(origin.get("menge"))
                                    if amount is None:
                                        amount = Decimal(str(_numeric(str(origin.get("menge", "")))))
                                except (ValueError, ZeroDivisionError):
                                    continue
                                if amount.is_finite() and _family(origin.get("einheit")) == _family(row["einheit"]):
                                    delta += amount * _multiplier(origin.get("einheit")) / _multiplier(row["einheit"])
                            removed_delta = -delta
                            if row["menge"] is not None:
                                values["menge"] = _number(max(Decimal(0), Decimal(row["menge"]) - delta))
                            if not remaining and not row["manuell"] and (row["menge"] is None or values.get("menge", row["menge"]) <= 0):
                                cur.execute("SELECT UTC_TIMESTAMP() AS zeit")
                                values.update(geloescht_am=cur.fetchone()["zeit"], hlc_geloescht=hlc)
                        update(ident, values)
                        result["ergebnis"] = "ok"
                elif typ == "menge_plus":
                    if hlc < row["hlc_menge"]:
                        result["ergebnis"] = "ignoriert"
                    else:
                        amount, unit = _amount_plus(row, _number(data["menge"]), data.get("einheit"))
                        update(ident, {"menge": amount, "einheit": unit})
                        result["ergebnis"] = "ok"
                elif typ == "loeschen":
                    cur.execute("SELECT UTC_TIMESTAMP() AS zeit")
                    update(ident, {"geloescht_am": cur.fetchone()["zeit"], "hlc_geloescht": hlc})
                    result["ergebnis"] = "ok"
                else:
                    field = {"inhalt_setzen": "hlc_inhalt", "menge_setzen": "hlc_menge",
                             "status_setzen": "hlc_status", "verschieben": "hlc_position"}[typ]
                    if hlc <= row[field]:
                        result["ergebnis"] = "ignoriert"
                    else:
                        values = dict(data)
                        if typ == "inhalt_setzen" and "name" in values:
                            values["name"] = values["name"].strip()
                            values["name_norm"] = normalize_name(values["name"])
                        if typ == "status_setzen":
                            cur.execute("SELECT UTC_TIMESTAMP() AS zeit")
                            values["erledigt_am"] = cur.fetchone()["zeit"] if data["erledigt"] else None
                        if typ == "menge_setzen":
                            family = _family(data["einheit"])
                            if not data["menge_text"] and family is not None:
                                total = data["menge"] if data["menge"] is not None else (1 if family == "" else 0)
                                total = Decimal(str(total)) * _multiplier(data["einheit"])
                                cur.execute("""SELECT daten FROM einkauf_ops WHERE eintrag_uuid=%s
                                    AND typ IN ('menge_plus','anlegen','herkunft_entfernen') AND ergebnis='ok' AND BINARY hlc > BINARY %s
                                    ORDER BY BINARY hlc, op_id FOR UPDATE""", (ident, hlc))
                                applied = False
                                for delta in cur.fetchall():
                                    saved = parse_json_field(delta["daten"])
                                    if saved.get("_sync_delta") and _family(saved.get("einheit")) == family:
                                        total += Decimal(str(saved["_sync_delta"])) * _multiplier(saved.get("einheit"))
                                        applied = True
                                # Without newer deltas keep the user's spelling (1,5 kg stays kg).
                                if applied:
                                    values["menge"] = _number(max(Decimal(0), total) / _multiplier(data["einheit"]))
                                    values["einheit"] = data["einheit"] or None
                        values[field] = hlc
                        update(ident, values)
                        result["ergebnis"] = "ok"
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            cur.execute("ROLLBACK TO SAVEPOINT einkauf_op")
            seq = old_seq
            result["ergebnis"] = "abgelehnt"
            result["grund"] = str(exc) if isinstance(exc, ValueError) else "op_format"
        cur.execute("RELEASE SAVEPOINT einkauf_op")
        # Keep the exact response for retries, alongside the original operation data.
        saved = dict(op.get("daten")) if isinstance(op.get("daten"), dict) else {}
        if result["ergebnis"] == "ok" and op.get("typ") == "menge_plus":
            saved["_sync_delta"] = saved["menge"]
        elif result["ergebnis"] == "ok" and op.get("typ") == "anlegen" and result["eintrag_uuid"] != op.get("eintrag"):
            saved["_sync_delta"] = saved.get("menge") if saved.get("menge") is not None else (1 if not saved.get("einheit") else 0)
        if result["ergebnis"] == "ok" and op.get("typ") == "herkunft_entfernen" and removed_delta is not None:
            saved["_sync_delta"] = removed_delta
            saved["einheit"] = row["einheit"]
        saved["_sync_result"] = result
        try:
            encoded = json.dumps(saved, allow_nan=False, default=_json_default)
        except (ValueError, TypeError):
            encoded = json.dumps({"_sync_result": result})
        valid_hlc = op.get("hlc")
        try:
            parse_hlc(valid_hlc)
        except ValueError:
            valid_hlc = ""
        typ = op.get("typ")
        cur.execute("""UPDATE einkauf_ops SET eintrag_uuid=%s,typ=%s,hlc=%s,daten=%s,ergebnis=%s,seq=%s
            WHERE op_id=%s""", (result["eintrag_uuid"], typ if isinstance(typ, str) and len(typ) <= 32 else "",
                                 valid_hlc, encoded, result["ergebnis"], seq, op_id))
        results.append(result)
    cur.execute("UPDATE einkaufslisten SET seq=%s WHERE uuid=%s", (seq, liste_uuid))
    return {"ergebnisse": results, "seq": seq}


def aenderungen_seit(cur, liste_uuid, seit):
    if type(seit) is not int or seit < 0:
        raise ValueError("seq_format")
    # Share the list lock so seq and both collections describe the same state.
    cur.execute("SELECT seq FROM einkaufslisten WHERE uuid=%s LOCK IN SHARE MODE", (liste_uuid,))
    liste = cur.fetchone()
    if not liste:
        raise ListeNichtGefunden(liste_uuid)
    cur.execute("""SELECT * FROM einkaufsliste_eintraege WHERE liste_uuid=%s
        AND (%s=0 OR seq>%s) ORDER BY seq, id LOCK IN SHARE MODE""", (liste_uuid, seit, seit))
    entries = []
    fields = ("uuid", "id", "name", "notiz", "einheit", "menge_text", "rang", "kategorie_id", "seq") + _HLC_FIELDS
    for row in cur.fetchall():
        entry = {key: row[key] for key in fields}
        entry.update(menge=float(row["menge"]) if row["menge"] is not None else None,
                     erledigt=bool(row["erledigt"]), manuell=bool(row["manuell"]),
                     herkunft=parse_json_field(row["herkunft"]), geloescht=bool(row["geloescht_am"]))
        for key in ("erledigt_am", "erstellt_am"):
            entry[key] = row[key].isoformat() if row[key] else None
        entries.append(entry)
    cur.execute("""SELECT alt_uuid AS alt, ziel_uuid AS ziel FROM einkauf_aliase
        WHERE liste_uuid=%s AND (%s=0 OR seq>%s) ORDER BY seq LOCK IN SHARE MODE""", (liste_uuid, seit, seit))
    return {"seq": liste["seq"], "eintraege": entries, "aliase": list(cur.fetchall())}
