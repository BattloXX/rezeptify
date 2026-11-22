"""Shopping sync contract against the real MariaDB test database."""
import random
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest

from db import get_db, init_db
from services.einkauf_sync import (
    ListeNichtGefunden, aenderungen_seit, apply_ops, parse_hlc, rang_initial,
    rang_zwischen, server_hlc, server_op, standard_liste,
)


@pytest.fixture()
def liste(client):
    with get_db() as conn:
        with conn.cursor() as cur:
            return standard_liste(cur)


def hlc(t=0, device="geraetA"):
    return f"{1600000000000 + t:013d}-0000-{device}"


def op(typ, ident, data=None, t=10, device="geraetA"):
    return {"op_id": str(uuid4()), "typ": typ, "eintrag": ident,
            "hlc": hlc(t, device), "daten": data or {}}


def send(liste, *ops):
    with get_db() as conn:
        with conn.cursor() as cur:
            return apply_ops(cur, liste, list(ops))


def state(liste, seit=0):
    with get_db() as conn:
        with conn.cursor() as cur:
            return aenderungen_seit(cur, liste, seit)


def create(liste, name="Milch", **data):
    ident = str(uuid4())
    assert send(liste, op("anlegen", ident, {"name": name, **data}, t=0))["ergebnisse"][0]["ergebnis"] == "ok"
    return ident


def test_k2_offline_different_entries(liste):
    ids = [create(liste, f"Artikel {i}") for i in range(8)]
    offline = [op("status_setzen", ident, {"erledigt": True}, device="geraetA") for ident in ids[:5]]
    send(liste, *[op("status_setzen", ident, {"erledigt": True}, device="geraetB") for ident in ids[5:]])
    send(liste, *offline)
    assert sum(row["erledigt"] for row in state(liste)["eintraege"]) == 8


def test_k3_same_entry(liste):
    ident = create(liste)
    send(liste, op("status_setzen", ident, {"erledigt": True}),
         op("status_setzen", ident, {"erledigt": True}, device="geraetB"))
    rows = state(liste)["eintraege"]
    assert len(rows) == 1 and rows[0]["erledigt"]


def test_k4_status_converges_in_both_orders(liste):
    for reverse in (False, True):
        ident = create(liste, str(reverse))
        ops = [op("status_setzen", ident, {"erledigt": True}, t=1),
               op("status_setzen", ident, {"erledigt": False}, t=2, device="geraetB")]
        send(liste, *ops[::(-1 if reverse else 1)])
    assert all(not row["erledigt"] for row in state(liste)["eintraege"])


def test_k5_independent_fields(liste):
    ident = create(liste)
    send(liste, op("menge_setzen", ident, {"menge": 3, "einheit": None, "menge_text": None}),
         op("status_setzen", ident, {"erledigt": True}, device="geraetB"))
    row = state(liste)["eintraege"][0]
    assert row["menge"] == 3 and row["erledigt"]


def test_k6_two_deltas(liste):
    ident = create(liste, menge=1)
    send(liste, op("menge_plus", ident, {"menge": 1}),
         op("menge_plus", ident, {"menge": 1}, device="geraetB"))
    assert state(liste)["eintraege"][0]["menge"] == 3


def test_k6b_set_replays_later_deltas(liste):
    ident = create(liste)
    send(liste, op("menge_plus", ident, {"menge": 1}, t=3))
    send(liste, op("menge_setzen", ident, {"menge": 3, "einheit": None, "menge_text": None}, t=2))
    assert state(liste)["eintraege"][0]["menge"] == 4
    result = send(liste, op("menge_plus", ident, {"menge": 1}, t=1))
    assert result["ergebnisse"][0]["ergebnis"] == "ignoriert"
    assert state(liste)["eintraege"][0]["menge"] == 4


def test_k7_merge_alias_and_followup(liste):
    target = create(liste)
    alias = str(uuid4())
    result = send(liste, op("anlegen", alias, {"name": " MILCH "}))
    assert result["ergebnisse"][0]["eintrag_uuid"] == target
    send(liste, op("status_setzen", alias, {"erledigt": True}, t=20))
    snapshot = state(liste)
    assert len(snapshot["eintraege"]) == 1
    assert snapshot["eintraege"][0]["menge"] == 2
    assert snapshot["eintraege"][0]["erledigt"]
    assert snapshot["aliase"] == [{"alt": alias, "ziel": target}]


