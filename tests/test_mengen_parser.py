"""The browser and REST parser consume the same expectations."""
import json
from pathlib import Path

import pytest

from services.mengen_parser import parse_eintrag, split_mehrfach

CASES = json.loads((Path(__file__).parent / "fixtures/mengen_parser_cases.json").read_text())


@pytest.mark.parametrize("case", CASES["parse"], ids=lambda case: case["text"])
def test_parse(case):
    assert parse_eintrag(case["text"]) == case["expected"]


@pytest.mark.parametrize("case", CASES["split"], ids=lambda case: case["text"])
def test_split(case):
    assert split_mehrfach(case["text"]) == case["expected"]
