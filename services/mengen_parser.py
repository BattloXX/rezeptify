"""Deterministic free-text shopping input; grammar shared with mengen-parser.js."""
import math
import re

UNITS = {'g': 'g', 'kg': 'kg', 'mg': 'mg', 'ml': 'ml', 'cl': 'cl', 'dl': 'dl', 'l': 'l', 'stk': 'Stk', 'stück': 'Stk', 'stücke': 'Stk', 'el': 'EL', 'tl': 'TL', 'pkg': 'Pkg', 'packung': 'Pkg', 'packungen': 'Pkg', 'pck': 'Pkg', 'bund': 'Bund', 'bünde': 'Bund', 'dose': 'Dose', 'dosen': 'Dosen', 'becher': 'Becher', 'flasche': 'Flasche', 'flaschen': 'Flaschen', 'glas': 'Glas', 'gläser': 'Gläser', 'kiste': 'Kiste', 'kisten': 'Kisten', 'netz': 'Netz', 'netze': 'Netze', 'beutel': 'Beutel', 'prise': 'Prise', 'prisen': 'Prisen', 'zehe': 'Zehe', 'zehen': 'Zehen', 'scheibe': 'Scheibe', 'scheiben': 'Scheiben', 'rolle': 'Rolle', 'rollen': 'Rollen'}
NUM = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?|[½¼¾⅓⅔])"
QTY = rf"{NUM}(?:\s*[-–]\s*{NUM})?"
UNIT = "|".join(sorted(UNITS, key=len, reverse=True))
PREFIX = re.compile(rf"^({QTY})(?:\s*[x×]\s*|\s*({UNIT})\.?(?=\s|$)\s*|\s+)(.+)$", re.I)
SUFFIX = re.compile(rf"^(.+?)\s+(?:[x×]\s*({QTY})|({QTY})(?:\s*[x×]|\s*({UNIT})\.?)?)$", re.I)
FRACTIONS = {"½": .5, "¼": .25, "¾": .75, "⅓": 1/3, "⅔": 2/3}


def _numeric(value):
    if value in FRACTIONS:
        return FRACTIONS[value]
    if "/" in value:
        parts = value.split()
        numerator, denominator = parts.pop().split("/")
        return (float(parts[0]) if parts else 0) + float(numerator) / float(denominator)
    return float(value.replace(",", "."))


def parse_eintrag(text):
    notes = []

    def note(match):
        if match[1].strip():
            notes.append(match[1].strip())
        return " "

    name = " ".join(re.sub(r"\(([^()]*)\)", note, text).split())
    quantity = unit = None
    prefix = PREFIX.fullmatch(name)
    suffix = None if prefix else SUFFIX.fullmatch(name)
    if prefix:
        quantity, unit, name = prefix.groups()
    elif suffix:
        name, first, second, unit = suffix.groups()
        quantity = first or second
    amount = amount_text = None
    if quantity:
        parts = re.split(r"\s*[-–]\s*", quantity)
        if len(parts) == 2:
            amount_text = "–".join(parts)
        else:
            try:
                amount = _numeric(quantity)
                if not math.isfinite(amount):
                    amount = None
            except ZeroDivisionError:
                pass
    return {"name": name.strip(), "menge": amount, "einheit": UNITS.get(unit.lower()) if unit else None,
            "menge_text": amount_text, "notiz": "; ".join(notes) or None}


def split_mehrfach(text):
    parts = []
    start = depth = 0
    for i, char in enumerate(text):
        if char == "(":
            depth += 1
        if char == ")":
            depth = max(0, depth - 1)
        decimal = char == "," and i > 0 and i + 1 < len(text) and text[i - 1] in "0123456789" and text[i + 1] in "0123456789"
        if not depth and (char in "\n\r;" or (char == "," and not decimal)):
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return [clean for part in parts if (clean := re.sub(r"^(?:(?:[•*☐-]|\[\s*\]|\d+\.(?=\s|$))\s*)+", "", part.strip()).strip())]
