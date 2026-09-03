"""Tests voor kansen_site/app.py: login, de kaart-pagina, de JSON-lijst van
actieve kansen en de "ververs nu"-knop. pipeline.run() wordt hier nooit echt
aangeroepen (geen IMAP/PDOK/etc.), alleen gemockt."""
import json

import pytest
from werkzeug.security import generate_password_hash

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


def test_api_kansen_bevat_investeerder_onafhankelijke_totalen(app_client, tmp_path):
    # winst_pm_pp/eigen_inleg_pp staan al gedeeld door 2 investeerders; de totalen
    # (voor de investeerders-omreken op de kaart) zijn dat maal 2.
    _zet_listing(tmp_path, winst_pm_pp=150.0, eigen_inleg_pp=25_000.0, schakelgeld_totaal=180_000.0)
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    item = app_client.get("/api/kansen").get_json()[0]
    assert item["winst_pm_totaal"] == 300.0
    assert item["eigen_inleg_na_ophoging_totaal"] == 50_000.0
    assert item["schakelgeld_totaal"] == 180_000.0


def test_api_kansen_totalen_zijn_none_zonder_cijfers(app_client, tmp_path):
    _zet_listing(tmp_path, winst_pm_pp=None, eigen_inleg_pp=None)
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    item = app_client.get("/api/kansen").get_json()[0]
    assert item["winst_pm_totaal"] is None
    assert item["eigen_inleg_na_ophoging_totaal"] is None
    assert item["schakelgeld_totaal"] is None


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
    # Ook het schakelgeld (eigen inleg vóór verhoging) wordt herberekend/opgeslagen.
    assert item.schakelgeld_totaal is not None


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


def _wacht_op_run_klaar(client, timeout=3.0):
    """De verwerking draait op de achtergrond; wacht tot de status niet meer 'bezig' is."""
    import time
    einde = time.time() + timeout
    while time.time() < einde:
        data = client.get("/handmatig-toevoegen/status").get_json()
        if data.get("status") not in ("bezig", "leeg"):
            return data
        time.sleep(0.02)
    raise AssertionError(f"Run niet op tijd klaar; laatste status: {data}")


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

    # Start de (nu asynchrone) verwerking; de POST leidt om naar de pagina.
    resp = client.post("/handmatig-toevoegen", data={"tekst": "3073KJ 47A"})
    assert resp.status_code == 302

    run = _wacht_op_run_klaar(client)
    assert run["status"] == "klaar"
    assert run["resultaat"]["nieuw_actief"] == 1
    assert "een waarschuwing" in run["resultaat"]["fouten"]

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
    _wacht_op_run_klaar(client)
    assert aangeroepen == [True]


def test_handmatig_toevoegen_weigert_tweede_run_terwijl_bezig(tmp_path, monkeypatch):
    import threading

    import kansen_site.app as appmodule

    config = _config(tmp_path)
    gestart = threading.Event()
    los = threading.Event()

    def _traag(config, listings, today=None, forceer_herprocessen=False):
        gestart.set()
        los.wait(3.0)  # houd de run "bezig" tot de test 'm loslaat
        return RunResult()

    monkeypatch.setattr(appmodule.pipeline, "run_handmatig", _traag)
    app = appmodule.create_app(config)
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    client.post("/handmatig-toevoegen", data={"tekst": "3073KJ 47A"})
    assert gestart.wait(2.0)  # eerste run draait nu

    # Tweede poging tijdens een lopende run wordt geweigerd (geen dubbele state-write).
    resp = client.post("/handmatig-toevoegen", data={"tekst": "3078CN 44"}, follow_redirects=True)
    assert "al een verwerking" in resp.get_data(as_text=True).lower()

    los.set()
    _wacht_op_run_klaar(client)


# --- Rekentool per woning ---------------------------------------------------

def _ingelogd(tmp_path):
    app = create_app(_config(tmp_path))
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    return client


def test_berekening_zonder_login_wordt_omgeleid(app_client):
    resp = app_client.get("/woning/a/berekening")
    assert resp.status_code == 302


def test_berekening_onbekende_woning_geeft_404(tmp_path):
    client = _ingelogd(tmp_path)
    assert client.get("/woning/bestaat-niet/berekening").status_code == 404


