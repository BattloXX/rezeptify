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


def merge_or_add(cur, eintraege):
    """Persist entries, merging only exact names and recognised unit families."""
    result = []
    for entry in eintraege:
        name = str(entry.get("name") or "").strip()
        menge_text = entry.get("menge_text")
        unit = (entry.get("einheit") or "").strip() or None
        amount = entry.get("menge")
        origin = entry.get("herkunft") or []
        if isinstance(origin, dict):
            origin = [origin]
        family, multiplier = normalize_unit(unit), _unit_multiplier(unit)
        decimal_amount = _decimal_amount(amount) if isinstance(amount, str) else (Decimal(str(amount)) if amount is not None else None)
        can_merge = bool(name and family and decimal_amount is not None and not menge_text)
        existing = None
        if can_merge:
            cur.execute("SELECT * FROM einkaufsliste_eintraege WHERE erledigt=0 AND menge_text IS NULL")
            for row in cur.fetchall():
                if normalize_name(row["name"]) == normalize_name(name) and normalize_unit(row["einheit"]) == family:
                    existing = row
                    break
        if existing:
            old_multiplier = _unit_multiplier(existing["einheit"])
            total = Decimal(str(existing["menge"])) * old_multiplier + decimal_amount * multiplier
            # Store in the canonical base unit when unit spellings differ.
            stored_unit = existing["einheit"] if old_multiplier == Decimal("1") else family
            stored_amount = total if stored_unit == family else total / old_multiplier
            old_origin = existing.get("herkunft")
            if isinstance(old_origin, str):
                try: old_origin = json.loads(old_origin)
                except json.JSONDecodeError: old_origin = []
            cur.execute("""UPDATE einkaufsliste_eintraege
                SET menge=%s, einheit=%s, herkunft=%s WHERE id=%s""",
                (stored_amount, stored_unit, json.dumps((old_origin or []) + origin, ensure_ascii=False), existing["id"]))
            existing.update(menge=stored_amount, einheit=stored_unit, herkunft=(old_origin or []) + origin)
            result.append(existing)
            continue
        cur.execute("""INSERT INTO einkaufsliste_eintraege
            (name, menge, einheit, menge_text, erledigt, manuell, herkunft, sortierung)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (name, decimal_amount, unit, menge_text, bool(entry.get("erledigt")), bool(entry.get("manuell")),
             json.dumps(origin, ensure_ascii=False) if origin else None, entry.get("sortierung")))
        result.append({"id": cur.lastrowid, "name": name, "menge": decimal_amount, "einheit": unit,
                       "menge_text": menge_text, "erledigt": bool(entry.get("erledigt")),
                       "manuell": bool(entry.get("manuell")), "herkunft": origin, "sortierung": entry.get("sortierung")})
    return result
