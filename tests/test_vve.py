from decimal import Decimal

from rotterdam_scanner.vve import classificeer_vve, parse_vve_bijdrage


def test_parse_bijdrage_euro():
    assert parse_vve_bijdrage("€ 78,75") == Decimal("78.75")


def test_parse_bijdrage_checklist_vorm():
    assert parse_vve_bijdrage("Ja (€ 78,75 p.m.)") == Decimal("78.75")


def test_parse_bijdrage_duizendtal():
    assert parse_vve_bijdrage("€ 1.250,00") == Decimal("1250.00")


def test_parse_bijdrage_geen():
    assert parse_vve_bijdrage(None) is None
    assert parse_vve_bijdrage("Geen") is None
    assert parse_vve_bijdrage("n.v.t.") is None
    assert parse_vve_bijdrage("€ 0,00") is None


def test_appartement_heeft_vve():
    r = classificeer_vve("appartement", Decimal("78.75"))
    assert r["heeft_vve"] is True and r["bijdrage_pm"] == Decimal("78.75")


def test_woonhuis_geen_vve():
    r = classificeer_vve("woonhuis", Decimal("50.00"))
    assert r["heeft_vve"] is False and r["bijdrage_pm"] is None


def test_expliciet_signaal_wint():
    assert classificeer_vve("appartement", None, heeft_vve_signaal=False)["heeft_vve"] is False


def test_onbekend_type_zonder_bijdrage():
    assert classificeer_vve(None)["heeft_vve"] is None


def test_onbekend_type_met_bijdrage_is_vve():
    assert classificeer_vve(None, Decimal("40.00"))["heeft_vve"] is True
