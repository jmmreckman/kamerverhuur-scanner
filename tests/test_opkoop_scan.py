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
        bag_func=lambda aobj: (80, "woonfunctie"),
    )
    assert [a.weergavenaam for a in r.afgevallen_opkoop] == ["A 1"]       # WOZ <= grens
    assert [a.weergavenaam for a in r.afgevallen_50m] == ["B 2"]          # binnen 50m
    assert {a.weergavenaam for a in r.pool} == {"C 3", "D 4"}             # overgebleven
    assert r.woz_onbereikbaar is False
    assert r.gis_onbereikbaar is False


def test_centrumadres_wordt_uitgesloten():
    adressen = [
        _nabij("Pompstraat 42, 3082RT Rotterdam", 0, "1", aobj="a1", rd=(1.0, 1.0)),  # centrum
        _nabij("Pompstraat 44, 3082RT Rotterdam", 8, "2", aobj="a2", rd=(2.0, 2.0)),  # buur
    ]
    woz_calls = []
    r = opkoop_scan.scan(
        52.0, 4.0, 470_000, "Pompstraat 42, 3082RT Rotterdam", pauze_s=0,
        adres_func=lambda lat, lon, straal: adressen,
        woz_func=lambda nid: woz_calls.append(nid) or 600_000,
        vergunning_func=lambda rx, ry: False,
        beschermde_wijk_func=lambda naam: True,
        bag_func=lambda aobj: (95, "woonfunctie"),
    )
    # Het centrumadres staat apart en NIET in de pool/risico's.
    assert [a.weergavenaam for a in r.centrum_rijen] == ["Pompstraat 42, 3082RT Rotterdam"]
    assert [a.weergavenaam for a in r.pool_reeel] == ["Pompstraat 44, 3082RT Rotterdam"]
    assert all("42" not in a.weergavenaam for a in r.pool)
    assert "1" not in woz_calls  # geen WOZ-call voor het uitgesloten centrumadres


def test_niet_in_opkoopwijk_slaat_woz_over():
    adressen = [_nabij("A 1", 5, "1", rd=(1.0, 1.0)), _nabij("B 2", 10, "2", rd=(2.0, 2.0))]
    woz_calls = []

    r = opkoop_scan.scan(
        52.0, 4.0, 470_000, "Centrum 1", pauze_s=0,
        adres_func=lambda lat, lon, straal: adressen,
        woz_func=lambda nid: woz_calls.append(nid) or 100,
        vergunning_func=lambda rx, ry: False,
        beschermde_wijk_func=lambda naam: False,  # niet beschermd
        bag_func=lambda aobj: (80, "woonfunctie"),
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
        bag_func=lambda aobj: (80, "woonfunctie"),
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
        bag_func=lambda aobj: (bag[aobj], "woonfunctie"),
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
        bag_func=lambda aobj: (80, "woonfunctie"),
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
        bag_func=lambda aobj: (80, "woonfunctie"),
    )
    assert r.gis_onbereikbaar is True
    assert len(r.pool) == 1  # op onzekerheid sluiten we niet uit


def test_ander_gebruiksdoel_gaat_naar_zeer_onwaarschijnlijk():
    adressen = [
        _nabij("Woning 1", 5, "1", aobj="aw", rd=(1.0, 1.0)),
        _nabij("Winkel 2", 10, "2", aobj="ak", rd=(2.0, 2.0)),
    ]
    doelen = {"aw": (90, "woonfunctie"), "ak": (120, "winkelfunctie")}
    r = opkoop_scan.scan(
        52.0, 4.0, 470_000, "Centrum 1", pauze_s=0,
        adres_func=lambda lat, lon, straal: adressen,
        woz_func=lambda nid: None,            # geen WOZ (niet-woning geeft sowieso geen WOZ)
        vergunning_func=lambda rx, ry: False,
        beschermde_wijk_func=lambda naam: False,  # niet beschermd -> opkoop doet niks
        bag_func=lambda aobj: doelen[aobj],
    )
    assert [a.weergavenaam for a in r.zeer_onwaarschijnlijk] == ["Winkel 2"]
    assert "winkelfunctie" in r.zeer_onwaarschijnlijk[0].reden_afgevallen
    assert [a.weergavenaam for a in r.pool_reeel] == ["Woning 1"]
    assert r.zeer_onwaarschijnlijk[0] not in r.pool


