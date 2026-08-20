"""Tests voor rotterdam_scanner/bekendmakingen.py: het uitlezen van een adres uit
de titel van een officiële bekendmaking, de afstandsberekening, en de
favoriet-check die waarschuwingen toevoegt en per publicatie maar één keer meldt.
Er wordt nooit echt naar KOOP/PDOK gebeld (haal_recente_vergunningen wordt
gemockt)."""
from datetime import date

import pytest

from rotterdam_scanner import bekendmakingen
from rotterdam_scanner.bekendmakingen import Vergunning
from rotterdam_scanner.state import ListingState, StateStore


@pytest.mark.parametrize(
    "titel,verwacht",
    [
        ("Vergunning kamerverhuur Sint-Jacobstraat 99", "Sint-Jacobstraat 99"),
        ("Vergunning kamerverhuur C.P.Tielestraat 30B", "C.P.Tielestraat 30B"),
        ("Vergunning kamerverhuur Zuidhoek 101A - Rectificatie", "Zuidhoek 101A"),
        ("Vergunning kamerbewoning Hilledijk 291B-02", "Hilledijk 291B-02"),
    ],
)
def test_adres_uit_titel_haalt_adres_eruit(titel, verwacht):
    assert bekendmakingen._adres_uit_titel(titel) == verwacht


@pytest.mark.parametrize(
    "titel",
    [
        "Nadere regels voor kamerbewoning 2014",
        "Verordening samenstelling Woningvoorraad 2025",
        "Intrekking vergunning kamerverhuur Teststraat 1",
        "Vergunning kamerverhuur Teststraat 1 - geweigerd",
        "Aanvraag omgevingsvergunning kamerverhuur Teststraat 1",
    ],
)
def test_adres_uit_titel_slaat_niet_adres_titels_over(titel):
    assert bekendmakingen._adres_uit_titel(titel) is None


def test_pub_id_uit_url():
    assert (
        bekendmakingen._pub_id("https://zoek.officielebekendmakingen.nl/gmb-2026-65707.html")
        == "gmb-2026-65707"
    )


def test_afstand_meter_zelfde_punt_is_nul():
    assert bekendmakingen.afstand_meter(51.92, 4.45, 51.92, 4.45) == pytest.approx(0.0, abs=1e-6)


def test_afstand_meter_ordegrootte():
    # ~40 m verderop moet netjes binnen de 50 m-straal vallen; een paar honderd
    # meter ruim erbuiten.
    dichtbij = bekendmakingen.afstand_meter(51.9140, 4.4528, 51.91436, 4.4528)
    veraf = bekendmakingen.afstand_meter(51.9140, 4.4528, 51.9180, 4.4560)
    assert dichtbij < bekendmakingen.STRAAL_METER
    assert veraf > bekendmakingen.STRAAL_METER


def _favoriet(tmp_path, **overrides):
    defaults = dict(
        object_id="3023TD-1",
        url="https://www.funda.nl/koop/rotterdam/huis-1/",
        weergavenaam="C.P.Tielestraat 28, 3023TD Rotterdam",
        eerst_gezien="2026-08-01",
        laatst_gezien="2026-08-19",
        status="actief",
        lat=51.91402645,
        lon=4.45286674,
        favoriet=True,
    )
    defaults.update(overrides)
    state = StateStore(tmp_path / "state.json")
    state.upsert(ListingState(**defaults))
    state.save()
    return StateStore(tmp_path / "state.json")