def test_berekening_pagina_toont_voorgevulde_koopsom_en_kamers(tmp_path):
    _zet_listing(tmp_path, object_id="a", prijs=355_000, aantal_kamers_mogelijk=6)
    client = _ingelogd(tmp_path)
    resp = client.get("/woning/a/berekening")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'name="koopsom" value="355000' in body
    assert 'name="aantal_kamers" value="6"' in body


def test_berekening_opslaan_bewaart_en_geeft_doorgerekende_sommen(tmp_path):
    _zet_listing(tmp_path, object_id="a", prijs=355_000, aantal_kamers_mogelijk=6)
    client = _ingelogd(tmp_path)
    # De PDF-uitgangspunten insturen (procenten als heel getal).
    resp = client.post("/woning/a/berekening", json={
        "koopsom": "355000", "aantal_kamers": "6", "aantal_investeerders": "2",
        "overdrachtsbelasting": "8", "bar": "7.6", "kale_huur_per_kamer": "560",
        "servicekosten_per_kamer": "250", "vaste_kosten_per_huurder": "100",
        "kosten_koper_ex_ovb": "6000", "verbouwkosten": "25000", "rente": "5.9",
        "taxatie_verhouding_voor_verhoging": "87.5", "ltv": "80",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert round(data["winst_pm_pp"], 2) == 1_086.63
    assert round(data["eigen_inleg_na_ophoging_pp"], 2) == -1_880.42

    # Opgeslagen bij de woning (procenten als fractie) en overleeft een herstart.
    state = StateStore(tmp_path / "state.json")
    bewaard = state.get("a").berekening
    assert bewaard["kale_huur_per_kamer"] == 560
    assert bewaard["overdrachtsbelasting"] == pytest.approx(0.08)
    assert bewaard["rente"] == pytest.approx(0.059)


def test_berekening_opgeslagen_waarden_worden_hergebruikt_bij_volgend_bezoek(tmp_path):
    _zet_listing(tmp_path, object_id="a", prijs=355_000, aantal_kamers_mogelijk=6)
    client = _ingelogd(tmp_path)
    client.post("/woning/a/berekening", json={"kale_huur_per_kamer": "600"})
    resp = client.get("/woning/a/berekening")
    assert 'name="kale_huur_per_kamer" value="600' in resp.get_data(as_text=True)


def test_berekening_opslaan_weigert_ongeldige_waarde(tmp_path):
    _zet_listing(tmp_path, object_id="a", prijs=355_000, aantal_kamers_mogelijk=6)
    client = _ingelogd(tmp_path)
    resp = client.post("/woning/a/berekening", json={"rente": "abc"})
    assert resp.status_code == 400


# --- Inloggen met de Steenhub-accounts (gedeelde users.json) ----------------

def _steenhub_users_file(tmp_path, gebruiker="marit", wachtwoord="steenhub-geheim"):
    pad = tmp_path / "users.json"
    pad.write_text(json.dumps({
        gebruiker: {"wachtwoord_hash": generate_password_hash(wachtwoord), "alle_panden": True, "panden": []},
    }))
    return str(pad)


def _client_met_steenhub(tmp_path, **overrides):
    app = create_app(_config(tmp_path, steenhub_users_file=_steenhub_users_file(tmp_path), **overrides))
    app.testing = True
    return app.test_client()


def test_login_met_steenhub_account_werkt(tmp_path):
    client = _client_met_steenhub(tmp_path)
    resp = client.post(
        "/login", data={"gebruiker": "marit", "wachtwoord": "steenhub-geheim"}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Kansen" in resp.get_data(as_text=True)


def test_login_met_steenhub_account_verkeerd_wachtwoord_faalt(tmp_path):
    client = _client_met_steenhub(tmp_path)
    resp = client.post("/login", data={"gebruiker": "marit", "wachtwoord": "fout"})
    assert resp.status_code == 200
    assert "onjuist" in resp.get_data(as_text=True).lower()


def test_eigen_kansen_users_blijven_werken_naast_steenhub(tmp_path):
    client = _client_met_steenhub(tmp_path)
    resp = client.post(
        "/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"}, follow_redirects=True,
    )
    assert resp.status_code == 200


def test_start_zonder_kansen_users_maar_met_steenhub_file_mag(tmp_path):
    # Geen KANSEN_APP_USERS, wel een bruikbaar steenhub-bestand -> mag starten.
    create_app(_config(tmp_path, kansen_app_users={}, steenhub_users_file=_steenhub_users_file(tmp_path)))


def test_start_zonder_enige_inlogbron_weigert(tmp_path):
    with pytest.raises(SystemExit):
        create_app(_config(tmp_path, kansen_app_users={}, steenhub_users_file=""))


# --- Favoriet + bekendmakingen-check ---


def test_favoriet_zonder_login_wordt_omgeleid(app_client):
    resp = app_client.post("/kansen/3000AA-1/favoriet")
    assert resp.status_code == 302


def test_favoriet_togglet_heen_en_weer(tmp_path):
    app = create_app(_config(tmp_path))
    app.testing = True
    client = app.test_client()
    _zet_listing(tmp_path)
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    resp = client.post("/kansen/3000AA-1/favoriet")
    assert resp.status_code == 200
    assert resp.get_json()["favoriet"] is True
    assert StateStore(tmp_path / "state.json").get("3000AA-1").favoriet is True

    resp = client.post("/kansen/3000AA-1/favoriet")
    assert resp.get_json()["favoriet"] is False
    assert StateStore(tmp_path / "state.json").get("3000AA-1").favoriet is False


def test_favoriet_onbekende_woning_geeft_404(app_client):
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = app_client.post("/kansen/onbekend/favoriet")
    assert resp.status_code == 404


def test_api_kansen_toont_afgevallen_favoriet(tmp_path):
    app = create_app(_config(tmp_path))
    app.testing = True
    client = app.test_client()
    # Een afgevallen woning die tóch favoriet is, moet op de kaart blijven staan.
    _zet_listing(tmp_path, status="afgevallen", favoriet=True)
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = client.get("/api/kansen")
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["favoriet"] is True
    assert data[0]["status"] == "afgevallen"


def test_bekendmakingen_check_roept_pipeline_aan(app_client, monkeypatch):
    import kansen_site.app as appmodule

    monkeypatch.setattr(
        appmodule.pipeline, "controleer_bekendmakingen",
        lambda config: {"aantal_nieuw": 2, "fouten": []},
    )
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = app_client.post("/bekendmakingen/check")
    assert resp.status_code == 200
    assert resp.get_json()["aantal_nieuw"] == 2


# --- Vergunningenlaag + data-analyse ---


def _zet_vergunningen_index(tmp_path, vergunningen):
    import json
    pad = tmp_path / "vergunningen_index.json"
    data = {
        "meta": {"volledige_enumeratie_gedaan": True, "bijgewerkt": "2026-08-20T07:00:00"},
        "vergunningen": {v["publicatie_id"]: v for v in vergunningen},
    }
    pad.write_text(json.dumps(data), encoding="utf-8")


def test_api_vergunningen_zonder_login_wordt_omgeleid(app_client):
    resp = app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "fout"})
    resp = app_client.get("/api/vergunningen")
    assert resp.status_code == 302


