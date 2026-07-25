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


def test_ververs_slaat_apify_over_als_niet_ingesteld(app_client, monkeypatch):
    import kansen_site.app as appmodule

    monkeypatch.setattr(appmodule.pipeline, "run", lambda config: RunResult())
    apify_mock_aangeroepen = []
    monkeypatch.setattr(
        appmodule.pipeline, "run_apify",
        lambda config: apify_mock_aangeroepen.append(config) or RunResult(),
    )
    app_client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    app_client.post("/ververs")
    assert apify_mock_aangeroepen == []


def test_ververs_roept_ook_apify_aan_indien_ingesteld_en_telt_beide_resultaten_op(tmp_path, monkeypatch):
    import kansen_site.app as appmodule

    config = _config(
        tmp_path, apify_api_token="apify-token", apify_search_urls=["https://www.funda.nl/koop/rotterdam/"],
    )
    monkeypatch.setattr(
        appmodule.pipeline, "run",
        lambda config: RunResult(nieuw_actief=[object()], fouten=["mail-waarschuwing"]),
    )
    monkeypatch.setattr(
        appmodule.pipeline, "run_apify",
        lambda config: RunResult(nieuw_actief=[object(), object()], nieuw_afgevallen=[object()], fouten=["apify-waarschuwing"]),
    )
    app = appmodule.create_app(config)
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"gebruiker": "jurian", "wachtwoord": "geheim123"})

    resp = client.post("/ververs")
    data = resp.get_json()
    assert data["nieuw_actief"] == 3  # 1 (mail) + 2 (apify)
    assert data["nieuw_afgevallen"] == 1
    assert data["fouten"] == ["mail-waarschuwing", "apify-waarschuwing"]
