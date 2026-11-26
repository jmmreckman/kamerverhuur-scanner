"""Tests voor de winstberekeningspagina (per pand), de gecombineerde
"totale winst alle panden"-pagina, en de dashboard-/pandkiezertegel."""
import json
from datetime import date
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner import state
from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Payment, Tenant
from webapp.app import create_app


class FakeSheetClient:
    kamers = [Tenant(row_index=2, naam="Jan", kamer="1", verwacht_bedrag=Decimal("650.00"))]

    def __init__(self, _config, _pand):
        pass

    def get_kamers(self):
        return FakeSheetClient.kamers


class FakeBunqClient:
    def __init__(self, _config):
        pass

    def get_outgoing_payments(self, pand, since):
        return [
            Payment(bedrag=Decimal("100.00"), valuta="EUR", tegenpartij_naam="Energieleverancier",
                    tegenpartij_iban="NL91ABNA0417164300", omschrijving="Energie", datum=date(2026, 4, 3)),
            Payment(bedrag=Decimal("100.00"), valuta="EUR", tegenpartij_naam="Energieleverancier",
                    tegenpartij_iban="NL91ABNA0417164300", omschrijving="Energie", datum=date(2026, 5, 3)),
            Payment(bedrag=Decimal("100.00"), valuta="EUR", tegenpartij_naam="Energieleverancier",
                    tegenpartij_iban="NL91ABNA0417164300", omschrijving="Energie", datum=date(2026, 6, 3)),
        ]


@pytest.fixture
def opzet(tmp_path, monkeypatch):
    import webapp.app as appmodule
    import kamerverhuur_scanner.runner as runner_module
    monkeypatch.setattr(appmodule, "SheetClient", FakeSheetClient)
    monkeypatch.setattr(runner_module, "BunqClient", FakeBunqClient)
    FakeSheetClient.kamers = [Tenant(row_index=2, naam="Jan", kamer="1", verwacht_bedrag=Decimal("650.00"))]

    properties_file = tmp_path / "properties.json"
    properties_file.write_text(json.dumps([
        {"slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "fake",
         "bunq_rekening_iban": "NL81BUNQ2163127125", "onderhoud_reserve_per_maand": "60.00"},
        {"slug": "baumannlaan", "naam": "Burgemeester Baumannlaan 70b", "google_sheet_id": "fake2",
         "bunq_rekening_iban": "NL00OTHER0000000000"},
    ]))
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({
        "beheerder": {"wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": True, "panden": []},
        "justin": {
            "wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": False,
            "panden": ["mahoniestraat"],
        },
    }))
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config = Config(
        google_service_account_file="fake.json", properties_file=str(properties_file),
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file=str(users_file), flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14, state_dir=str(state_dir),
    )
    app = create_app(config)
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    return client, config


def test_winstberekening_toont_inkomsten_lasten_en_winst(opzet):
    client, _config = opzet
    resp = client.get("/pand/mahoniestraat/winst")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Energieleverancier" in body
    # 650 inkomsten - 100 (last) - 75 (belasting) - 60 (onderhoud) = 415 winst
    assert "415,00" in body
    assert "60,00" in body  # onderhoudsreserve
    assert "75,00" in body  # belasting


def test_winstberekening_legt_snapshot_vast(opzet):
    client, config = opzet
    assert state.laad_winst_geschiedenis("mahoniestraat", config.state_dir) == []
    client.get("/pand/mahoniestraat/winst")
    geschiedenis = state.laad_winst_geschiedenis("mahoniestraat", config.state_dir)
    assert len(geschiedenis) == 1


def test_dashboard_toont_bereken_zonder_snapshot(opzet):
    client, _config = opzet
    resp = client.get("/pand/mahoniestraat/")
    assert "Bereken" in resp.get_data(as_text=True)


