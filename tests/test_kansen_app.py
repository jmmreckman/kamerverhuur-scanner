"""Tests voor kansen_site/app.py: login, de kaart-pagina, de JSON-lijst van
actieve kansen en de "ververs nu"-knop. pipeline.run() wordt hier nooit echt
aangeroepen (geen IMAP/PDOK/etc.), alleen gemockt."""
import pytest

from kansen_site.app import create_app
from rotterdam_scanner.config import Config
from rotterdam_scanner.pipeline import RunResult
from rotterdam_scanner.state import ListingState, StateStore


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
        kansen_app_secret_key="test-secret",
    )
    defaults.update(overrides)
    return Config(**defaults)


@pytest.fixture
def app_client(tmp_path):
    app = create_app(_config(tmp_path))
    app.testing = True
    return app.test_client()


def _zet_listing(tmp_path, **overrides):
    defaults = dict(
        object_id="3000AA-1", url="https://www.funda.nl/koop/rotterdam/huis-1/",
        weergavenaam="Teststraat 1, 3000AA Rotterdam", eerst_gezien="2026-07-01",
        laatst_gezien="2026-07-25", status="actief", wijknaam="Middelland",
        lat=51.92, lon=4.45, prijs=350_000, winst_pm_pp=150.0, eigen_inleg_pp=25_000.0,
    )
    defaults.update(overrides)
    state = StateStore(tmp_path / "state.json")
    state.upsert(ListingState(**defaults))
    state.save()


def test_create_app_zonder_gebruikers_weigert_te_starten(tmp_path):
    with pytest.raises(SystemExit):
        create_app(_config(tmp_path, kansen_app_users={}))


def test_create_app_zonder_secret_key_weigert_te_starten(tmp_path):
    with pytest.raises(SystemExit):
        create_app(_config(tmp_path, kansen_app_secret_key=""))


def test_kaart_zonder_login_wordt_omgeleid_naar_login(app_client):
    resp = app_client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_met_verkeerd_wachtwoord_geeft_foutmelding(app_client):
    resp = app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "fout"})
    assert resp.status_code == 200
    assert "onjuist" in resp.get_data(as_text=True).lower()


def test_login_met_juist_wachtwoord_geeft_toegang_tot_kaart(app_client):
    resp = app_client.post(
        "/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Kansen" in resp.get_data(as_text=True)


def test_beide_gebruikers_kunnen_inloggen(app_client):
    resp = app_client.post(
        "/login", data={"gebruiker": "justin", "wachtwoord": "anderwachtwoord"}, follow_redirects=True,
    )
    assert resp.status_code == 200


def test_logout_verwijdert_toegang(app_client):
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    app_client.post("/logout")
    resp = app_client.get("/")
    assert resp.status_code == 302


def test_api_kansen_zonder_login_wordt_omgeleid(app_client):
    resp = app_client.get("/api/kansen")
    assert resp.status_code == 302


def test_api_kansen_geeft_alleen_actieve_woningen_met_coordinaten(app_client, tmp_path):
    _zet_listing(tmp_path, object_id="a", status="actief", lat=51.9, lon=4.4)
    _zet_listing(tmp_path, object_id="b", status="afgevallen", lat=51.9, lon=4.4)
    _zet_listing(tmp_path, object_id="c", status="actief", lat=None, lon=None)
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    resp = app_client.get("/api/kansen")
    data = resp.get_json()
    assert [item["object_id"] for item in data] == ["a"]


def test_api_kansen_bevat_de_belangrijkste_velden(app_client, tmp_path):
    _zet_listing(tmp_path)
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    resp = app_client.get("/api/kansen")
    item = resp.get_json()[0]
    assert item["weergavenaam"] == "Teststraat 1, 3000AA Rotterdam"
    assert item["wijknaam"] == "Middelland"
    assert item["prijs"] == 350_000
    assert item["winst_pm_pp"] == 150.0
    assert item["eigen_inleg_pp"] == 25_000.0
    assert item["lat"] == 51.92
    assert item["lon"] == 4.45
    assert item["eerst_gezien"] == "2026-07-01"


def test_ververs_zonder_login_wordt_omgeleid(app_client):
    resp = app_client.post("/ververs")
    assert resp.status_code == 302


def test_ververs_roept_pipeline_run_aan_en_geeft_samenvatting(app_client, monkeypatch):
    import kansen_site.app as appmodule

    aangeroepen = []

    def _fake_run(config):
        aangeroepen.append(config)
        return RunResult(nieuw_actief=[object()], nieuw_afgevallen=[object(), object()], fouten=["een waarschuwing"])

    monkeypatch.setattr(appmodule.pipeline, "run", _fake_run)
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    resp = app_client.post("/ververs")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["nieuw_actief"] == 1
    assert data["nieuw_afgevallen"] == 2
    assert data["fouten"] == ["een waarschuwing"]
    assert len(aangeroepen) == 1


# --- Kansen handmatig verwijderen + terugplaatsen ---


def test_kans_verwijderen_zonder_login_wordt_omgeleid(app_client):
    resp = app_client.post("/kansen/3000AA-1/verwijderen")
    assert resp.status_code == 302


def test_kans_verwijderen_onbekende_woning_geeft_404(app_client):
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = app_client.post("/kansen/onbekend/verwijderen")
    assert resp.status_code == 404


def test_kans_verwijderen_zet_status_en_vlag(app_client, tmp_path):
    _zet_listing(tmp_path)
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    resp = app_client.post("/kansen/3000AA-1/verwijderen", data={"reden": "Zelfbewoningsplicht"})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}

    item = StateStore(tmp_path / "state.json").get("3000AA-1")
    assert item.status == "afgevallen"
    assert item.handmatig_verwijderd is True
    assert item.afvalreden == "Zelfbewoningsplicht"