def test_k8_tombstone_is_final(liste):
    ident = create(liste)
    send(liste, op("loeschen", ident))
    result = send(liste, op("menge_setzen", ident, {"menge": 5, "einheit": None, "menge_text": None}, t=20))
    assert result["ergebnisse"][0]["ergebnis"] == "ignoriert"
    assert state(liste)["eintraege"][0]["geloescht"]


def test_k9_stale_clear_keeps_reopened_entry(liste):
    ident = create(liste)
    send(liste, op("status_setzen", ident, {"erledigt": True}, t=1))
    send(liste, op("status_setzen", ident, {"erledigt": False}, t=2))
    send(liste, op("erledigte_loeschen", None, {"eintraege": [{"uuid": ident, "hlc_status": hlc(1)}]}))
    assert not state(liste)["eintraege"][0]["geloescht"]


def test_k10_idempotent_delta(liste):
    ident = create(liste, menge=1)
    delta = op("menge_plus", ident, {"menge": 1})
    first = send(liste, delta)
    second = send(liste, delta)
    assert first == second
    assert state(liste)["eintraege"][0]["menge"] == 2


def test_k11_independent_positions(liste):
    a, b = create(liste, "A"), create(liste, "B")
    send(liste, op("verschieben", a, {"rang": "a"}), op("verschieben", b, {"rang": "b"}))
    assert {row["uuid"]: row["rang"] for row in state(liste)["eintraege"]} == {a: "a", b: "b"}


def test_k12_future_clock(liste):
    ident = create(liste)
    future = op("status_setzen", ident, {"erledigt": True})
    future["hlc"] = f"{int(time.time() * 1000) + 25 * 3600000:013d}-0000-geraetA"
    result = send(liste, future)
    assert result["ergebnisse"][0]["grund"] == "hlc_zukunft"
    assert send(liste, future) == result
    seen = f"{int(time.time() * 1000) + 3600000:013d}-ffff-geraetB"
    assert server_hlc(seen) > seen
    assert server_hlc() > seen


def test_k13_concurrent_connections(liste):
    ids = [create(liste, f"Artikel {i}") for i in range(40)]
    barrier = Barrier(2)

    def worker(group, device):
        with get_db() as conn:
            with conn.cursor() as cur:
                barrier.wait(timeout=10)
                return apply_ops(cur, liste, [op("status_setzen", ident, {"erledigt": True}, device=device) for ident in group])

    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(worker, ids[:20], "geraetA")
        b = executor.submit(worker, ids[20:], "geraetB")
        results = [a.result(timeout=20), b.result(timeout=20)]
    assert all(r["ergebnis"] == "ok" for batch in results for r in batch["ergebnisse"])
    snapshot = state(liste)
    assert snapshot["seq"] == 80
    assert len({row["seq"] for row in snapshot["eintraege"]}) == 40
    assert all(row["erledigt"] for row in snapshot["eintraege"])


def test_changes_include_tombstones_and_aliases(liste):
    ident = create(liste)
    before = state(liste)["seq"]
    alias = str(uuid4())
    send(liste, op("anlegen", alias, {"name": "Milch"}))
    changes = state(liste, before)
    assert changes["aliase"] == [{"alt": alias, "ziel": ident}]
    assert len(changes["eintraege"]) == 1
    send(liste, op("loeschen", alias, t=20))
    changes = state(liste, changes["seq"])
    assert changes["eintraege"][0]["geloescht"] and changes["aliase"] == []
    assert state(liste, changes["seq"])["eintraege"] == []
    assert len(state(liste)["aliase"]) == 1


def test_migration_backfill_is_idempotent(client):
    with get_db() as conn:
        with conn.cursor() as cur:
            for name, order in (("  MILCH ", 2), ("Brot", 1), ("Salz", 1)):
                cur.execute("INSERT INTO einkaufsliste_eintraege (name,sortierung) VALUES (%s,%s)", (name, order))
    init_db()
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM einkaufsliste_eintraege ORDER BY sortierung,id")
            before = cur.fetchall()
            assert all(row["uuid"] and row["liste_uuid"] and row["rang"] and row["seq"] for row in before)
            assert [row["rang"] for row in before] == sorted(row["rang"] for row in before)
            assert [row["seq"] for row in before] == [1, 2, 3]
            assert before[-1]["name_norm"] == "milch"
            assert all(row["hlc_inhalt"] == row["hlc_menge"] == row["hlc_status"] == row["hlc_position"] == row["hlc_geloescht"] for row in before)
            cur.execute("SELECT seq FROM einkaufslisten WHERE uuid=%s", (before[0]["liste_uuid"],))
            assert cur.fetchone()["seq"] == 3
    init_db()
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM einkaufsliste_eintraege ORDER BY sortierung,id")
            assert cur.fetchall() == before


