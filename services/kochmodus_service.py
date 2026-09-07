"""Helpers for generating practical cooking steps from recipe instructions."""
import re
from typing import Optional


_STEP_MARKER = re.compile(r"(?im)^\s*(?:\d+\s*[.)]|schritt\s*\d+\s*[:.)]?)\s*")
_TIME = re.compile(
    r"(?i)(\d+)\s*(stunden?|std\.?|h|minuten?|min\.?|sekunden?|sek\.?|s)\b"
)


def split_zubereitung(text: str) -> list[str]:
    """Split only explicit steps or paragraphs; otherwise preserve one text block."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    matches = list(_STEP_MARKER.finditer(cleaned))
    if matches:
        steps = []
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
            step = cleaned[match.end():end].strip()
            if step:
                steps.append(step)
        if steps:
            return steps

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", cleaned) if part.strip()]
    return paragraphs if len(paragraphs) > 1 else [cleaned]


def parse_zeit(text: str) -> Optional[int]:
    """Return the first duration mentioned in text in seconds, if any."""
    total = 0
    found = False
    for value, unit in _TIME.findall(text or ""):
        found = True
        amount = int(value)
        normalized = unit.lower().rstrip(".")
        if normalized.startswith(("stunde", "std", "h")):
            total += amount * 3600
        elif normalized.startswith(("minute", "min")):
            total += amount * 60
        else:
            total += amount
    return total if found else None
