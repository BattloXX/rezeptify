"""Conservative ingredient scaling and shopping-list aggregation."""
import json
import math
import re
from decimal import Decimal, ROUND_HALF_UP


_FRACTIONS = ((0.25, "¼"), (0.5, "½"), (0.75, "¾"), (0.33, "⅓"), (0.67, "⅔"))
_UNIT_FAMILIES = {
    "g": ("g", Decimal("1")), "kg": ("g", Decimal("1000")),
    "ml": ("ml", Decimal("1")), "l": ("ml", Decimal("1000")),
    "stk": ("Stk", Decimal("1")), "stück": ("Stk", Decimal("1")), "stueck": ("Stk", Decimal("1")),
    "el": ("EL", Decimal("1")), "tl": ("TL", Decimal("1")),
}


def normalize_unit(einheit):
    """Return the canonical unit family, or None for anything ambiguous."""
    if not isinstance(einheit, str):
        return None
    item = _UNIT_FAMILIES.get(einheit.strip().lower().rstrip("."))
    return item[0] if item else None


def _unit_multiplier(einheit):
    if not isinstance(einheit, str):
        return None
    item = _UNIT_FAMILIES.get(einheit.strip().lower().rstrip("."))
    return item[1] if item else None


def normalize_name(name):
    """Only normalise harmless whitespace/case differences; never fuzzy-match."""
    if not isinstance(name, str):
        return ""
    return " ".join(name.strip().casefold().split())


def format_num(n):
    """Python port of static/js/utils.js::formatNum()."""
    n = float(n)
    if n == 0:
        return "0"
    whole = math.floor(n)
    dec = n - whole
    for value, symbol in _FRACTIONS:
        if abs(dec - value) < 0.06:
            return f"{whole}{symbol}" if whole > 0 else symbol
    if n >= 100:
        return str(math.floor(n + 0.5))
    if n >= 10:
        value = math.floor(n * 2 + 0.5) / 2
    elif n >= 1:
        value = math.floor(n * 4 + 0.5) / 4
    else:
        value = math.floor(n * 10 + 0.5) / 10
    return str(int(value)) if value == int(value) else str(value)


def scale_amount(menge, einheit=None, faktor=1):
    """Port of scaleAmount(menge, factor); einheit is accepted for API symmetry."""
    if not menge or not str(menge).strip():
        return ""
    text = str(menge).strip()
    factor = float(faktor)
    fraction = re.fullmatch(r"(\d+)/(\d+)", text)
    if fraction:
        return format_num((int(fraction[1]) / int(fraction[2])) * factor)
    mixed = re.fullmatch(r"(\d+)\s+(\d+)/(\d+)", text)
    if mixed:
        return format_num((int(mixed[1]) + int(mixed[2]) / int(mixed[3])) * factor)
    amount_range = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)", text)
    if amount_range:
        return f"{format_num(float(amount_range[1].replace(',', '.')) * factor)}–{format_num(float(amount_range[2].replace(',', '.')) * factor)}"
    # JS parseFloat deliberately accepts a numeric prefix.
    numeric = re.match(r"[+-]?(?:\d+(?:[.]\d*)?|[.]\d+)", text.replace(",", "."))
    if numeric:
        return format_num(float(numeric.group()) * factor)
    return text


def _decimal_amount(value):
    """Turn the formatted scale result (including unicode fractions) into Decimal."""
    if not value or "–" in str(value) or "-" in str(value):
        return None
    text = str(value).strip()
    fractions = {"¼": Decimal(".25"), "½": Decimal(".5"), "¾": Decimal(".75"), "⅓": Decimal(".33"), "⅔": Decimal(".67")}
    for symbol, fraction in fractions.items():
        if text.endswith(symbol):
            whole = text[:-1]
            return Decimal(whole or "0") + fraction
    try:
        return Decimal(text.replace(",", "."))
    except Exception:
        return None


def zutaten_fuer_einkauf(rezept, portionen):
    """Return scaled, merge-ready shopping entries for one recipe row."""
    base_portionen = rezept.get("portionen") or 0
    faktor = portionen / base_portionen if base_portionen else 1
    zutaten = rezept.get("zutaten") or []
    if isinstance(zutaten, str):
        try:
            zutaten = json.loads(zutaten)
        except json.JSONDecodeError:
            zutaten = []
    items = []
    for zutat in zutaten:
        if zutat.get("gruppe") or not zutat.get("name"):
            continue
        raw = zutat.get("menge") or ""
        scaled = scale_amount(raw, zutat.get("einheit"), faktor)
        amount = _decimal_amount(scaled)
        items.append({
            "name": zutat["name"], "menge": amount, "einheit": zutat.get("einheit"),
            "menge_text": None if amount is not None else (scaled or None),
            "herkunft": [{"rezept_id": rezept["id"], "rezept_titel": rezept["titel"],
                           "menge": scaled, "einheit": zutat.get("einheit") or ""}],
        })
    return items


def merge_or_add(cur, eintraege):
    """Persist entries through the sync engine and return the resulting rows."""
    from uuid import uuid4
    from db import parse_json_field
    from services.einkauf_sync import apply_ops, server_op, standard_liste

    result = []
    liste = standard_liste(cur)
    for entry in eintraege:
        amount = entry.get("menge")
        origin = entry.get("herkunft") or []
        if isinstance(origin, dict):
            origin = [origin]
        data = {"name": str(entry.get("name") or "").strip(),
                "menge": _decimal_amount(amount) if isinstance(amount, str) else amount,
                "einheit": (entry.get("einheit") or "").strip() or None,
                "menge_text": entry.get("menge_text"), "herkunft": origin,
                "manuell": bool(entry.get("manuell"))}
        applied = apply_ops(cur, liste, [server_op("anlegen", str(uuid4()), data)])["ergebnisse"][0]
        if applied["ergebnis"] == "abgelehnt":
            raise ValueError(applied["grund"])
        cur.execute("SELECT * FROM einkaufsliste_eintraege WHERE uuid=%s FOR UPDATE", (applied["eintrag_uuid"],))
        row = cur.fetchone()
        row["herkunft"] = parse_json_field(row["herkunft"])
        row["erledigt"], row["manuell"] = bool(row["erledigt"]), bool(row["manuell"])
        result.append(row)
    return result
