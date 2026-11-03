"""Title-only duplicate candidates, without changing any recipes."""
import re
import unicodedata
from itertools import combinations


DUPLICATE_THRESHOLD = 0.7
_FILLER_WORDS = set("""
und mit in aus auf vom von der die das ein eine nach art a la de im an am fur zu
original klassisch klassiker einfach einfache einfacher perfekt perfektes bestes beste
omas selbst gemacht
""".split())


def normalize_title(t: str) -> str:
    folded = unicodedata.normalize("NFKD", t.lower().replace("ß", "ss"))
    ascii_title = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]", " ", ascii_title).split())


def title_tokens(t: str) -> set[str]:
    return {word for word in normalize_title(t).split()
            if word not in _FILLER_WORDS and (len(word) >= 3 or word.isdigit())}


def similarity(a: str, b: str) -> float:
    if normalize_title(a) == normalize_title(b):
        return 1.0
    tokens_a, tokens_b = title_tokens(a), title_tokens(b)
    if not tokens_a or not tokens_b:
        return 0.0
    shared = tokens_a & tokens_b
    score = len(shared) / len(tokens_a | tokens_b)
    smaller = min((tokens_a, tokens_b), key=len)
    if len(smaller) >= 2 or any(len(word) >= 5 and word in shared for word in smaller):
        score = max(score, len(shared) / len(smaller) * 0.9)
    if len(shared) >= 3:
        score = max(score, 0.75)
    return score


def find_similar(cur, titel: str, exclude_id: int | None = None, limit: int = 5) -> list[dict]:
    cur.execute("SELECT id, titel, slug, kategorie FROM rezepte ORDER BY id")
    matches = []
    for row in cur.fetchall():
        if row["id"] == exclude_id:
            continue
        score = similarity(titel, row["titel"])
        if score >= DUPLICATE_THRESHOLD:
            matches.append((score, {**row, "aehnlichkeit": round(score, 2)}))
    matches.sort(key=lambda match: match[0], reverse=True)
    return [match for _, match in matches[:limit]]


def find_duplicate_pairs(cur, limit: int = 50) -> list[dict]:
    cur.execute("SELECT id, titel FROM rezepte ORDER BY id")
    matches = []
    for a, b in combinations(cur.fetchall(), 2):
        score = similarity(a["titel"], b["titel"])
        if score >= DUPLICATE_THRESHOLD:
            matches.append((score, {"a": a, "b": b, "aehnlichkeit": round(score, 2)}))
    matches.sort(key=lambda match: match[0], reverse=True)
    return [match for _, match in matches[:limit]]