def test_api_vergunningen_geeft_alleen_bruikbare(tmp_path):
    app = create_app(_config(tmp_path))
    app.testing = True
    client = app.test_client()
    _zet_vergunningen_index(tmp_path, [
        {"publicatie_id": "gmb-1", "verwerkt": True, "bruikbaar": True, "adres": "A-straat 1",
         "gebied": "Delfshaven", "aantal_personen": 3, "datum": "2026-08-10", "soort": "overgangsbepaling",
         "besluitdatum": "2026-08-08", "zaaknummer": "1-2026", "url": "u", "lat": 51.9, "lon": 4.45},
        {"publicatie_id": "gmb-2", "verwerkt": True, "bruikbaar": False, "adres": None},
    ])
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = client.get("/api/vergunningen")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["vergunningen"]) == 1
    assert data["vergunningen"][0]["adres"] == "A-straat 1"
    assert data["vergunningen"][0]["aantal_personen"] == 3
    assert data["vergunningen"][0]["soort"] == "overgangsbepaling"
    assert data["compleet"] is True


def test_api_vergunningen_zonder_index_geeft_lege_lijst(app_client):
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = app_client.get("/api/vergunningen")
    assert resp.status_code == 200
    assert resp.get_json()["vergunningen"] == []


def test_data_analyse_pagina_vereist_login(app_client):
    resp = app_client.get("/data-analyse")
    assert resp.status_code == 302


