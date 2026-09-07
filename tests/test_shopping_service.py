from decimal import Decimal

from services.shopping_service import merge_or_add, scale_amount


class Cursor:
    def __init__(self): self.rows, self.lastrowid, self._result = [], 0, []
    def execute(self, sql, params=None):
        if sql.startswith("SELECT *"):
            self._result = [dict(row) for row in self.rows]
        elif sql.startswith("INSERT"):
            self.lastrowid += 1
            keys = ("name", "menge", "einheit", "menge_text", "erledigt", "manuell", "herkunft", "sortierung")
            row = dict(zip(keys, params)); row["id"] = self.lastrowid
            self.rows.append(row)
        elif sql.startswith("UPDATE"):
            row = next(r for r in self.rows if r["id"] == params[-1])
            row.update(menge=params[0], einheit=params[1], herkunft=params[2])
    def fetchall(self): return self._result


def test_scale_amount_matches_client_rounding_and_fraction_rules():
    assert scale_amount("1/2", "EL", 2) == "1"
    assert scale_amount("1 1/2", "Stk", 0.5) == "¾"
    assert scale_amount("1,5", "l", 2) == "3"
    assert scale_amount("2-3", "Stk", 0.5) == "1–1½"
    assert scale_amount("12", "g", 1.2) == "14.5"
    assert scale_amount("nach Geschmack", None, 2) == "nach Geschmack"


def test_merge_or_add_merges_only_exact_name_and_compatible_units():
    cur = Cursor()
    merge_or_add(cur, [{"name": "Tomaten", "menge": Decimal("1"), "einheit": "kg", "herkunft": [{"rezept_id": 1}]}])
    merge_or_add(cur, [{"name": " tomaten ", "menge": Decimal("500"), "einheit": "g", "herkunft": [{"rezept_id": 2}]}])
    assert len(cur.rows) == 1
    assert cur.rows[0]["menge"] == Decimal("1500")
    assert cur.rows[0]["einheit"] == "g"

    merge_or_add(cur, [{"name": "Tomaten", "menge": Decimal("2"), "einheit": "EL"}])
    assert len(cur.rows) == 2


def test_merge_or_add_never_merges_free_text_amounts():
    cur = Cursor()
    item = {"name": "Salz", "menge": None, "einheit": "", "menge_text": "nach Geschmack"}
    merge_or_add(cur, [item]); merge_or_add(cur, [item])
    assert len(cur.rows) == 2