def test_fractional_rank_random_insertions():
    rng = random.Random(42)
    ranks = []
    for _ in range(1000):
        i = rng.randrange(len(ranks) + 1)
        rank = rang_zwischen(ranks[i - 1] if i else None, ranks[i] if i < len(ranks) else None)
        ranks.insert(i, rank)
    assert ranks == sorted(set(ranks))
    assert max(map(len, ranks)) < 16
    initial = [rang_initial(i) for i in range(1001)]
    assert initial == sorted(set(initial))
    assert len({len(rank) for rank in initial}) == 1
    # No ASCII string exists strictly between a prefix and prefix + minimum digit.
    with pytest.raises(ValueError, match="kein_zwischenraum"):
        rang_zwischen("a", "a0")
    assert "a" < rang_zwischen("a", "a1") < "a1"


def test_amounts_without_units(liste):
    create(liste)
    create(liste, menge=2)
    row = state(liste)["eintraege"][0]
    assert row["menge"] == 3 and row["einheit"] is None


def test_units_delta_replay_and_negative_clamp(liste):
    ident = create(liste, menge=1, einheit="kg")
    send(liste, op("menge_plus", ident, {"menge": 500, "einheit": "g"}, t=30))
    send(liste, op("menge_setzen", ident, {"menge": 2, "einheit": "kg", "menge_text": None}, t=20))
    assert state(liste)["eintraege"][0]["menge"] == 2.5
    result = send(liste, op("menge_plus", ident, {"menge": 1, "einheit": "ml"}, t=40))
    assert result["ergebnisse"][0]["grund"] == "einheit_inkompatibel"
    send(liste, op("menge_plus", ident, {"menge": -10, "einheit": "kg"}, t=50))
    row = state(liste)["eintraege"][0]
    assert row["menge"] == 0 and not row["geloescht"]


def test_text_amounts_never_merge(liste):
    create(liste, menge_text="nach Bedarf")
    create(liste, menge_text="nach Bedarf")
    assert len(state(liste)["eintraege"]) == 2


def test_content_lww_and_category(liste):
    ident = create(liste)
    send(liste, op("inhalt_setzen", ident, {"name": " Brot ", "notiz": "Vollkorn", "kategorie_id": 3}, t=20))
    send(liste, op("inhalt_setzen", ident, {"name": "Alt"}, t=10))
    row = state(liste)["eintraege"][0]
    assert (row["name"], row["notiz"], row["kategorie_id"]) == ("Brot", "Vollkorn", 3)


def test_cross_list_ops_rejected(liste):
    ident = create(liste)
    with get_db() as conn:
        with conn.cursor() as cur:
            other = str(uuid4())
            cur.execute("INSERT INTO einkaufslisten (uuid,name) VALUES (%s,'Andere')", (other,))
    for typ, data in (("anlegen", {"name": "Falsch"}), ("status_setzen", {"erledigt": True})):
        assert send(other, op(typ, ident, data))["ergebnisse"][0]["grund"] == "andere_liste"
    assert not state(liste)["eintraege"][0]["erledigt"]


def test_bulk_clear_checks_status_and_is_atomic(liste):
    a, b = create(liste, "A"), create(liste, "B")
    send(liste, op("status_setzen", a, {"erledigt": True}, t=5),
         op("status_setzen", b, {"erledigt": True}, t=20))
    send(liste, op("erledigte_loeschen", None, {"eintraege": [{"uuid": a, "hlc_status": hlc(5)}, {"uuid": b, "hlc_status": hlc(10)}]}))
    rows = {row["uuid"]: row for row in state(liste)["eintraege"]}
    assert rows[a]["geloescht"] and not rows[b]["geloescht"]


