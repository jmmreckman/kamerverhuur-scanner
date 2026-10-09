"""Tests voor de concurrentie-scan (trechter): de pure logica met geïnjecteerde fakes
(geen echte PDOK/WOZ/BAG/ArcGIS-calls), de mailopbouw, en de /opkoop-scan-route
(beheerder-only, ontvanger-veld, achtergrond-scan + mail)."""
import pytest

from kansen_site import app as kansen_app
from rotterdam_scanner import geocode, opkoop_scan
from rotterdam_scanner.config import Config


def _nabij(naam, afstand, nid, *, aobj="a", rd=(0.0, 0.0), buurt="Oud Charlois"):
    return geocode.NabijAdres(
        weergavenaam=naam, afstand_m=afstand, nummeraanduiding_id=nid,
        adresseerbaarobject_id=aobj, rd_x=rd[0], rd_y=rd[1], buurtnaam=buurt,
    )


# --- Pure trechter-logica ---

def test_trechter_volledige_funnel():
    woz = {"1": 300_000, "2": 600_000, "3": 600_000, "4": 650_000}
    binnen = {"1": False, "2": True, "3": False, "4": False}
    # elk adres een unieke rd zodat de vergunning_func per adres te keyen is
    adressen = [
        _nabij("A 1", 5, "1", rd=(1.0, 1.0)),
        _nabij("B 2", 10, "2", rd=(2.0, 2.0)),
        _nabij("C 3", 15, "3", rd=(3.0, 3.0)),
        _nabij("D 4", 20, "4", rd=(4.0, 4.0)),
    ]
    rd_naar_nid = {(a.rd_x, a.rd_y): a.nummeraanduiding_id for a in adressen}

    r = opkoop_scan.scan(
        52.0, 4.0, 470_000, "Centrum 1", pauze_s=0,
        adres_func=lambda lat, lon, straal: adressen,
        woz_func=lambda nid: woz[nid],
        vergunning_func=lambda rx, ry: binnen[rd_naar_nid[(rx, ry)]],
        beschermde_wijk_func=lambda naam: True,
        bag_func=lambda aobj: 80,
    )
    assert [a.weergavenaam for a in r.afgevallen_opkoop] == ["A 1"]       # WOZ <= grens
    assert [a.weergavenaam for a in r.afgevallen_50m] == ["B 2"]          # binnen 50m
    assert {a.weergavenaam for a in r.pool} == {"C 3", "D 4"}             # overgebleven
    assert r.woz_onbereikbaar is False
    assert r.gis_onbereikbaar is False


def test_niet_in_opkoopwijk_slaat_woz_over():
    adressen = [_nabij("A 1", 5, "1", rd=(1.0, 1.0)), _nabij("B 2", 10, "2", rd=(2.0, 2.0))]
    woz_calls = []

    r = opkoop_scan.scan(
        52.0, 4.0, 470_000, "Centrum 1", pauze_s=0,
        adres_func=lambda lat, lon, straal: adressen,
        woz_func=lambda nid: woz_calls.append(nid) or 100,
        vergunning_func=lambda rx, ry: False,
        beschermde_wijk_func=lambda naam: False,  # niet beschermd
        bag_func=lambda aobj: 80,
    )
    assert r.in_opkoopwijk is False
    assert r.afgevallen_opkoop == []
    assert woz_calls == []          # geen WOZ opgevraagd buiten een beschermde wijk
    assert len(r.pool) == 2


def test_te_koop_func_markeert_pool():
    adressen = [_nabij("A 1", 5, "1", rd=(1.0, 1.0))]
    r = opkoop_scan.scan(
        52.0, 4.0, 470_000, "Centrum 1", pauze_s=0,
        adres_func=lambda lat, lon, straal: adressen,
        woz_func=lambda nid: 600_000,
        vergunning_func=lambda rx, ry: False,
        beschermde_wijk_func=lambda naam: True,
        bag_func=lambda aobj: 80,
        te_koop_func=lambda naam, grens: "2026-05-01",
    )
    assert r.archief_doorzocht is True
    assert [a.weergavenaam for a in r.pool_te_koop_geweest] == ["A 1"]
    assert r.pool[0].te_koop_laatst == "2026-05-01"


