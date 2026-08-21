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


# Oudere vrije-tekst format (2019-2020): geen Gebied:/Adres:-labels, getal als woord.
_BODY_2019 = """
<p>Het college maakt bekend dat zij op 20 mei 2019 de volgende vergunning heeft verleend
(op basis van artikel 21 van de Huisvestingswet 2014). Vergunning voor kamerbewoning door
maximaal vier personen voor de woning met adres Schiedamseweg Beneden 481 C, 3028 BN
Rotterdam/Delfshaven. Zaaknummer: 109736-2019.</p>
"""

# 2021 gestructureerd, maar met "Datum besluit:" i.p.v. "Verzenddatum besluit:".
_BODY_2021 = """
<p>maakt bekend dat zij de volgende vergunning voor kamerbewoning heeft verleend.
Gebied: Kralingen-Crooswijk Adres: Charlotte de Bourbonlaan 33B Postcode: 3062 GC
Datum besluit: 17 augustus 2021 Zaaknummer: 437973-2021
Activiteit: vergunning kamerverhuur aan 6 personen</p>
"""


def test_parse_body_vrije_tekst_2019():
    velden = vi.parse_body(_BODY_2019)
    assert velden["adres"] == "Schiedamseweg Beneden 481 C"
    assert velden["postcode"] == "3028BN"
    assert velden["gebied"] == "Delfshaven"
    assert velden["aantal_personen"] == 4
    assert velden["besluitdatum"] == "2019-05-20"


def test_parse_body_datum_besluit_2021():
    velden = vi.parse_body(_BODY_2021)
    assert velden["gebied"] == "Kralingen-Crooswijk"
    assert velden["adres"] == "Charlotte de Bourbonlaan 33B"
    assert velden["aantal_personen"] == 6
    assert velden["besluitdatum"] == "2021-08-17"


# 2021 "bestaande situatie"-grant: body heeft wél "Gebied:" maar géén "Adres:";
# het adres staat alleen in de titel.
_BODY_2021_TITELADRES = """
<p>Het college maakt bekend dat zij de volgende vergunning voor kamerbewoning heeft verleend
voor maximaal 3 personen voor een bestaande situatie van kamerbewoning onder de overgangsbepaling.
Gebied: Delfshaven Datum besluit: 4 november 2021 Dossiernummer: 57944</p>
"""


def test_parse_body_adres_uit_titel_als_body_geen_adres_heeft():
    velden = vi.parse_body(_BODY_2021_TITELADRES, "Verleende vergunning kamerbewoning Osseweistraat 38B")
    assert velden["adres"] == "Osseweistraat 38B"
    assert velden["gebied"] == "Delfshaven"
    assert velden["aantal_personen"] == 3
    assert velden["besluitdatum"] == "2021-11-04"


def test_parse_body_zonder_adres_en_zonder_titel_geeft_none():
    assert vi.parse_body(_BODY_2021_TITELADRES) is None


@pytest.mark.parametrize("titel,verwacht", [
    ("Vergunning kamerverhuur Sint-Jacobstraat 99", "Sint-Jacobstraat 99"),
    ("Verleende vergunning kamerbewoning Osseweistraat 38B", "Osseweistraat 38B"),
    ("verleende vergunning voor kamerbewoning Bergweg 183", "Bergweg 183"),
    ("kamerverhuur Schiedamseweg Beneden 481C", "Schiedamseweg Beneden 481C"),
    ("Vergunning kamerverhuur Zuidhoek 101A - Rectificatie", "Zuidhoek 101A"),
    ("Vergunning kamerbewoning onder de overgangsbepaling voor bestaande situaties", None),
])
def test_adres_uit_titel(titel, verwacht):
    assert vi._adres_uit_titel(titel) == verwacht


def test_parse_body_aanvraag_zonder_verleend_geeft_none():
    # Een aanvraag (nog niet verleend) mag niet als vergunning meetellen.
    aanvraag = "<p>Aangevraagde omgevingsvergunning voor kamerbewoning. Adres: Teststraat 1 Postcode: 3000 AA</p>"
    assert vi.parse_body(aanvraag) is None


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