def test_grootste_risicos_is_reeel_en_te_koop_geweest():
    adressen = [
        _nabij("Risico 1", 5, "1", aobj="a1", rd=(1.0, 1.0)),   # reeel + te koop
        _nabij("Rustig 2", 10, "2", aobj="a2", rd=(2.0, 2.0)),  # reeel, niet te koop
        _nabij("Klein 3", 12, "3", aobj="a3", rd=(3.0, 3.0)),   # te koop maar te klein
    ]
    opp = {"a1": (95, "woonfunctie"), "a2": (120, "woonfunctie"), "a3": (50, "woonfunctie")}
    tk = {
        "Risico 1": {"sinds": "2026-03-01", "tot": "2026-07-01", "prijs": 365_000,
                     "bron": "funda, nvm", "url": "https://funda.nl/x", "status": "afgevallen"},
        "Klein 3": {"sinds": "2026-05-01", "tot": "2026-06-01", "prijs": 200_000,
                    "bron": "funda", "url": None, "status": "afgevallen"},
    }
    r = opkoop_scan.scan(
        52.0, 4.0, 470_000, "Centrum 1", pauze_s=0,
        adres_func=lambda lat, lon, straal: adressen,
        woz_func=lambda nid: 600_000,
        vergunning_func=lambda rx, ry: False,
        beschermde_wijk_func=lambda naam: True,
        bag_func=lambda aobj: opp[aobj],
        te_koop_func=lambda naam, grens: tk.get(naam),
    )
    # alleen Risico 1 is én reëel (>=72) én te koop geweest; Klein 3 valt in te-klein
    assert [a.weergavenaam for a in r.grootste_risicos] == ["Risico 1"]
    risico = r.grootste_risicos[0]
    assert risico.te_koop_sinds == "2026-03-01"
    assert risico.te_koop_laatst == "2026-07-01"
    assert risico.te_koop_prijs == 365_000
    assert risico.te_koop_bron == "funda, nvm"
    assert risico.te_koop_url == "https://funda.nl/x"


def test_nu_te_koop_sorteert_bovenaan():
    adressen = [
        _nabij("Verkocht recent", 5, "1", aobj="a1", rd=(1.0, 1.0)),
        _nabij("Nu te koop ouder", 8, "2", aobj="a2", rd=(2.0, 2.0)),
    ]
    tk = {
        "Verkocht recent": {"sinds": "2026-07-01", "tot": "2026-09-01", "prijs": None,
                            "bron": "funda", "url": None, "status": "afgevallen"},
        "Nu te koop ouder": {"sinds": "2026-02-01", "tot": "2026-06-01", "prijs": None,
                             "bron": "funda", "url": None, "status": "actief"},
    }
    r = opkoop_scan.scan(
        52.0, 4.0, 470_000, "Centrum 1", pauze_s=0,
        adres_func=lambda lat, lon, straal: adressen,
        woz_func=lambda nid: 600_000, vergunning_func=lambda rx, ry: False,
        beschermde_wijk_func=lambda naam: True, bag_func=lambda aobj: (90, "woonfunctie"),
        te_koop_func=lambda naam, grens: tk.get(naam),
    )
    # 'Nu te koop' staat bovenaan ondanks oudere datum (actief = scherpste risico).
    assert [a.weergavenaam for a in r.grootste_risicos] == ["Nu te koop ouder", "Verkocht recent"]
    assert r.grootste_risicos[0].nu_te_koop is True
    assert r.grootste_risicos[1].nu_te_koop is False


