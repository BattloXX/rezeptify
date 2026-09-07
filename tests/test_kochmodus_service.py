from services.kochmodus_service import parse_zeit, split_zubereitung


def test_split_numbered_instructions():
    assert split_zubereitung("1. Zwiebel schneiden.\n2. 10 Minuten braten.\n3. Servieren.") == [
        "Zwiebel schneiden.", "10 Minuten braten.", "Servieren."
    ]


def test_split_preserves_unstructured_text_as_one_step():
    assert split_zubereitung("Alles vermengen und goldbraun backen.") == [
        "Alles vermengen und goldbraun backen."
    ]


def test_split_paragraphs_and_parse_durations():
    assert split_zubereitung("Vorbereiten.\n\nDann backen.") == ["Vorbereiten.", "Dann backen."]
    assert parse_zeit("30 Minuten backen") == 1800
    assert parse_zeit("1 Stunde und 15 Min. ruhen lassen") == 4500
    assert parse_zeit("Ohne Zeitangabe") is None