def test_dashboard_toont_laatste_winst_na_bezoek_winstpagina(opzet):
    client, _config = opzet
    client.get("/pand/mahoniestraat/winst")  # legt een snapshot vast
    resp = client.get("/pand/mahoniestraat/")
    body = resp.get_data(as_text=True)
    assert "winstberekening" in body.lower()
    assert "Bereken" not in body


def test_winst_overzicht_combineert_meerdere_panden(opzet):
    client, config = opzet
    state.voeg_winst_snapshot_toe("mahoniestraat", Decimal("1000.00"), config.state_dir)
    state.voeg_winst_snapshot_toe("baumannlaan", Decimal("500.00"), config.state_dir)

    resp = client.get("/winst-overzicht")
    assert resp.status_code == 200


def test_winst_overzicht_toont_optelsom_per_pand(opzet):
    client, config = opzet
    # justin heeft ook toegang tot mahoniestraat -> 2 beheerders, dus 1000/2 = 500 "jouw deel"
    state.voeg_winst_snapshot_toe("mahoniestraat", Decimal("1000.00"), config.state_dir)
    state.voeg_winst_snapshot_toe("baumannlaan", Decimal("500.00"), config.state_dir)

    resp = client.get("/winst-overzicht")
    body = resp.get_data(as_text=True)
    assert "Mahoniestraat 15" in body
    assert "Burgemeester Baumannlaan 70b" in body
    assert "1.000,00" in body  # laatste winst mahoniestraat
    assert body.count("500,00") >= 2  # jouw deel mahoniestraat (verdeeld) + laatste winst baumannlaan
    assert "1.000,00" in body  # totaal: 500 (mahoniestraat verdeeld) + 500 (baumannlaan) = 1000


def test_winst_overzicht_pand_zonder_snapshot_toont_streepje(opzet):
    client, config = opzet
    state.voeg_winst_snapshot_toe("mahoniestraat", Decimal("1000.00"), config.state_dir)
    # baumannlaan heeft bewust geen snapshot

    resp = client.get("/winst-overzicht")
    body = resp.get_data(as_text=True)
    assert "nog geen winst-datapunt" in body.lower()


def test_pandkiezer_toont_totaal_overzicht_knop(opzet):
    client, _config = opzet
    resp = client.get("/")
    body = resp.get_data(as_text=True)
    assert "Totaal overzicht" in body
    assert "/winst-overzicht" in body


def test_totaal_overzicht_toont_totale_winst_alle_panden(opzet):
    client, config = opzet
    # baumannlaan heeft in deze fixture maar 1 beheerder ("beheerder" zelf,
    # via alle_panden) - justin heeft alleen toegang tot mahoniestraat.
    state.voeg_winst_snapshot_toe("baumannlaan", Decimal("500.00"), config.state_dir)

    resp = client.get("/winst-overzicht")
    body = resp.get_data(as_text=True)
    assert "totale winst alle panden" in body.lower()
    assert "500,00" in body


def test_totaal_overzicht_verdeelt_winst_bij_meerdere_beheerders(opzet):
    client, config = opzet
    state.voeg_winst_snapshot_toe("mahoniestraat", Decimal("1000.00"), config.state_dir)
    # justin heeft ook toegang tot mahoniestraat, dus de winst van dat pand
    # moet hier door 2 gedeeld worden (500,00) - baumannlaan blijft onverdeeld.
    state.voeg_winst_snapshot_toe("baumannlaan", Decimal("500.00"), config.state_dir)

    resp = client.get("/winst-overzicht")
    body = resp.get_data(as_text=True)
    assert "1.000,00" in body  # 500 (mahoniestraat, verdeeld) + 500 (baumannlaan, onverdeeld)