def test_kans_verwijderen_zonder_reden_gebruikt_standaardtekst(app_client, tmp_path):
    _zet_listing(tmp_path)
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    app_client.post("/kansen/3000AA-1/verwijderen")

    item = StateStore(tmp_path / "state.json").get("3000AA-1")
    assert item.afvalreden == "Handmatig verwijderd via kansen.steenhub.nl."


def test_kans_verwijderd_valt_niet_meer_uit_api_kansen(app_client, tmp_path):
    _zet_listing(tmp_path)
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    app_client.post("/kansen/3000AA-1/verwijderen")

    resp = app_client.get("/api/kansen")
    assert resp.get_json() == []


def test_kans_kamers_zonder_login_wordt_omgeleid(app_client):
    resp = app_client.post("/kansen/3000AA-1/kamers")
    assert resp.status_code == 302


def test_kans_kamers_onbekende_woning_geeft_404(app_client):
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = app_client.post("/kansen/onbekend/kamers", data={"aantal_kamers": "5"})
    assert resp.status_code == 404


def test_kans_kamers_aanpassen_herberekent_investering(app_client, tmp_path):
    _zet_listing(tmp_path, prijs=403_000, opslag_percentage=0.0, aantal_kamers_mogelijk=6)
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    resp = app_client.post("/kansen/3000AA-1/kamers", data={"aantal_kamers": "4"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["aantal_kamers_mogelijk"] == 4
    assert data["aantal_kamers_handmatig"] is True

    item = StateStore(tmp_path / "state.json").get("3000AA-1")
    assert item.aantal_kamers_mogelijk == 4
    assert item.aantal_kamers_handmatig is True
    # Winst/eigen inleg moeten meeveranderen met het handmatige aantal (minder kamers
    # dan de automatisch berekende 6 -> minder huurinkomsten dan voorheen).
    assert item.winst_pm_pp is not None


def test_kans_kamers_leeg_veld_gaat_terug_naar_automatisch(app_client, tmp_path):
    _zet_listing(
        tmp_path, prijs=403_000, oppervlakte_advertentie=115,
        aantal_kamers_mogelijk=4, aantal_kamers_handmatig=True,
    )
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    resp = app_client.post("/kansen/3000AA-1/kamers", data={"aantal_kamers": ""})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["aantal_kamers_handmatig"] is False
    assert data["aantal_kamers_mogelijk"] == 6  # floor(115 / 18)

    item = StateStore(tmp_path / "state.json").get("3000AA-1")
    assert item.aantal_kamers_handmatig is False
    assert item.aantal_kamers_mogelijk == 6


def test_kans_kamers_negatief_geeft_fout(app_client, tmp_path):
    _zet_listing(tmp_path)
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    resp = app_client.post("/kansen/3000AA-1/kamers", data={"aantal_kamers": "-1"})
    assert resp.status_code == 400


def test_kans_kamers_ongeldige_waarde_geeft_fout(app_client, tmp_path):
    _zet_listing(tmp_path)
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    resp = app_client.post("/kansen/3000AA-1/kamers", data={"aantal_kamers": "abc"})
    assert resp.status_code == 400


def test_kans_terugplaatsen_zonder_login_wordt_omgeleid(app_client):
    resp = app_client.post("/kansen/3000AA-1/terugplaatsen")
    assert resp.status_code == 302


def test_kans_terugplaatsen_onbekende_woning_geeft_404(app_client):
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = app_client.post("/kansen/onbekend/terugplaatsen")
    assert resp.status_code == 404


def test_kans_terugplaatsen_zet_weer_actief(app_client, tmp_path):
    _zet_listing(
        tmp_path, status="afgevallen", handmatig_verwijderd=True, afvalreden="Zelfbewoningsplicht",
    )
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    resp = app_client.post("/kansen/3000AA-1/terugplaatsen", follow_redirects=True)
    assert resp.status_code == 200

    item = StateStore(tmp_path / "state.json").get("3000AA-1")
    assert item.status == "actief"
    assert item.handmatig_verwijderd is False
    assert item.afvalreden is None


def test_verwijderd_zonder_login_wordt_omgeleid(app_client):
    resp = app_client.get("/verwijderd")
    assert resp.status_code == 302


def test_verwijderd_toont_alleen_handmatig_verwijderde_woningen(app_client, tmp_path):
    _zet_listing(
        tmp_path, object_id="a", status="afgevallen", handmatig_verwijderd=True,
        afvalreden="Zelfbewoningsplicht", weergavenaam="Handmatig verwijderde straat 1",
    )
    _zet_listing(
        tmp_path, object_id="b", status="afgevallen", handmatig_verwijderd=False,
        afvalreden="Buiten opkoopbescherming", weergavenaam="Automatisch afgevallen straat 2",
    )
    _zet_listing(tmp_path, object_id="c", status="actief", weergavenaam="Nog actieve straat 3")
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    resp = app_client.get("/verwijderd")
    tekst = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Handmatig verwijderde straat 1" in tekst
    assert "Zelfbewoningsplicht" in tekst
    assert "Automatisch afgevallen straat 2" not in tekst
    assert "Nog actieve straat 3" not in tekst


# --- /handmatig-toevoegen ---


def test_handmatig_toevoegen_zonder_login_wordt_omgeleid(app_client):
    resp = app_client.get("/handmatig-toevoegen")
    assert resp.status_code == 302


def test_handmatig_toevoegen_toont_formulier(app_client):
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = app_client.get("/handmatig-toevoegen")
    assert resp.status_code == 200
    assert "Verwerken" in resp.get_data(as_text=True)


def test_handmatig_toevoegen_zonder_leesbare_adressen_toont_foutmelding(app_client):
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = app_client.post("/handmatig-toevoegen", data={"tekst": "dit is geen adres"}, follow_redirects=True)
    assert resp.status_code == 200
    assert "geen enkel adres" in resp.get_data(as_text=True).lower()


def test_handmatig_toevoegen_verwerkt_adresregel_en_toont_resultaat(tmp_path, monkeypatch):
    import kansen_site.app as appmodule

    config = _config(tmp_path)
    aangeroepen = []

    def _fake_run_handmatig(config, listings, today=None, forceer_herprocessen=False):
        aangeroepen.append((listings, forceer_herprocessen))
        return RunResult(nieuw_actief=[object()], fouten=["een waarschuwing"])

    monkeypatch.setattr(appmodule.pipeline, "run_handmatig", _fake_run_handmatig)
    app = appmodule.create_app(config)
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    resp = client.post("/handmatig-toevoegen", data={"tekst": "3073KJ 47A"})
    assert resp.status_code == 200
    tekst = resp.get_data(as_text=True)
    assert "1 nieuwe kans" in tekst
    assert "een waarschuwing" in tekst

    assert len(aangeroepen) == 1
    listings, forceer_herprocessen = aangeroepen[0]
    assert len(listings) == 1
    assert listings[0].object_id == "3073KJ-47A"
    assert forceer_herprocessen is False


def test_handmatig_toevoegen_forceer_herprocessen_vinkje(tmp_path, monkeypatch):
    import kansen_site.app as appmodule

    config = _config(tmp_path)
    aangeroepen = []
    monkeypatch.setattr(
        appmodule.pipeline, "run_handmatig",
        lambda config, listings, today=None, forceer_herprocessen=False: (
            aangeroepen.append(forceer_herprocessen) or RunResult()
        ),
    )
    app = appmodule.create_app(config)
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    client.post("/handmatig-toevoegen", data={"tekst": "3073KJ 47A", "forceer_herprocessen": "on"})
    assert aangeroepen == [True]


# --- Zoekopdrachten (browsergebaseerde search-URL's) ---


def test_zoekopdrachten_zonder_login_wordt_omgeleid(app_client):
    resp = app_client.get("/zoekopdrachten")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_zoekopdrachten_toont_lege_lijst(app_client):
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = app_client.get("/zoekopdrachten")
    assert resp.status_code == 200
    assert "Nog geen zoekopdrachten toegevoegd." in resp.get_data(as_text=True)


def test_zoekopdrachten_toevoegen_slaat_url_en_label_op(app_client):
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = app_client.post(
        "/zoekopdrachten/toevoegen",
        data={"url": "https://www.funda.nl/zoeken/koop?selected_area=rotterdam", "label": "Rotterdam t/m 8 ton"},
        follow_redirects=True,
    )
    tekst = resp.get_data(as_text=True)
    assert "Rotterdam t/m 8 ton" in tekst
    assert "selected_area=rotterdam" in tekst


def test_zoekopdrachten_toevoegen_weigert_niet_funda_url(app_client):
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = app_client.post(
        "/zoekopdrachten/toevoegen", data={"url": "https://www.evil.example/", "label": ""},
        follow_redirects=True,
    )
    assert "lijkt geen Funda-zoek-URL" in resp.get_data(as_text=True)


def test_zoekopdrachten_verwijderen_haalt_url_weg(app_client):
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    app_client.post(
        "/zoekopdrachten/toevoegen", data={"url": "https://www.funda.nl/zoeken/koop?a=1", "label": ""},
    )
    resp = app_client.post(
        "/zoekopdrachten/verwijderen", data={"url": "https://www.funda.nl/zoeken/koop?a=1"},
        follow_redirects=True,
    )
    assert "Nog geen zoekopdrachten toegevoegd." in resp.get_data(as_text=True)


def test_zoekopdrachten_testen_zonder_login_wordt_omgeleid(app_client):
    resp = app_client.post("/zoekopdrachten/testen", data={"url": "https://www.funda.nl/zoeken/koop?a=1"})
    assert resp.status_code == 302


def test_zoekopdrachten_testen_zonder_url_geeft_fout(app_client):
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = app_client.post("/zoekopdrachten/testen", data={"url": ""})
    assert resp.status_code == 400
    assert resp.get_json()["fout"] == "Onbekende zoekopdracht."


def test_zoekopdrachten_testen_geeft_gevonden_adressen_terug(app_client, monkeypatch):
    import kansen_site.app as appmodule
    from rotterdam_scanner.funda_mail import FundaListing

    listing = FundaListing(
        object_id="3073KJ-47A", url="https://www.funda.nl/detail/koop/rotterdam/x/1/",
        straatnaam="Hillevliet", huisnummer="47", toevoeging="A", postcode="3073KJ", woonplaats="Rotterdam",
    )
    monkeypatch.setattr(appmodule, "browser_haal_listings_op", lambda url, vandaag=None: ([listing], []))
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    resp = app_client.post("/zoekopdrachten/testen", data={"url": "https://www.funda.nl/zoeken/koop?a=1"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["aantal"] == 1
    assert "Hillevliet 47A, 3073KJ Rotterdam" in data["adressen"]
    assert data["fouten"] == []