def test_bouw_rapport_pdf_met_grootste_risicos_rendert():
    from kansen_site import opkoop_rapport_pdf
    adressen = [_nabij("Risico 1", 5, "1", aobj="a1", rd=(1.0, 1.0))]
    r = opkoop_scan.scan(
        52.0, 4.0, 470_000, "Pompstraat 42, Rotterdam", pauze_s=0,
        adres_func=lambda lat, lon, straal: adressen,
        woz_func=lambda nid: 600_000,
        vergunning_func=lambda rx, ry: False,
        beschermde_wijk_func=lambda naam: True,
        bag_func=lambda aobj: (95, "woonfunctie"),
        te_koop_func=lambda naam, grens: {"sinds": "2026-03-01", "tot": "2026-07-01",
                                          "prijs": 365_000, "bron": "funda", "url": "https://funda.nl/x",
                                          "status": "afgevallen"},
    )
    assert len(r.grootste_risicos) == 1
    pdf = opkoop_rapport_pdf.bouw_rapport_pdf(r)
    assert pdf.startswith(b"%PDF") and len(pdf) > 1000


def test_pool_splitst_in_reeel_en_te_klein():
    adressen = [
        _nabij("Groot 1", 5, "1", aobj="ag", rd=(1.0, 1.0)),
        _nabij("Klein 2", 10, "2", aobj="ak", rd=(2.0, 2.0)),
    ]
    opp = {"ag": (95, "woonfunctie"), "ak": (55, "woonfunctie")}
    r = opkoop_scan.scan(
        52.0, 4.0, 470_000, "Centrum 1", pauze_s=0, m2_grens=72,
        adres_func=lambda lat, lon, straal: adressen,
        woz_func=lambda nid: 600_000,
        vergunning_func=lambda rx, ry: False,
        beschermde_wijk_func=lambda naam: True,
        bag_func=lambda aobj: opp[aobj],
    )
    assert [a.weergavenaam for a in r.pool_reeel] == ["Groot 1"]
    assert [a.weergavenaam for a in r.pool_te_klein] == ["Klein 2"]
    # beide zitten nog in de pool (te klein is geen harde uitsluiting)
    assert {a.weergavenaam for a in r.pool} == {"Groot 1", "Klein 2"}


def test_woz_func_wordt_herhaald_bij_transiente_fout():
    # Simuleer twee time-outs, dan succes: de echte _veilige_woz retryt en vindt 'm alsnog.
    import requests
    from rotterdam_scanner import woz as woz_mod

    pogingen = {"n": 0}

    class _Waarde:
        bedrag = 400_000

    def _flaky(nid):
        pogingen["n"] += 1
        if pogingen["n"] < 3:
            raise requests.exceptions.ReadTimeout("time-out")
        return _Waarde()

    import time as _t
    orig_sleep = _t.sleep
    _t.sleep = lambda s: None  # geen echte wachttijd in de test
    try:
        # monkeypatch via het woz-module-attribuut dat _veilige_woz gebruikt
        oud = woz_mod.meest_recente_woz_waarde
        woz_mod.meest_recente_woz_waarde = _flaky
        try:
            waarde = opkoop_scan._veilige_woz("123")
        finally:
            woz_mod.meest_recente_woz_waarde = oud
    finally:
        _t.sleep = orig_sleep
    assert waarde == 400_000
    assert pogingen["n"] == 3


def test_korte_samenvatting_een_zin():
    adressen = [
        _nabij("Groot 1", 5, "1", aobj="a1", rd=(1.0, 1.0)),
        _nabij("Klein 2", 10, "2", aobj="a2", rd=(2.0, 2.0)),
    ]
    opp = {"a1": (95, "woonfunctie"), "a2": (50, "woonfunctie")}
    r = opkoop_scan.scan(
        52.0, 4.0, 470_000, "Centrum 1", pauze_s=0, m2_grens=72,
        adres_func=lambda lat, lon, straal: adressen,
        woz_func=lambda nid: 600_000, vergunning_func=lambda rx, ry: False,
        beschermde_wijk_func=lambda naam: True, bag_func=lambda aobj: opp[aobj],
        te_koop_func=lambda naam, grens: {"sinds": "2026-05-01", "tot": "2026-10-09",
                                          "prijs": None, "bron": "funda", "url": None,
                                          "status": "actief"} if naam == "Groot 1" else None,
    )
    zin = opkoop_scan.korte_samenvatting(r)
    assert zin.endswith(".")
    assert "1 reële concurrent" in zin
    assert "1 nu te koop" in zin
    assert "1 te klein" in zin