def test_bad_ops_do_not_abort_batch(liste):
    ident = create(liste)
    bad = [op("unbekannt", ident), op("status_setzen", ident, {"erledigt": 1}),
           op("verschieben", ident, {"rang": "!"}), op("anlegen", str(uuid4()), {"name": ""}),
           op("menge_plus", ident, {"menge": float("nan")}),
           op("inhalt_setzen", ident, {"kategorie_id": []})]
    invalid_hlc = op("loeschen", ident)
    invalid_hlc["hlc"] = "bad"
    bad.append(invalid_hlc)
    valid = op("status_setzen", ident, {"erledigt": True})
    result = send(liste, *bad, valid)
    assert all(r["ergebnis"] == "abgelehnt" for r in result["ergebnisse"][:-1])
    assert result["ergebnisse"][-1]["ergebnis"] == "ok"
    assert send(liste, *bad)["ergebnisse"] == result["ergebnisse"][:-1]


def test_hlc_strict_and_server_ops():
    for bad in ("1-0000-A", "1600000000000-ABCD-A", "1600000000000-0000-", "1600000000000-0000-ä", "1600000000000-0000-" + "a" * 37, None):
        with pytest.raises(ValueError):
            parse_hlc(bad)
    assert parse_hlc(hlc()) == (1600000000000, 0, "geraetA")
    clocks = [server_hlc() for _ in range(100)]
    assert clocks == sorted(set(clocks))
    ident = str(uuid4())
    built = server_op("loeschen", ident, {})
    assert built["eintrag"] == ident and parse_hlc(built["hlc"])[2] == "server"


def test_missing_list_and_standard_recreation(client):
    with get_db() as conn:
        with conn.cursor() as cur:
            with pytest.raises(ListeNichtGefunden):
                apply_ops(cur, str(uuid4()), [])
            with pytest.raises(ListeNichtGefunden):
                aenderungen_seit(cur, str(uuid4()), 0)
            a = standard_liste(cur)
            assert standard_liste(cur) == a
            cur.execute("DELETE FROM einkaufslisten WHERE uuid=%s", (a,))
            assert standard_liste(cur) != a


def test_merge_older_creation_still_adds(liste):
    first, second = str(uuid4()), str(uuid4())
    send(liste, op("anlegen", first, {"name": "Milch"}, t=20))
    send(liste, op("anlegen", second, {"name": "Milch"}, t=10))
    assert state(liste)["eintraege"][0]["menge"] == 2


def test_merge_delta_survives_delayed_set(liste):
    ident = create(liste, menge=1, einheit="kg", herkunft=[{"rezept_id": 1}])
    alias = str(uuid4())
    send(liste, op("anlegen", alias, {"name": "Milch", "menge": 500, "einheit": "g", "herkunft": [{"rezept_id": 2}]}, t=30))
    send(liste, op("menge_setzen", ident, {"menge": 2, "einheit": "kg", "menge_text": None}, t=20))
    row = state(liste)["eintraege"][0]
    assert row["menge"] == 2.5 and row["einheit"] == "kg"
    assert row["herkunft"] == [{"rezept_id": 1}, {"rezept_id": 2}]


def test_bulk_clear_duplicate_ids_change_once(liste):
    ident = create(liste)
    send(liste, op("status_setzen", ident, {"erledigt": True}, t=5))
    before = state(liste)["seq"]
    entry = {"uuid": ident, "hlc_status": hlc(5)}
    send(liste, op("erledigte_loeschen", None, {"eintraege": [entry, entry]}))
    assert state(liste)["seq"] == before + 1


def test_bulk_clear_rejects_foreign_list_without_partial_changes(liste):
    ident = create(liste)
    send(liste, op("status_setzen", ident, {"erledigt": True}, t=5))
    other, foreign = str(uuid4()), str(uuid4())
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO einkaufslisten (uuid,name) VALUES (%s,'Andere')", (other,))
    send(other, op("anlegen", foreign, {"name": "Brot"}))
    before = state(liste)["seq"]
    result = send(liste, op("erledigte_loeschen", None, {"eintraege": [
        {"uuid": ident, "hlc_status": hlc(5)}, {"uuid": foreign, "hlc_status": hlc(5)}]}))
    assert result["ergebnisse"][0]["grund"] == "andere_liste"
    assert state(liste)["seq"] == before
    assert not state(liste)["eintraege"][0]["geloescht"]


def test_fractional_rank_prefix_boundaries():
    assert "a" < rang_zwischen("a", "a00") < "a00"
    assert "a0" < rang_zwischen("a0", "a000") < "a000"
    assert "a0" < rang_zwischen("a0", "a1") < "a1"
    assert rang_zwischen(None, "00") < "00"


def test_normalized_names_preserve_accents(liste):
    create(liste, "Apfel")
    create(liste, "Äpfel")
    assert len(state(liste)["eintraege"]) == 2


