"""Tests voor de opkoopbescherming-scan: de pure teloglica (ScanResultaat +
scan() met geïnjecteerde fakes, dus zonder echte PDOK/WOZ-calls), de opbouw van
de resultaatmail, en de /opkoop-scan-route (beheerder-only, start een
achtergrond-scan en mailt het resultaat)."""
import json

import pytest

from kansen_site import app as kansen_app
from rotterdam_scanner import geocode, opkoop_scan
from rotterdam_scanner.config import Config


# --- Pure logica: scan() + ScanResultaat ---

def _nabij(naam, afstand, nid):
    return geocode.NabijAdres(weergavenaam=naam, afstand_m=afstand, nummeraanduiding_id=nid)


def test_scan_verdeelt_adressen_boven_onder_en_onbekend():
    adressen = [
        _nabij("A 1", 5, "1"),   # boven
        _nabij("B 2", 10, "2"),  # onder
        _nabij("C 3", 15, "3"),  # precies op de grens -> onder (<=)
        _nabij("D 4", 20, "4"),  # geen WOZ -> onbekend
    ]
    woz = {"1": 600_000, "2": 300_000, "3": 470_000, "4": None}

    r = opkoop_scan.scan(
        lat=52.0, lon=4.0, grens=470_000, centrum_adres="Testcentrum 1",
        pauze_s=0,  # geen sleep in de test
        woz_func=lambda nid: woz[nid],
        adres_func=lambda lat, lon, straal: adressen,
    )

    assert len(r.adressen) == 4
    assert [a.weergavenaam for a in r.boven] == ["A 1"]
    assert {a.weergavenaam for a in r.onder} == {"B 2", "C 3"}
    assert [a.weergavenaam for a in r.onbekend] == ["D 4"]
    assert len(r.met_woz) == 3
    # percentages tellen alleen de adressen mét WOZ: 1 van 3 boven, 2 van 3 onder.
    assert r.pct_boven == pytest.approx(33.3)
    assert r.pct_onder == pytest.approx(66.7)


def test_scan_zonder_adressen_geeft_geen_deling_door_nul():
    r = opkoop_scan.scan(
        lat=52.0, lon=4.0, grens=470_000, centrum_adres="Leeg 1",
        pauze_s=0, woz_func=lambda nid: None, adres_func=lambda lat, lon, straal: [],
    )
    assert r.adressen == []
    assert r.pct_boven == 0.0
    assert r.pct_onder == 0.0


def test_scan_geeft_straal_door_aan_adres_func():
    gezien = {}

    def _adres_func(lat, lon, straal):
        gezien["straal"] = straal
        return []

    opkoop_scan.scan(52.0, 4.0, 470_000, "X 1", straal_m=75.0, pauze_s=0,
                     woz_func=lambda nid: None, adres_func=_adres_func)
    assert gezien["straal"] == 75.0


def test_bouw_mail_bevat_aantallen_en_adreslijsten():
    r = opkoop_scan.ScanResultaat(
        centrum_adres="Pompstraat 42, Rotterdam", straal_m=50.0, grens=470_000,
        adressen=[
            opkoop_scan.AdresResultaat("Pompstraat 44", 8.0, 600_000),
            opkoop_scan.AdresResultaat("Pompstraat 40", 12.0, 300_000),
            opkoop_scan.AdresResultaat("Pompstraat 46", 20.0, None),
        ],
    )
    onderwerp, html, text = opkoop_scan.bouw_mail(r)

    assert "Pompstraat 42, Rotterdam" in onderwerp
    assert "1 boven / 1 onder" in onderwerp
    # grens netjes geformatteerd als euro's met duizendtalpunt
    assert "€470.000" in text
    # elk adres komt terug in de tekstmail
    for naam in ("Pompstraat 44", "Pompstraat 40", "Pompstraat 46"):
        assert naam in text
        assert naam in html
    # het onbekende adres telt niet mee in de percentages maar staat wel in de mail
    assert "onbekend" in text.lower()


# --- Route: /opkoop-scan ---

def _config(tmp_path, **overrides):
    defaults = dict(
        gmail_address="scanner@example.com",
        gmail_app_password="gmail-pw",
        report_to=["a@example.com"],
        funda_mail_folder="INBOX",
        listing_expiry_days=30,
        opkoopbescherming_woz_grens=470_000,
        state_path=tmp_path / "state.json",
        kansen_app_users={"jurian": "geheim123", "justin": "anderwachtwoord"},
        kansen_app_beheerders={"jurian"},
        kansen_app_secret_key="test-secret",
    )
    defaults.update(overrides)
    return Config(**defaults)


@pytest.fixture
def client(tmp_path):
    app = kansen_app.create_app(_config(tmp_path))
    app.testing = True
    return app.test_client()


def test_opkoop_scan_zonder_login_geen_toegang(client):
    resp = client.post("/opkoop-scan", json={"adres": "Pompstraat 42, Rotterdam"})
    assert resp.status_code in (302, 401, 403)


def test_opkoop_scan_zonder_adres_geeft_fout(client):
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = client.post("/opkoop-scan", json={"adres": "   "})
    assert resp.status_code == 400
    assert "fout" in resp.get_json()


def test_opkoop_scan_start_en_mailt(client, monkeypatch):
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    # Geen echte PDOK/WOZ/mail: alles wordt vervangen door fakes.
    def _fake_geocode(adres):
        return geocode.GeocodeResult(
            weergavenaam="Pompstraat 42, Rotterdam", straatnaam="Pompstraat",
            huisnummer="42", postcode="3000AA", woonplaats="Rotterdam",
            rotterdam_wijk="Middelland", cbs_wijknaam="Delfshaven",
            rd_x=0.0, rd_y=0.0, lon=4.0, lat=52.0,
            nummeraanduiding_id="42", adresseerbaarobject_id="42",
        )

    verstuurd = {}

    def _fake_scan(lat, lon, grens, centrum, **kw):
        return opkoop_scan.ScanResultaat(centrum, 50.0, grens, [])

    def _fake_send_mail(config, subject, html_body, text_body, recipients=None):
        verstuurd["onderwerp"] = subject
        verstuurd["ontvangers"] = recipients

    # De scan draait normaal in een achtergrond-thread; in de test laten we 'm
    # synchroon lopen zodat de fakes nog actief zijn (anders zou de thread ná de
    # monkeypatch-teardown alsnog een echte PDOK/WOZ-call kunnen doen).
    class _DirecteThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(kansen_app.geocode, "geocode_vrij_landelijk", _fake_geocode)
    monkeypatch.setattr(kansen_app.opkoop_scan, "scan", _fake_scan)
    monkeypatch.setattr(kansen_app, "send_mail", _fake_send_mail)
    monkeypatch.setattr(kansen_app.threading, "Thread", _DirecteThread)

    resp = client.post("/opkoop-scan", json={"adres": "Pompstraat 42, Rotterdam"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "jmmreckman@gmail.com" in data["melding"]
    assert verstuurd["ontvangers"] == ["jmmreckman@gmail.com"]
    assert "Pompstraat 42, Rotterdam" in verstuurd["onderwerp"]


def test_opkoop_scan_onvindbaar_adres_geeft_nette_fout(client, monkeypatch):
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    def _raise(adres):
        raise geocode.GeocodeError("niet gevonden")

    monkeypatch.setattr(kansen_app.geocode, "geocode_vrij_landelijk", _raise)
    resp = client.post("/opkoop-scan", json={"adres": "bestaat niet 999"})
    assert resp.status_code == 400
    assert "fout" in resp.get_json()