def test_werk_bij_herinventariseert_bij_versiewijziging(tmp_path, monkeypatch):
    # Simuleer een index gebouwd met een oudere enumeratie-versie: één publicatie is
    # eerder als "niet bruikbaar" afgeschreven. Na een versiewijziging moet die een
    # herkansing krijgen (verwerkt terug op False) en de versie worden bijgewerkt.
    import json

    index_path = tmp_path / "vergunningen_index.json"
    index_path.write_text(json.dumps({
        "meta": {"volledige_enumeratie_gedaan": True, "enumeratie_versie": 1},
        "vergunningen": {
            "gmb-oud-1": {"publicatie_id": "gmb-oud-1", "titel": "Vergunning kamerverhuur X 1",
                          "html_url": "u", "verwerkt": True, "bruikbaar": False},
        },
    }), encoding="utf-8")

    monkeypatch.setattr(vi, "enumereer_stubs", lambda vanaf=None: {})

    def _fake_verwerk(stub):
        stub["verwerkt"] = True
        stub["bruikbaar"] = True
        stub["gebied"] = "Delfshaven"
        stub["adres"] = "X 1"

    monkeypatch.setattr(vi, "_verwerk_stub", _fake_verwerk)

    voortgang = vi.werk_bij(index_path, batch=5, vandaag=date(2026, 8, 20))
    # De eerder-mislukte publicatie is opnieuw geprobeerd en nu bruikbaar.
    assert voortgang["bruikbaar"] == 1
    index = vi.VergunningIndex(index_path)
    assert index.meta["enumeratie_versie"] == vi._ENUMERATIE_VERSIE


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


@pytest.mark.parametrize("waarde,verwacht", [
    ("Delfshaven", "Delfshaven"),
    ("Kralingen-Crooswijk", "Kralingen-Crooswijk"),
    ("kralingen crooswijk", "Kralingen-Crooswijk"),   # spelling/koppelteken
    ("IJsselmonde", "IJsselmonde"),
    ("Centrum/Stadsdriehoek", "Centrum"),             # gebied/wijk -> gebied
    ("Nieuwe Westen", "Delfshaven"),                   # cbs-wijk -> gebied
    ("Beverwaard", "IJsselmonde"),
    ("Carnisse", "Charlois"),
    ("'s-Gravenland", "Prins Alexander"),
    ("Schiebroek", "Hillegersberg-Schiebroek"),
    ("", "Onbekend"),
    (None, "Onbekend"),
    ("Onbestaandiets", "Overig"),
])
def test_normaliseer_gebied(waarde, verwacht):
    assert vi.normaliseer_gebied(waarde) == verwacht


def test_normaliseer_gebied_dekt_14_gebieden():
    # Elk officieel gebied moet één-op-één op zichzelf normaliseren.
    for g in vi.GEBIEDEN:
        assert vi.normaliseer_gebied(g) == g
    assert len(vi.GEBIEDEN) == 14


# "Bestaande situatie onder de overgangsbepaling"-grant: per-adres, body gebruikt
# "Straat:" i.p.v. "Adres:", en de titel bevat "overgangsbepaling" (mag niet meer
# worden uitgesloten).
_BODY_OVERGANG = """
<p>maakt bekend dat zij de volgende vergunning voor kamerbewoning heeft verleend
(artikel 21 van de Huisvestingswet 2014). Gebied: Delfshaven Straat: Ruilstraat 26A-01
Postcode: 3023 XS Activiteit: vergunning kamerverhuur aan 4 personen
Datum besluit: 23 december 2022 Zaaknummer: 123456-2022</p>
"""
_TITEL_OVERGANG = ("Vergunning kamerbewoning onder de overgangsbepaling voor "
                   "bestaande situaties van kamerbewoning Ruilstraat 26A-01")


def test_overgangsbepaling_titel_wordt_niet_uitgesloten():
    assert not vi._UITSLUIT_RE.search(_TITEL_OVERGANG)
    assert vi._KANDIDAAT_RE.search(_TITEL_OVERGANG)


def test_parse_body_leest_straat_label_bestaande_situatie():
    velden = vi.parse_body(_BODY_OVERGANG, _TITEL_OVERGANG)
    assert velden["gebied"] == "Delfshaven"
    assert velden["adres"] == "Ruilstraat 26A-01"
    assert velden["postcode"] == "3023XS"
    assert velden["aantal_personen"] == 4
    assert velden["besluitdatum"] == "2022-12-23"