def test_data_analyse_pagina_rendert(app_client):
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = app_client.get("/data-analyse")
    assert resp.status_code == 200
    assert b"Data-analyse" in resp.data


# --- Globale reken-instellingen ---

from dataclasses import asdict as _asdict
from rotterdam_scanner.investering import RekenUitgangspunten as _RU


def test_reken_instellingen_pagina_rendert(app_client):
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = app_client.get("/reken-instellingen")
    assert resp.status_code == 200
    assert "Standaard-uitgangspunten voor alle panden".encode() in resp.data


def test_reken_instellingen_propageert_naar_volgende_panden_niet_naar_custom(tmp_path):
    import json
    default_rente = _asdict(_RU(koopsom=0, aantal_kamers=0))["rente"]  # de huidige globale standaard (fractie)

    app = create_app(_config(tmp_path))
    app.testing = True
    client = app.test_client()
    # Pand A volgt de oude globale rente; pand B heeft een eigen (afwijkende) rente;
    # pand C heeft helemaal geen eigen berekening.
    _zet_listing(tmp_path, object_id="A", berekening={"rente": default_rente, "bar": 0.076})
    _zet_listing(tmp_path, object_id="B", berekening={"rente": default_rente + 0.001, "bar": 0.076})
    _zet_listing(tmp_path, object_id="C")
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    nieuwe_rente_procent = round(default_rente * 100 + 1, 4)  # +1 procentpunt
    resp = client.post("/reken-instellingen", data={"rente": str(nieuwe_rente_procent)}, follow_redirects=True)
    assert resp.status_code == 200

    listings = json.loads((tmp_path / "state.json").read_text())["listings"]
    assert listings["A"]["berekening"]["rente"] == pytest.approx(default_rente + 0.01)  # meebijgewerkt
    assert listings["B"]["berekening"]["rente"] == pytest.approx(default_rente + 0.001)  # eigen waarde blijft
    assert listings["C"]["berekening"] is None  # geen eigen berekening -> volgt globaal vanzelf

    defaults = json.loads((tmp_path / "reken_defaults.json").read_text())
    assert defaults["rente"] == pytest.approx(default_rente + 0.01)


def test_woning_zonder_berekening_volgt_globale_rente(tmp_path):
    default_rente = _asdict(_RU(koopsom=0, aantal_kamers=0))["rente"]
    app = create_app(_config(tmp_path))
    app.testing = True
    client = app.test_client()
    _zet_listing(tmp_path, object_id="C", prijs=350_000, aantal_kamers_mogelijk=6)
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    client.post("/reken-instellingen", data={"rente": str(round(default_rente * 100 + 2, 4))})
    # De rekentool van pand C (zonder eigen berekening) toont nu de nieuwe globale rente.
    resp = client.get("/woning/C/berekening")
    nieuw = round(default_rente * 100 + 2, 4)
    getoond = str(int(nieuw)) if float(nieuw).is_integer() else str(nieuw)
    assert f'name="rente" value="{getoond}"'.encode() in resp.data


# --- Toegangsbeheer: accounts "buiten werking" zetten ---

def _beheer_config(tmp_path, **overrides):
    # jurian = beheerder, justin = gewoon (blokkeerbaar) account.
    defaults = dict(kansen_app_beheerders={"jurian"})
    defaults.update(overrides)
    return _config(tmp_path, **defaults)


def _beheer_client(tmp_path, **overrides):
    app = create_app(_beheer_config(tmp_path, **overrides))
    app.testing = True
    return app.test_client()


