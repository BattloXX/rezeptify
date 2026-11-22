"""Shared frontend/server rank examples, without database access."""
import json
from pathlib import Path

from services.einkauf_sync import rang_initial, rang_nach, rang_zwischen


def test_rang_fixture():
    cases = json.loads((Path(__file__).parent / "fixtures" / "rang_cases.json").read_text())
    for a, b, expected in cases["rangZwischen"]:
        assert rang_zwischen(a, b) == expected
    for a, expected in cases["rangNach"]:
        assert rang_nach(a) == expected
    for i, expected in cases["rangInitial"]:
        assert rang_initial(i) == expected