def test_testaccount_telt_niet_mee_als_beheerder_in_winstverdeling(opzet):
    from werkzeug.security import generate_password_hash

    client, config = opzet
    # Een testaccount met toegang tot alle panden toevoegen mag de winstverdeling
    # niet veranderen: mahoniestraat blijft door 2 (beheerder + justin), niet 3.
    users = json.loads(open(config.users_file).read())
    users["kijker"] = {
        "wachtwoord_hash": generate_password_hash("geheim123"),
        "alle_panden": True, "panden": [], "test_account": True,
    }
    open(config.users_file, "w").write(json.dumps(users))

    state.voeg_winst_snapshot_toe("mahoniestraat", Decimal("1000.00"), config.state_dir)
    state.voeg_winst_snapshot_toe("baumannlaan", Decimal("500.00"), config.state_dir)

    resp = client.get("/winst-overzicht")
    body = resp.get_data(as_text=True)
    assert "1.000,00" in body  # 500 (mahoniestraat / 2 beheerders) + 500 (baumannlaan)
    assert "333,33" not in body  # niet door 3 gedeeld


def test_totaal_overzicht_telt_betalingen_deze_maand_uit_cache(opzet):
    from kamerverhuur_scanner.models import Status, TenantResult

    client, config = opzet
    # Twee panden met elk een gecachete controle: mahoniestraat 1 betaald van 2,
    # baumannlaan 1 betaald van 1 -> samen 2/3 betaald, ontvangen 1200 van 1950.
    state.save("mahoniestraat", [
        TenantResult(tenant=Tenant(row_index=2, naam="A", kamer="1", verwacht_bedrag=Decimal("650.00")),
                     ontvangen_bedrag=Decimal("650.00"), status=Status.BETAALD),
        TenantResult(tenant=Tenant(row_index=3, naam="B", kamer="2", verwacht_bedrag=Decimal("650.00")),
                     ontvangen_bedrag=Decimal("0.00"), status=Status.NIET_ONTVANGEN),
    ], 0, config.state_dir)
    state.save("baumannlaan", [
        TenantResult(tenant=Tenant(row_index=2, naam="C", kamer="1", verwacht_bedrag=Decimal("650.00")),
                     ontvangen_bedrag=Decimal("550.00"), status=Status.BETAALD),
    ], 0, config.state_dir)

    resp = client.get("/winst-overzicht")
    body = resp.get_data(as_text=True)
    assert "2/3" in body  # betalingen binnen deze maand
    assert "1.200,00" in body  # totaal ontvangen (650 + 550)
    assert "1.950,00" in body  # totaal verwacht (3 x 650)


def test_totaal_overzicht_toont_komende_maand_uitsplitsing_per_pand(opzet, monkeypatch):
    from kamerverhuur_scanner.models import Status, TenantResult
    import webapp.app as appmodule

    client, _config = opzet

    def _fake_run_check(config, pand, dry_run, vandaag):
        if pand.slug == "mahoniestraat":
            results = [
                TenantResult(tenant=Tenant(row_index=2, naam="A", kamer="1", verwacht_bedrag=Decimal("650.00")),
                             ontvangen_bedrag=Decimal("650.00"), status=Status.BETAALD),
                TenantResult(tenant=Tenant(row_index=3, naam="B", kamer="2", verwacht_bedrag=Decimal("650.00")),
                             ontvangen_bedrag=Decimal("0.00"), status=Status.NIET_ONTVANGEN),
            ]
        else:  # baumannlaan: niemand vooruitbetaald -> mag niet in de uitsplitsing komen
            results = [
                TenantResult(tenant=Tenant(row_index=2, naam="C", kamer="1", verwacht_bedrag=Decimal("650.00")),
                             ontvangen_bedrag=Decimal("0.00"), status=Status.NIET_ONTVANGEN),
            ]
        return [], results, []

    monkeypatch.setattr(appmodule, "run_check", _fake_run_check)

    # Vóór verversen: de komende maand is nog niet opgehaald (snelle laadpagina)
    resp = client.get("/winst-overzicht")
    assert "Nog niet opgehaald" in resp.get_data(as_text=True)

    # Ververs-knop haalt live op en cachet het resultaat
    client.post("/winst-overzicht/ververs-komende-maand")

    resp = client.get("/winst-overzicht")
    body = resp.get_data(as_text=True)
    # 1 van 3 vooruitbetaald voor komende maand, uitgesplitst per pand
    assert "1/3" in body  # totaal vooruitbetaald komende maand
    # de uitsplitsing per pand toont alleen panden die bijdragen (mahoniestraat 1/2)
    uitsplitsing = body.split('<ul class="komend-per-pand">')[1].split("</ul>")[0]
    assert "Mahoniestraat 15" in uitsplitsing
    assert "1/2" in uitsplitsing
    assert "Burgemeester Baumannlaan 70b" not in uitsplitsing  # draagt niets bij