def test_pool_te_klein_markering():
    bag = {"a1": 60, "a2": 90}
    adressen = [
        _nabij("A 1", 5, "1", aobj="a1", rd=(1.0, 1.0)),
        _nabij("B 2", 10, "2", aobj="a2", rd=(2.0, 2.0)),
    ]
    r = opkoop_scan.scan(
        52.0, 4.0, 470_000, "Centrum 1", pauze_s=0, m2_grens=72,
        adres_func=lambda lat, lon, straal: adressen,
        woz_func=lambda nid: 600_000,
        vergunning_func=lambda rx, ry: False,
        beschermde_wijk_func=lambda naam: True,
        bag_func=lambda aobj: bag[aobj],
    )
    assert [a.weergavenaam for a in r.pool_te_klein] == ["A 1"]  # 60 < 72, 90 niet


def test_woz_onbereikbaar_als_alles_none_in_opkoopwijk():
    adressen = [_nabij("A 1", 5, "1", rd=(1.0, 1.0))]
    r = opkoop_scan.scan(
        52.0, 4.0, 470_000, "Centrum 1", pauze_s=0,
        adres_func=lambda lat, lon, straal: adressen,
        woz_func=lambda nid: None,
        vergunning_func=lambda rx, ry: False,
        beschermde_wijk_func=lambda naam: True,
        bag_func=lambda aobj: 80,
    )
    assert r.woz_onbereikbaar is True


def test_gis_onbereikbaar_als_alles_none():
    adressen = [_nabij("A 1", 5, "1", rd=(1.0, 1.0))]
    r = opkoop_scan.scan(
        52.0, 4.0, 470_000, "Centrum 1", pauze_s=0,
        adres_func=lambda lat, lon, straal: adressen,
        woz_func=lambda nid: 600_000,
        vergunning_func=lambda rx, ry: None,  # ArcGIS onbereikbaar
        beschermde_wijk_func=lambda naam: True,
        bag_func=lambda aobj: 80,
    )
    assert r.gis_onbereikbaar is True
    assert len(r.pool) == 1  # op onzekerheid sluiten we niet uit


def test_bouw_mail_bevat_trechter_en_kanttekening():
    adressen = [
        _nabij("A 1", 5, "1", rd=(1.0, 1.0)),
        _nabij("C 3", 15, "3", rd=(3.0, 3.0)),
    ]
    woz = {"1": 300_000, "3": 600_000}
    r = opkoop_scan.scan(
        52.0, 4.0, 470_000, "Pompstraat 42, Rotterdam", pauze_s=0,
        adres_func=lambda lat, lon, straal: adressen,
        woz_func=lambda nid: woz[nid],
        vergunning_func=lambda rx, ry: False,
        beschermde_wijk_func=lambda naam: True,
        bag_func=lambda aobj: 80,
    )
    onderwerp, html, text = opkoop_scan.bouw_mail(r)
    assert "Pompstraat 42, Rotterdam" in onderwerp
    assert "mogelijke adressen" in onderwerp
    assert "TRECHTER" in text
    assert "14 weken" in text                 # kanttekening over aanvragen
    assert "Pool" in html


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


def _login(client):
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})


def _fake_geocode(adres):
    return geocode.GeocodeResult(
        weergavenaam="Pompstraat 42, Rotterdam", straatnaam="Pompstraat",
        huisnummer="42", postcode="3000AA", woonplaats="Rotterdam",
        rotterdam_wijk="Oud Charlois", cbs_wijknaam="Charlois",
        rd_x=0.0, rd_y=0.0, lon=4.0, lat=52.0,
        nummeraanduiding_id="42", adresseerbaarobject_id="42",
    )


