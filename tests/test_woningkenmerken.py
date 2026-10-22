"""Tests voor de appartement/woonhuis-classificatie van Move's objectDetailedType."""
from rotterdam_scanner.woningkenmerken import classificeer_woningtype, mooi_woningtype


def test_appartement_typen():
    for t in ["BENEDENWONING", "BOVEN_WONING", "GALERIJFLAT", "PORTIEKFLAT",
              "PORTIEKWONING", "MAISONNETTE", "TUSSENVERDIEPING"]:
        assert classificeer_woningtype(t) == "appartement", t


def test_woonhuis_typen():
    for t in ["HERENHUIS", "TUSSENWONING", "GESCHAKELDE_2_ONDER_1_KAPWONING",
              "VRIJSTAANDE_WONING", "HOEKWONING"]:
        assert classificeer_woningtype(t) == "woonhuis", t


def test_onbekend_en_leeg():
    assert classificeer_woningtype(None) is None
    assert classificeer_woningtype("") is None
    assert classificeer_woningtype("IETS_NIEUWS_123") is None


def test_hoofdletterongevoelig():
    assert classificeer_woningtype("benedenwoning") == "appartement"
    assert classificeer_woningtype(" Herenhuis ") == "woonhuis"


def test_mooi_label():
    assert mooi_woningtype("BOVEN_WONING") == "Boven woning"
    assert mooi_woningtype(None) is None