def test_controleer_favorieten_voegt_waarschuwing_toe_binnen_50m(tmp_path, monkeypatch):
    state = _favoriet(tmp_path)
    # Vergunning op ~0 m (zelfde coördinaat als het favoriete pand) -> treffer.
    monkeypatch.setattr(
        bekendmakingen,
        "haal_recente_vergunningen",
        lambda *a, **k: [
            Vergunning(
                "gmb-2026-1", "Vergunning kamerverhuur C.P.Tielestraat 30B", "2026-08-12",
                "https://zoek.officielebekendmakingen.nl/gmb-2026-1.html", "C.P.Tielestraat 30B",
                "rotterdam", 51.91402645, 4.45286674,
            )
        ],
    )

    nieuw = bekendmakingen.controleer_favorieten(state, tmp_path / "cache.json", vandaag=date(2026, 8, 20))

    assert len(nieuw) == 1
    fav, waarschuwingen = nieuw[0]
    assert fav.object_id == "3023TD-1"
    assert waarschuwingen[0]["publicatie_id"] == "gmb-2026-1"
    assert waarschuwingen[0]["afstand_m"] == 0
    # Opgeslagen op de woning zelf.
    herladen = StateStore(tmp_path / "state.json").get("3023TD-1")
    assert len(herladen.bekendmaking_waarschuwingen) == 1


def test_controleer_favorieten_meldt_geen_dubbele(tmp_path, monkeypatch):
    state = _favoriet(tmp_path)
    monkeypatch.setattr(
        bekendmakingen,
        "haal_recente_vergunningen",
        lambda *a, **k: [
            Vergunning(
                "gmb-2026-1", "Vergunning kamerverhuur C.P.Tielestraat 30B", "2026-08-12",
                "https://zoek.officielebekendmakingen.nl/gmb-2026-1.html", "C.P.Tielestraat 30B",
                "rotterdam", 51.91402645, 4.45286674,
            )
        ],
    )

    eerste = bekendmakingen.controleer_favorieten(state, tmp_path / "cache.json", vandaag=date(2026, 8, 20))
    tweede = bekendmakingen.controleer_favorieten(
        StateStore(tmp_path / "state.json"), tmp_path / "cache.json", vandaag=date(2026, 8, 20)
    )

    assert len(eerste) == 1
    assert tweede == []  # zelfde publicatie -> geen nieuwe melding


def test_controleer_favorieten_negeert_vergunning_buiten_50m(tmp_path, monkeypatch):
    state = _favoriet(tmp_path)
    monkeypatch.setattr(
        bekendmakingen,
        "haal_recente_vergunningen",
        lambda *a, **k: [
            Vergunning(
                "gmb-2026-2", "Vergunning kamerverhuur Verweg 1", "2026-08-12",
                "https://zoek.officielebekendmakingen.nl/gmb-2026-2.html", "Verweg 1",
                "rotterdam", 51.9200, 4.4600,  # honderden meters verderop
            )
        ],
    )

    nieuw = bekendmakingen.controleer_favorieten(state, tmp_path / "cache.json", vandaag=date(2026, 8, 20))
    assert nieuw == []


def test_controleer_favorieten_zonder_favorieten_doet_niets(tmp_path, monkeypatch):
    state = _favoriet(tmp_path, favoriet=False)
    geroepen = []
    monkeypatch.setattr(
        bekendmakingen, "haal_recente_vergunningen", lambda *a, **k: geroepen.append(1) or []
    )
    nieuw = bekendmakingen.controleer_favorieten(state, tmp_path / "cache.json", vandaag=date(2026, 8, 20))
    assert nieuw == []
    assert geroepen == []  # geen favorieten -> geen (dure) KOOP-call


def test_bouw_alert_mail_bevat_pand_en_adres(tmp_path):
    state = _favoriet(tmp_path)
    fav = state.get("3023TD-1")
    waarschuwing = {
        "publicatie_id": "gmb-2026-1", "titel": "Vergunning kamerverhuur C.P.Tielestraat 30B",
        "datum": "2026-08-12", "url": "https://zoek.officielebekendmakingen.nl/gmb-2026-1.html",
        "adres": "C.P.Tielestraat 30B", "afstand_m": 25,
    }
    onderwerp, html, tekst = bekendmakingen.bouw_alert_mail([(fav, [waarschuwing])])
    assert "50 m" in onderwerp
    assert "C.P.Tielestraat 30B" in html
    assert "C.P.Tielestraat 30B" in tekst
    assert fav.weergavenaam in html