class _DirecteThread:
    def __init__(self, target=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


def test_opkoop_scan_zonder_login_geen_toegang(client):
    resp = client.post("/opkoop-scan", json={"adres": "Pompstraat 42, Rotterdam"})
    assert resp.status_code in (302, 401, 403)


def test_opkoop_scan_zonder_adres_geeft_fout(client):
    _login(client)
    resp = client.post("/opkoop-scan", json={"adres": "   "})
    assert resp.status_code == 400
    assert "fout" in resp.get_json()


def test_opkoop_scan_ongeldig_emailadres_geeft_fout(client):
    _login(client)
    resp = client.post("/opkoop-scan", json={"adres": "Pompstraat 42", "ontvangers": "jan@"})
    assert resp.status_code == 400
    assert "Ongeldig" in resp.get_json()["fout"]


def test_opkoop_scan_mailt_naar_opgegeven_ontvangers_zonder_bcc(client, monkeypatch):
    _login(client)
    verzonden = {}

    def _fake_scan(lat, lon, grens, centrum, **kw):
        return opkoop_scan.ScanResultaat(centrum, 50.0, grens, 72, "Oud Charlois", True, [])

    def _fake_send_mail(config, subject, html_body, text_body, recipients=None, stille_bcc=True):
        verzonden["recipients"] = recipients
        verzonden["stille_bcc"] = stille_bcc

    monkeypatch.setattr(kansen_app.geocode, "geocode_vrij_landelijk", _fake_geocode)
    monkeypatch.setattr(kansen_app.opkoop_scan, "scan", _fake_scan)
    monkeypatch.setattr(kansen_app, "send_mail", _fake_send_mail)
    monkeypatch.setattr(kansen_app.threading, "Thread", _DirecteThread)

    resp = client.post("/opkoop-scan", json={
        "adres": "Pompstraat 42, Rotterdam",
        "ontvangers": "een@x.nl, twee@y.nl",
    })
    assert resp.status_code == 200
    assert verzonden["recipients"] == ["een@x.nl", "twee@y.nl"]
    assert verzonden["stille_bcc"] is False
    data = resp.get_json()
    assert "een@x.nl" in data["melding"] and "twee@y.nl" in data["melding"]


def test_opkoop_scan_leeg_ontvanger_valt_terug_op_report_to(client, monkeypatch):
    _login(client)
    verzonden = {}

    def _fake_scan(lat, lon, grens, centrum, **kw):
        return opkoop_scan.ScanResultaat(centrum, 50.0, grens, 72, "Oud Charlois", True, [])

    monkeypatch.setattr(kansen_app.geocode, "geocode_vrij_landelijk", _fake_geocode)
    monkeypatch.setattr(kansen_app.opkoop_scan, "scan", _fake_scan)
    monkeypatch.setattr(kansen_app, "send_mail",
                        lambda *a, recipients=None, stille_bcc=True, **k: verzonden.update(recipients=recipients))
    monkeypatch.setattr(kansen_app.threading, "Thread", _DirecteThread)

    resp = client.post("/opkoop-scan", json={"adres": "Pompstraat 42, Rotterdam"})
    assert resp.status_code == 200
    assert verzonden["recipients"] == ["a@example.com"]  # config.report_to


def test_opkoop_scan_fout_tijdens_scan_stuurt_foutmail(client, monkeypatch):
    _login(client)
    mails = []

    def _kapotte_scan(*a, **kw):
        raise RuntimeError("PDOK down")

    monkeypatch.setattr(kansen_app.geocode, "geocode_vrij_landelijk", _fake_geocode)
    monkeypatch.setattr(kansen_app.opkoop_scan, "scan", _kapotte_scan)
    monkeypatch.setattr(kansen_app, "send_mail",
                        lambda config, subject, h, t, recipients=None, stille_bcc=True: mails.append((subject, recipients, stille_bcc)))
    monkeypatch.setattr(kansen_app.threading, "Thread", _DirecteThread)

    resp = client.post("/opkoop-scan", json={"adres": "Pompstraat 42", "ontvangers": "x@y.nl"})
    assert resp.status_code == 200
    assert len(mails) == 1
    onderwerp, ontvangers, stille_bcc = mails[0]
    assert "MISLUKT" in onderwerp
    assert ontvangers == ["x@y.nl"]
    assert stille_bcc is False