def test_decimal_amount_from_server_callers(liste):
    ident = create(liste, menge=Decimal("1.5"))
    send(liste, op("menge_plus", ident, {"menge": Decimal("0.25")}))
    assert state(liste)["eintraege"][0]["menge"] == 1.75


def test_existing_transaction_snapshot_cannot_overwrite_newer_status(liste):
    ident = create(liste)
    newer = op("status_setzen", ident, {"erledigt": True}, t=20)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT erledigt FROM einkaufsliste_eintraege WHERE uuid=%s", (ident,))
            assert not cur.fetchone()["erledigt"]
            send(liste, newer)
            result = apply_ops(cur, liste, [op("status_setzen", ident, {"erledigt": False}, t=10)])
            assert result["ergebnisse"][0]["ergebnis"] == "ignoriert"
            assert apply_ops(cur, liste, [newer])["ergebnisse"][0]["ergebnis"] == "ok"
    assert state(liste)["eintraege"][0]["erledigt"]


def test_unbekannte_einheit_eigene_familie_und_menge_setzen_behaelt_einheit(client):
    from db import get_db
    from services.einkauf_sync import apply_ops, standard_liste
    from uuid import uuid4

    def op(typ, eintrag, daten, ms):
        return {"op_id": str(uuid4()), "typ": typ, "eintrag": eintrag, "hlc": f"{ms:013d}-0000-geraetA", "daten": daten}

    base = 1700000000000
    a, b, c = str(uuid4()), str(uuid4()), str(uuid4())
    with get_db() as conn:
        with conn.cursor() as cur:
            liste = standard_liste(cur)
            res = apply_ops(cur, liste, [
                op("anlegen", a, {"name": "Petersilie", "menge": 1, "einheit": "Bund"}, base),
                op("anlegen", b, {"name": "petersilie", "menge": 2, "einheit": "bund"}, base + 1),
                op("menge_plus", a, {"menge": 1, "einheit": "Bund"}, base + 2),
                op("anlegen", c, {"name": "Kartoffeln", "menge": 1, "einheit": "kg"}, base + 3),
                op("menge_setzen", c, {"menge": 1.5, "einheit": "kg", "menge_text": None}, base + 4),
            ])
            assert [r["ergebnis"] for r in res["ergebnisse"]] == ["ok"] * 5
            cur.execute("SELECT name, menge, einheit FROM einkaufsliste_eintraege WHERE geloescht_am IS NULL ORDER BY id")
            rows = cur.fetchall()
    assert len(rows) == 2
    assert float(rows[0]["menge"]) == 4 and rows[0]["einheit"] == "Bund"
    assert float(rows[1]["menge"]) == 1.5 and rows[1]["einheit"] == "kg"


def test_rang_nach_waechst_nicht_bei_vielen_anhaengen():
    from services.einkauf_sync import rang_nach, rang_zwischen
    rang = None
    ranks = []
    for _ in range(5000):
        rang = rang_nach(rang)
        ranks.append(rang)
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks)
    assert max(len(r) for r in ranks) == 9
    # Nach einem per rang_zwischen eingefügten Rang geht es weiterhin kurz weiter.
    mitte = rang_zwischen(ranks[0], ranks[1])
    assert rang_nach(mitte) > mitte
    assert rang_nach("zzzzzzzzU") > "zzzzzzzzU"


def test_anhaengen_ueber_400_eintraege(client):
    from db import get_db
    from services.einkauf_sync import apply_ops, standard_liste
    from uuid import uuid4
    base = 1700000000000
    with get_db() as conn:
        with conn.cursor() as cur:
            liste = standard_liste(cur)
            ops = [{"op_id": str(uuid4()), "typ": "anlegen", "eintrag": str(uuid4()),
                    "hlc": f"{base + i:013d}-0000-geraetA", "daten": {"name": f"Artikel {i}"}} for i in range(450)]
            res = apply_ops(cur, liste, ops)
            assert all(r["ergebnis"] == "ok" for r in res["ergebnisse"])
            cur.execute("SELECT MAX(LENGTH(rang)) AS n FROM einkaufsliste_eintraege")
            assert cur.fetchone()["n"] <= 9


