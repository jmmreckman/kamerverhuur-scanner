"""Tests voor rotterdam_scanner/vergunningenindex.py: het parsen van de body van
een kamerverhuurvergunning, de Nederlandse datum-omzetting, de incrementele
bijwerking (met gemockte enumeratie/body/geocoding) en de analyse-aggregatie.
Er wordt nooit echt naar KOOP/PDOK gebeld."""
from datetime import date

import pytest

from rotterdam_scanner import vergunningenindex as vi

# Verkorte, representatieve body zoals repository.overheid.nl 'm levert (HTML
# gestript tot de relevante regels).
_BODY = """
<p>Het college maakt bekend dat zij de volgende vergunning voor kamerbewoning heeft verleend.</p>
<p>Gebied: Delfshaven Adres: C.P.Tielestraat 30B Postcode: 3023 TD
Activiteit: vergunning kamerverhuur aan 3 personen Verzenddatum besluit: 22 juli 2026
Zaaknummer: 523472-2026</p>
"""


def test_parse_body_leest_alle_velden():
    velden = vi.parse_body(_BODY)
    assert velden == {
        "gebied": "Delfshaven",
        "adres": "C.P.Tielestraat 30B",
        "postcode": "3023TD",
        "aantal_personen": 3,
        "besluitdatum": "2026-07-22",
        "zaaknummer": "523472-2026",
    }


def test_parse_body_zonder_adres_geeft_none():
    assert vi.parse_body("<p>Beleidsregel kamerbewoning zonder adres.</p>") is None


@pytest.mark.parametrize(
    "tekst,iso",
    [
        ("22 juli 2026", "2026-07-22"),
        ("4 maart 2025", "2025-03-04"),
        ("1 januari 2020", "2020-01-01"),
        ("onzin", None),
        (None, None),
    ],
)
def test_nl_datum_naar_iso(tekst, iso):
    assert vi._nl_datum_naar_iso(tekst) == iso


def test_werk_bij_verwerkt_batch_en_is_resumable(tmp_path, monkeypatch):
    # Enumeratie levert twee stubs; body + geocoding worden gemockt.
    def _fake_enum(vanaf=None):
        return {
            "gmb-2026-1": {
                "publicatie_id": "gmb-2026-1", "titel": "Vergunning kamerverhuur A-straat 1",
                "datum": "2026-08-01", "url": "https://zoek/gmb-2026-1.html",
                "html_url": "https://repo/gmb-2026-1.html", "verwerkt": False,
            },
            "gmb-2026-2": {
                "publicatie_id": "gmb-2026-2", "titel": "Vergunning kamerverhuur B-straat 2",
                "datum": "2026-08-02", "url": "https://zoek/gmb-2026-2.html",
                "html_url": "https://repo/gmb-2026-2.html", "verwerkt": False,
            },
        }

    monkeypatch.setattr(vi, "enumereer_stubs", _fake_enum)

    class _Geo:
        lat, lon, rotterdam_wijk = 51.9, 4.45, "Delfshaven"

    def _fake_verwerk(stub):
        stub["verwerkt"] = True
        stub["bruikbaar"] = True
        stub["gebied"] = "Delfshaven"
        stub["adres"] = stub["titel"].split("kamerverhuur ")[1]
        stub["aantal_personen"] = 3
        stub["lat"], stub["lon"] = 51.9, 4.45

    monkeypatch.setattr(vi, "_verwerk_stub", _fake_verwerk)

    index_path = tmp_path / "vergunningen_index.json"
    # Batch 1 verwerkt er maar één -> nog niet compleet.
    voortgang = vi.werk_bij(index_path, batch=1, vandaag=date(2026, 8, 20))
    assert voortgang["totaal"] == 2
    assert voortgang["bruikbaar"] == 1
    assert voortgang["resterend"] == 1
    assert voortgang["compleet"] is False

    # Batch 2 maakt het af.
    voortgang2 = vi.werk_bij(index_path, batch=5, vandaag=date(2026, 8, 20))
    assert voortgang2["bruikbaar"] == 2
    assert voortgang2["compleet"] is True


def test_analyse_aggregeert_en_filtert_op_dagen():
    vergunningen = [
        {"gebied": "Delfshaven", "datum": "2026-08-10"},
        {"gebied": "Delfshaven", "datum": "2026-08-15"},
        {"gebied": "Charlois", "datum": "2026-07-01"},
        {"gebied": "Charlois", "datum": "2025-01-01"},
    ]
    volledig = vi.analyse(vergunningen, vandaag=date(2026, 8, 20))
    assert volledig["totaal"] == 4
    assert volledig["per_wijk"] == {"Delfshaven": 2, "Charlois": 2}
    assert volledig["per_jaar"] == {"2025": 1, "2026": 3}

    # Alleen de laatste 30 dagen: 10 + 15 aug (Delfshaven) vallen erin, rest niet.
    recent = vi.analyse(vergunningen, vandaag=date(2026, 8, 20), dagen=30)
    assert recent["totaal"] == 2
    assert recent["per_wijk"] == {"Delfshaven": 2}