def test_buiten_werking_account_krijgt_storing_ipv_login(tmp_path):
    (tmp_path / "toegang.json").write_text(json.dumps({"buiten_werking": ["justin"]}))
    client = _beheer_client(tmp_path)
    resp = client.post("/login", data={"gebruiker": "justin", "wachtwoord": "anderwachtwoord"})
    # Kale, onopgemaakte serverfout - lijkt op een gewone crash, niets verklapt dat
    # de toegang bewust is ontzegd.
    assert resp.status_code == 500
    assert resp.get_data(as_text=True) == "Internal Server Error"
    assert b"buiten werking" not in resp.data
    # Niet ingelogd: de kaart blijft achter de login.
    vervolg = client.get("/", follow_redirects=False)
    assert vervolg.status_code == 302


def test_buiten_werking_poging_wordt_geteld(tmp_path):
    (tmp_path / "toegang.json").write_text(json.dumps({"buiten_werking": ["justin"]}))
    client = _beheer_client(tmp_path)
    client.post("/login", data={"gebruiker": "justin", "wachtwoord": "anderwachtwoord"})
    client.post("/login", data={"gebruiker": "justin", "wachtwoord": "fout"})
    data = json.loads((tmp_path / "toegang.json").read_text())
    poging = data["pogingen"]["justin"]
    assert poging["aantal"] == 2
    assert poging["laatste_wachtwoord_klopte"] is False  # laatste poging had fout wachtwoord


def test_niet_geblokkeerd_account_kan_gewoon_inloggen(tmp_path):
    client = _beheer_client(tmp_path)
    resp = client.post("/login", data={"gebruiker": "justin", "wachtwoord": "anderwachtwoord"},
                       follow_redirects=False)
    assert resp.status_code == 302  # normaal ingelogd


def test_zittende_sessie_valt_om_zodra_account_buiten_werking(tmp_path):
    client = _beheer_client(tmp_path)
    client.post("/login", data={"gebruiker": "justin", "wachtwoord": "anderwachtwoord"})
    assert client.get("/").status_code == 200  # eerst nog toegang
    (tmp_path / "toegang.json").write_text(json.dumps({"buiten_werking": ["justin"]}))
    resp = client.get("/")
    assert resp.status_code == 500  # sessie meteen ongeldig


def test_toegangsbeheer_alleen_voor_beheerder(tmp_path):
    client = _beheer_client(tmp_path)
    # Anoniem -> naar login.
    assert client.get("/toegangsbeheer").status_code == 302
    # Gewoon account -> 404 (bestaan wordt niet verklapt).
    client.post("/login", data={"gebruiker": "justin", "wachtwoord": "anderwachtwoord"})
    assert client.get("/toegangsbeheer").status_code == 404


def test_beheerder_ziet_en_zet_buiten_werking(tmp_path):
    client = _beheer_client(tmp_path)
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = client.get("/toegangsbeheer")
    assert resp.status_code == 200
    assert b"justin" in resp.data
    # Zet justin buiten werking.
    client.post("/toegangsbeheer", data={"buiten_werking": "justin"}, follow_redirects=True)
    data = json.loads((tmp_path / "toegang.json").read_text())
    assert data["buiten_werking"] == ["justin"]


def test_beheerder_kan_zichzelf_niet_buitensluiten(tmp_path):
    client = _beheer_client(tmp_path)
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    # Probeer jurian (beheerder) én justin te blokkeren; alleen justin blijft over.
    client.post("/toegangsbeheer", data={"buiten_werking": ["jurian", "justin"]}, follow_redirects=True)
    data = json.loads((tmp_path / "toegang.json").read_text())
    assert data["buiten_werking"] == ["justin"]


def test_vaste_eigenaar_is_beheerder_via_steenhub_login(tmp_path):
    # Eigenaar logt in met zijn steenhub-account (niet in KANSEN_APP_USERS) en moet
    # tóch de beheerpagina + "Toegang"-link zien, zonder env-config.
    users = tmp_path / "steenhub_users.json"
    users.write_text(json.dumps({
        "jmmreckman": {"wachtwoord_hash": generate_password_hash("eigenaar-pw")},
    }))
    app = create_app(_config(tmp_path, kansen_app_users={"jurian": "geheim123"},
                             steenhub_users_file=str(users)))
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"gebruiker": "jmmreckman", "wachtwoord": "eigenaar-pw"})
    kaart = client.get("/")
    assert b"Toegang" in kaart.data
    assert client.get("/toegangsbeheer").status_code == 200