def test_bouw_cover_is_kort_met_kanttekening():
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
        bag_func=lambda aobj: (80, "woonfunctie"),
    )
    onderwerp, html, text = opkoop_scan.bouw_cover(r)
    assert "Pompstraat 42, Rotterdam" in onderwerp
    assert "reële adressen" in onderwerp
    assert "Samenvatting" in text
    assert "14 weken" in text                 # kanttekening over aanvragen
    assert "bijgevoegde PDF" in text          # verwijst naar de bijlage i.p.v. lange lijst
    # de cover bevat GEEN volledige adreslijst-tabel meer (die zit in de PDF)
    assert "C 3" not in text


def test_bouw_rapport_pdf_geeft_geldig_pdf():
    from kansen_site import opkoop_rapport_pdf
    adressen = [
        _nabij("A 1", 5, "1", rd=(1.0, 1.0)),
        _nabij("C 3", 15, "3", aobj="a3", rd=(3.0, 3.0)),
    ]
    woz = {"1": 300_000, "3": 600_000}
    r = opkoop_scan.scan(
        52.0, 4.0, 470_000, "Pompstraat 42, Rotterdam", pauze_s=0,
        adres_func=lambda lat, lon, straal: adressen,
        woz_func=lambda nid: woz[nid],
        vergunning_func=lambda rx, ry: False,
        beschermde_wijk_func=lambda naam: True,
        bag_func=lambda aobj: (60, "woonfunctie"),
    )
    pdf = opkoop_rapport_pdf.bouw_rapport_pdf(r)
    assert isinstance(pdf, bytes) and pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


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

    def _fake_send_mail(config, subject, html_body, text_body, recipients=None,
                        stille_bcc=True, attachments=None):
        verzonden["recipients"] = recipients
        verzonden["stille_bcc"] = stille_bcc
        verzonden["attachments"] = attachments

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
    # Het rapport gaat als PDF-bijlage mee (niet in de mailtekst).
    assert verzonden["attachments"] and len(verzonden["attachments"]) == 1
    naam, inhoud, subtype = verzonden["attachments"][0]
    assert naam.endswith(".pdf") and subtype == "pdf"
    assert inhoud.startswith(b"%PDF")
    data = resp.get_json()
    assert "een@x.nl" in data["melding"] and "twee@y.nl" in data["melding"]


def test_opkoop_scan_zonder_veld_gebruikt_mail_voorkeuren(tmp_path, monkeypatch):
    from rotterdam_scanner import mail_voorkeuren
    cfg = _config(tmp_path)
    mail_voorkeuren.zet_voorkeuren(cfg, "jurian", "voorkeur@x.nl", [])
    app = kansen_app.create_app(cfg)
    app.testing = True
    client = app.test_client()
    _login(client)

    verzonden = {}
    monkeypatch.setattr(kansen_app.geocode, "geocode_vrij_landelijk", _fake_geocode)
    monkeypatch.setattr(kansen_app.opkoop_scan, "scan",
                        lambda *a, **k: opkoop_scan.ScanResultaat("x", 50.0, 470_000, 72, "Oud Charlois", True, []))
    monkeypatch.setattr(kansen_app, "send_mail",
                        lambda *a, recipients=None, stille_bcc=True, attachments=None, **k: verzonden.update(recipients=recipients))
    monkeypatch.setattr(kansen_app.threading, "Thread", _DirecteThread)

    # Geen "ontvangers"-veld (zoals de kaart-popup doet) -> mail-voorkeuren-adres.
    resp = client.post("/opkoop-scan", json={"adres": "Pompstraat 42, Rotterdam"})
    assert resp.status_code == 200
    assert verzonden["recipients"] == ["voorkeur@x.nl"]


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
