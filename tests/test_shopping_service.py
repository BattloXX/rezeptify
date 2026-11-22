from decimal import Decimal

import pytest
from db import get_db

from services.shopping_service import merge_or_add, scale_amount


@pytest.fixture()
def cur(client):
    with get_db() as conn:
        with conn.cursor() as cursor:
            yield cursor


def rows(cur):
    cur.execute("SELECT * FROM einkaufsliste_eintraege WHERE geloescht_am IS NULL ORDER BY id")
    return cur.fetchall()


def test_scale_amount_matches_client_rounding_and_fraction_rules():
    assert scale_amount("1/2", "EL", 2) == "1"
    assert scale_amount("1 1/2", "Stk", 0.5) == "¾"
    assert scale_amount("1,5", "l", 2) == "3"
    assert scale_amount("2-3", "Stk", 0.5) == "1–1½"
    assert scale_amount("12", "g", 1.2) == "14.5"
    assert scale_amount("nach Geschmack", None, 2) == "nach Geschmack"


def test_merge_or_add_merges_only_exact_name_and_compatible_units(cur):
    merge_or_add(cur, [{"name": "Tomaten", "menge": Decimal("1"), "einheit": "kg", "herkunft": [{"rezept_id": 1}]}])
    result = merge_or_add(cur, [{"name": " tomaten ", "menge": Decimal("500"), "einheit": "g", "herkunft": [{"rezept_id": 2}]}])
    assert len(rows(cur)) == 1
    # The first entry's unit stays: 1 kg + 500 g = 1.5 kg.
    assert rows(cur)[0]["menge"] == Decimal("1.5")
    assert rows(cur)[0]["einheit"] == "kg"
    assert result[0]["id"] == rows(cur)[0]["id"]
    assert result[0]["herkunft"] == [{"rezept_id": 1}, {"rezept_id": 2}]
    assert result[0]["uuid"] and result[0]["seq"] > 1
    cur.execute("SELECT COUNT(*) AS n FROM einkauf_aliase")
    assert cur.fetchone()["n"] == 1

    merge_or_add(cur, [{"name": "Tomaten", "menge": Decimal("2"), "einheit": "EL"}])
    assert len(rows(cur)) == 2


def test_merge_or_add_never_merges_free_text_amounts(cur):
    item = {"name": "Salz", "menge": None, "einheit": "", "menge_text": "nach Geschmack"}
    merge_or_add(cur, [item]); merge_or_add(cur, [item])
    assert len(rows(cur)) == 2