def test_api_broninfo_geeft_bronverdeling(tmp_path):
    app = create_app(_config(tmp_path))
    app.testing = True
    client = app.test_client()
    _zet_listing(tmp_path, object_id="F", bronnen=["funda"])
    _zet_listing(tmp_path, object_id="N", bronnen=["nvm"])
    _zet_listing(tmp_path, object_id="B", bronnen=["funda", "nvm"])
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    data = client.get("/api/broninfo").get_json()
    assert data["funda"] == 2
    assert data["nvm"] == 2
    assert data["beide"] == 1
    assert data["alleen_funda"] == 1
    assert data["alleen_nvm"] == 1
    assert data["totaal"] == 3


def test_api_kansen_geeft_funda_zoek_url_als_fallback(tmp_path):
    # Een woning zonder directe Funda-link (bv. alleen via NVM) krijgt een
    # Funda-zoeklink op adres mee als fallback.
    app = create_app(_config(tmp_path))
    app.testing = True
    client = app.test_client()
    _zet_listing(tmp_path, url="", weergavenaam="Westzeedijk 74B, 3016AG Rotterdam")
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    item = client.get("/api/kansen").get_json()[0]
    assert item["funda_zoek_url"].startswith("https://www.funda.nl/zoeken/koop?query=")
    assert "Westzeedijk" in item["funda_zoek_url"]


def test_wwso_pagina_vereist_login(app_client):
    resp = app_client.get("/woning/3000AA-1/wwso")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_wwso_pagina_toont_scherm(tmp_path):
    app = create_app(_config(tmp_path))
    app.testing = True
    client = app.test_client()
    _zet_listing(tmp_path, aantal_kamers_mogelijk=6, prijs=350_000)
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = client.get("/woning/3000AA-1/wwso")
    assert resp.status_code == 200
    assert "WWSO-huur" in resp.get_data(as_text=True)


def test_wwso_bereken_geeft_huur_per_kamer(tmp_path):
    app = create_app(_config(tmp_path))
    app.testing = True
    client = app.test_client()
    _zet_listing(tmp_path, aantal_kamers_mogelijk=6)
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    payload = {
        "kamers": [{"oppervlakte_m2": "14", "verwarmd": True} for _ in range(6)],
        "energielabel": "B",
        "woz_waarde": "295000", "woz_oppervlakte_m2": "90",
        "corop_gemiddelde_woz_m2": "3884",
        "keuken": {"aanrecht_m": "2.5", "voorzieningen": ["koelkast"], "extra_kastruimte_60cm": "0"},
        "sanitair": {"voorzieningen": ["douche", "toilet_staand_badkamer", "wastafel"]},
        "gedeelde_ruimten": [],
        "gemeenschappelijke_buitenruimte": {"oppervlakte_m2": "51", "aantal_adressen": "1"},
    }
    resp = client.post("/woning/3000AA-1/wwso/bereken", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["kamers"]) == 6
    assert data["gemiddelde_huur"] > 0
    # Sanity: energie-rubriek van kamer 1 is label B (0,50) x 14 m² = 7,0.
    assert data["kamers"][0]["punten_per_rubriek"]["energie"] == 7.0


def test_wwso_bereken_zonder_kamers_geeft_fout(tmp_path):
    app = create_app(_config(tmp_path))
    app.testing = True
    client = app.test_client()
    _zet_listing(tmp_path)
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = client.post("/woning/3000AA-1/wwso/bereken", json={"kamers": []})
    assert resp.status_code == 400


def test_wwso_gebruik_zet_kale_huur_in_rekentool(tmp_path):
    app = create_app(_config(tmp_path))
    app.testing = True
    client = app.test_client()
    _zet_listing(tmp_path)
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})
    resp = client.post("/woning/3000AA-1/wwso/gebruik", json={"kale_huur_per_kamer": 512.5})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    item = StateStore(tmp_path / "state.json").get("3000AA-1")
    assert item.berekening["kale_huur_per_kamer"] == 512.5