# --- Negeerlijst ---


def test_winstpagina_toont_kruisje_per_last(opzet):
    client, _config = opzet
    resp = client.get("/pand/mahoniestraat/winst")
    body = resp.get_data(as_text=True)
    assert 'action="/pand/mahoniestraat/winst/negeer"' in body
    assert 'value="nl91abna0417164300"' in body


def test_last_negeren_verdwijnt_van_winstpagina(opzet):
    client, _config = opzet
    resp = client.post(
        "/pand/mahoniestraat/winst/negeer",
        data={"sleutel": "nl91abna0417164300", "omschrijving": "Energieleverancier"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "telt niet meer mee" in body.lower()
    # 'Energieleverancier' staat nog wel in de flash-melding, maar niet meer
    # in de lastentabel zelf (dat zou 2 losse plekken opleveren).
    assert body.count("Energieleverancier") == 1


def test_genegeerde_last_staat_op_negeerlijst(opzet):
    client, config = opzet
    state.negeer_last("mahoniestraat", "nl91abna0417164300", "Energieleverancier", config.state_dir)

    resp = client.get("/pand/mahoniestraat/winst/negeerlijst")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Energieleverancier" in body


def test_negeerlijst_zonder_items_toont_nette_melding(opzet):
    client, _config = opzet
    resp = client.get("/pand/mahoniestraat/winst/negeerlijst")
    assert "nog niets genegeerd" in resp.get_data(as_text=True).lower()


def test_negeerlijst_herstellen_laat_last_weer_meetellen(opzet):
    client, config = opzet
    state.negeer_last("mahoniestraat", "nl91abna0417164300", "Energieleverancier", config.state_dir)

    resp = client.post(
        "/pand/mahoniestraat/winst/negeerlijst/herstel",
        data={"sleutel": "nl91abna0417164300"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "weer teruggezet" in resp.get_data(as_text=True).lower()
    assert state.laad_genegeerde_lasten("mahoniestraat", config.state_dir) == {}

    # en de last verschijnt weer op de winstpagina
    body = client.get("/pand/mahoniestraat/winst").get_data(as_text=True)
    assert "Energieleverancier" in body


# --- Huurinkomsten-specificatie ---


def test_winstberekening_toont_huurinkomsten_specificatie_per_kamer(opzet):
    client, _config = opzet
    resp = client.get("/pand/mahoniestraat/winst")
    body = resp.get_data(as_text=True)
    assert "Huurinkomsten" in body
    assert "<td>1</td>" in body
    assert "<td>Jan</td>" in body


def test_winstberekening_gebruikt_nominale_huur_niet_werkelijk_ontvangen_bedrag(opzet):
    client, _config = opzet
    # Henri betaalde deze maand een ingelopen achterstand mee - dat mag de
    # winstberekening niet vertekenen: alleen de nominale huur telt.
    FakeSheetClient.kamers = [Tenant(
        row_index=2, naam="Henri", kamer="1", verwacht_bedrag=Decimal("650.00"),
        contract_startdatum="05-07-2026", borg_bedrag=Decimal("500.00"),
    )]

    resp = client.get("/pand/mahoniestraat/winst")
    body = resp.get_data(as_text=True)
    assert "Henri" in body
    # 650 nominale huur, geen spoor van een hoger, werkelijk ontvangen bedrag
    assert "650,00" in body
    assert "1.150,00" not in body
    assert "1.000,00" not in body