def test_k_recipe_removal_converts_units_and_is_idempotent(liste):
    origins = [{"rezept_id": 1, "menge": "0,5", "einheit": "kg"},
               {"rezept_id": 1, "menge": "100", "einheit": "g"},
               {"rezept_id": 2, "menge": "400", "einheit": "g"}]
    ident = create(liste, menge=1000, einheit="g", herkunft=origins)
    removal = op("herkunft_entfernen", ident, {"rezept_id": 1}, t=30)
    send(liste, removal, removal, op("herkunft_entfernen", ident, {"rezept_id": 1}, t=40))
    row = state(liste)["eintraege"][0]
    assert row["menge"] == 400 and row["herkunft"] == origins[2:] and not row["geloescht"]
    send(liste, op("menge_setzen", ident, {"menge": 2, "einheit": "kg", "menge_text": None}, t=20))
    assert state(liste)["eintraege"][0]["menge"] == 1.4


@pytest.mark.parametrize('manual,amount,deleted', [(False, 2, True), (True, 2, False), (True, 5, False), (False, None, True)])
def test_k_recipe_removal_tombstone(liste, manual, amount, deleted):
    ident = create(liste, menge=amount, manuell=manual,
                   herkunft=[{"rezept_id": 1, "menge": "2" if amount is not None else "etwas", "einheit": None}])
    send(liste, op("herkunft_entfernen", ident, {"rezept_id": 1}))
    row = state(liste)["eintraege"][0]
    assert row["geloescht"] is deleted and row["herkunft"] == []
    assert row["menge"] == (max(0, amount - 2) if amount is not None else None)


@pytest.mark.parametrize('reverse', [False, True])
def test_k_recipe_removal_respects_newer_amount(liste, reverse):
    ident = create(liste, menge=2, herkunft=[{"rezept_id": 1, "menge": "2"}], manuell=True)
    ops = [op("herkunft_entfernen", ident, {"rezept_id": 1}, t=10),
           op("menge_setzen", ident, {"menge": 8, "einheit": None, "menge_text": None}, t=20)]
    send(liste, *ops[::(-1 if reverse else 1)])
    row = state(liste)["eintraege"][0]
    assert row["menge"] == 8 and row["herkunft"] == [] and not row["geloescht"]


@pytest.mark.parametrize('value', [True, None, -1, 0, 1.5, "1", 2147483648])
def test_recipe_removal_validation(liste, value):
    ident = create(liste)
    result = send(liste, op("herkunft_entfernen", ident, {"rezept_id": value}))
    assert result["ergebnisse"][0]["grund"] == "rezept_id_format"


@pytest.mark.parametrize('quantity,amount', [('1½', 1.5), ('⅓', .33), ('1/2', .5), ('nach Geschmack', None)])
def test_k_recipe_removal_formatted_recipe_quantities(liste, quantity, amount):
    ident = create(liste, menge=amount, einheit='kg', herkunft=[{"rezept_id": 1, "menge": quantity, "einheit": "kg"}])
    send(liste, op('herkunft_entfernen', ident, {"rezept_id": 1}))
    row = state(liste)["eintraege"][0]
    assert row["geloescht"] and row["herkunft"] == []
    assert row["menge"] == (0 if amount is not None else None)


def test_menge_plus_behaelt_einheit_des_eintrags(client):
    from db import get_db
    from services.einkauf_sync import apply_ops, standard_liste
    from uuid import uuid4
    base = 1700000000000
    a = str(uuid4())

    def op(typ, daten, t):
        return {"op_id": str(uuid4()), "typ": typ, "eintrag": a, "hlc": f"{base + t:013d}-0000-geraetA", "daten": daten}

    with get_db() as conn:
        with conn.cursor() as cur:
            liste = standard_liste(cur)
            apply_ops(cur, liste, [op("anlegen", {"name": "Kartoffeln", "menge": 2, "einheit": "kg"}, 0),
                                   op("menge_plus", {"menge": 0.5, "einheit": "kg"}, 1),
                                   op("menge_plus", {"menge": 250, "einheit": "g"}, 2)])
            cur.execute("SELECT menge, einheit FROM einkaufsliste_eintraege WHERE uuid=%s", (a,))
            row = cur.fetchone()
            assert float(row["menge"]) == 2.75 and row["einheit"] == "kg"
            # Older set + newer delta: recomputed in the unit of the set (1 kg + 0.5 kg + 250 g).
            apply_ops(cur, liste, [op("menge_setzen", {"menge": 1, "einheit": "kg", "menge_text": None}, 0)])
            cur.execute("SELECT menge, einheit FROM einkaufsliste_eintraege WHERE uuid=%s", (a,))
            row = cur.fetchone()
    assert row["einheit"] == "kg"
