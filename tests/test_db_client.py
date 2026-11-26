"""Tests voor de SQLite-hoofddatabase: de panden-opslag (db.py) en de DbClient
(db_client.py), de drop-in vervanger van de oude SheetClient. Draait volledig in
de sandbox - SQLite heeft geen externe dependencies, geen Google-verbinding."""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from kamerverhuur_scanner import db
from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.db_client import DbClient
from kamerverhuur_scanner.models import (
    Aanmelding,
    Pand,
    Payment,
    Status,
    Tenant,
    TenantResult,
)


def _config(tmp_path) -> Config:
    return Config(
        google_service_account_file="fake.json",
        properties_file=str(tmp_path / "properties.json"),
        bunq_conf_file="fake.conf",
        bunq_environment="PRODUCTION",
        bunq_api_key=None,
        users_file=str(tmp_path / "users.json"),
        flask_secret_key="test",
        bedrag_tolerantie=Decimal("0.01"),
        vooruitbetaling_dagen=14,
        state_dir=str(tmp_path),
    )


def _pand(slug="menkemaborgstraat") -> Pand:
    return Pand(
        slug=slug, naam="Menkemaborgstraat 6", google_sheet_id="x",
        google_sheet_worksheet="Huurders", history_worksheet="Historie",
        bunq_rekening_iban="NL00TEST0000000000",
    )


@pytest.fixture
def client(tmp_path):
    cfg = _config(tmp_path)
    return DbClient(cfg, _pand()), cfg


# --- Kamers / huurders ----------------------------------------------------

def test_lege_database_geeft_geen_kamers(client):
    c, _ = client
    assert c.get_kamers() == []
    assert c.get_tenants() == []


def test_kamer_toevoegen_en_bewerken_rondrit(client):
    c, _ = client
    rij = c.voeg_kamer_toe("Kamer 1")
    c.update_kamer(
        row_index=rij, naam="Jan Jansen", kamer="Kamer 1",
        verwacht_bedrag=Decimal("550.00"), iban="nl00 bunq 0123", zoekwoord="jan",
        kale_huurprijs=Decimal("500"), servicekosten=Decimal("50"),
        contract_einddatum="01-07-2027", opmerking="let op", email="jan@x.nl",
        telefoonnummer="0612345678", borg_bedrag=Decimal("550"),
    )
    kamers = c.get_kamers()
    assert len(kamers) == 1
    k = kamers[0]
    assert k.row_index == rij
    assert k.naam == "Jan Jansen"
    assert k.kamer == "Kamer 1"
    assert k.verwacht_bedrag == Decimal("550.00")
    assert k.iban == "NL00BUNQ0123"  # genormaliseerd (hoofdletters, geen spaties)
    assert k.kale_huurprijs == Decimal("500.00")
    assert k.servicekosten == Decimal("50.00")
    assert k.telefoonnummer == "0612345678"  # voorloop-nul behouden
    assert k.borg_bedrag == Decimal("550.00")
    assert k.email == "jan@x.nl"
    assert c.get_tenants() == kamers  # heeft een huurder


def test_lege_huurder_is_wel_kamer_niet_tenant(client):
    c, _ = client
    c.voeg_kamer_toe("Kamer 2")  # geen naam
    assert len(c.get_kamers()) == 1
    assert c.get_tenants() == []


def test_kamer_zonder_kamernaam_wordt_overgeslagen(client):
    c, _ = client
    c.voeg_kamer_toe("")  # lege kamernaam -> telt niet mee (zoals de somrij-filter vroeger)
    assert c.get_kamers() == []


def test_update_aanbod_laat_huurdervelden_met_rust(client):
    c, _ = client
    rij = c.voeg_kamer_toe("Kamer 1")
    c.update_kamer(row_index=rij, naam="Jan", kamer="Kamer 1",
                   verwacht_bedrag=Decimal("500"), iban=None, zoekwoord=None)
    c.update_aanbod(rij, beschikbaar=True, omschrijving="Mooie kamer", map_id="map123",
                    prijs=Decimal("600"), oppervlakte="18 m2", aanbod_verhuurd=False)
    k = c.get_kamers()[0]
    assert k.naam == "Jan"  # niet overschreven door update_aanbod
    assert k.beschikbaar is True
    assert k.advertentie_omschrijving == "Mooie kamer"
    assert k.advertentie_map_id == "map123"
    assert k.advertentie_prijs == Decimal("600.00")
    assert k.advertentie_oppervlakte == "18 m2"
    assert k.aanbod_verhuurd is False


def test_aanbod_verhuurd_vlag(client):
    c, _ = client
    rij = c.voeg_kamer_toe("Kamer 1")
    c.update_aanbod(rij, beschikbaar=False, omschrijving=None, map_id=None, aanbod_verhuurd=True)
    assert c.get_kamers()[0].aanbod_verhuurd is True


def test_studenten_verplicht_standaard_aan_en_omzetbaar(client):
    c, _ = client
    rij = c.voeg_kamer_toe("Kamer 1")
    # Nieuwe kamer: standaard student verplicht (behoudt bestaand gedrag).
    assert c.get_kamers()[0].studenten_verplicht is True
    c.update_aanbod(rij, beschikbaar=True, omschrijving=None, map_id=None, studenten_verplicht=False)
    assert c.get_kamers()[0].studenten_verplicht is False
    c.update_aanbod(rij, beschikbaar=True, omschrijving=None, map_id=None, studenten_verplicht=True)
    assert c.get_kamers()[0].studenten_verplicht is True


def test_migratie_voegt_studenten_verplicht_kolom_toe():
    # Een oude huurders-tabel zonder de kolom -> _migreer_kolommen() voegt 'm
    # idempotent toe (default 1 = True). Direct op de helper getest, los van het
    # volledige schema.
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE huurders (id INTEGER PRIMARY KEY, pand_slug TEXT, kamer TEXT)")
    conn.execute("INSERT INTO huurders (pand_slug, kamer) VALUES ('p', 'Kamer 1')")

    db._migreer_kolommen(conn)
    kolommen = {r["name"] for r in conn.execute("PRAGMA table_info(huurders)")}
    assert "studenten_verplicht" in kolommen
    assert conn.execute("SELECT studenten_verplicht FROM huurders").fetchone()[0] == 1  # default True

    db._migreer_kolommen(conn)  # nog een keer: geen fout (idempotent)
    conn.close()


def test_update_kamer_raakt_aanbod_niet(client):
    c, _ = client
    rij = c.voeg_kamer_toe("Kamer 1")
    c.update_aanbod(rij, beschikbaar=True, omschrijving="Adv", map_id=None)
    c.update_kamer(row_index=rij, naam="Piet", kamer="Kamer 1",
                   verwacht_bedrag=Decimal("500"), iban=None, zoekwoord=None)
    k = c.get_kamers()[0]
    assert k.beschikbaar is True  # update_kamer liet dit met rust
    assert k.advertentie_omschrijving == "Adv"


def test_kamer_verwijderen(client):
    c, _ = client
    rij1 = c.voeg_kamer_toe("Kamer 1", "Jan")
    c.voeg_kamer_toe("Kamer 2", "Piet")
    c.verwijder_kamer(rij1)
    kamers = c.get_kamers()
    assert [k.kamer for k in kamers] == ["Kamer 2"]


def test_volgorde_blijft_invoegvolgorde(client):
    c, _ = client
    for naam in ["A", "B", "C"]:
        c.voeg_kamer_toe(naam)
    assert [k.kamer for k in c.get_kamers()] == ["A", "B", "C"]


# --- write_results --------------------------------------------------------

def _tenant(c, kamer, naam, verwacht):
    rij = c.voeg_kamer_toe(kamer, naam)
    c.update_kamer(row_index=rij, naam=naam, kamer=kamer,
                   verwacht_bedrag=verwacht, iban=None, zoekwoord=None)
    return next(k for k in c.get_kamers() if k.row_index == rij)


def test_write_results_schrijft_status(client):
    c, _ = client
    t = _tenant(c, "Kamer 1", "Jan", Decimal("500"))
    c.write_results([TenantResult(tenant=t, ontvangen_bedrag=Decimal("500"), status=Status.BETAALD)])
    conn = db.verbind(_config_from(c))
    try:
        row = conn.execute("SELECT status, ontvangen_bedrag FROM huurders WHERE id = ?", (t.row_index,)).fetchone()
    finally:
        conn.close()
    assert row["status"] == Status.BETAALD.value
    assert row["ontvangen_bedrag"] == "500.00"


def _config_from(c: DbClient) -> Config:
    return c._config


# --- Historie -------------------------------------------------------------

def test_upsert_history_maakt_en_werkt_bij(client):
    c, _ = client
    t = _tenant(c, "Kamer 1", "Jan", Decimal("500"))
    betaling = Payment(bedrag=Decimal("500"), valuta="EUR", tegenpartij_naam="Jan",
                       tegenpartij_iban="NL00", omschrijving="huur", datum=date(2026, 6, 3))
    res = TenantResult(tenant=t, ontvangen_bedrag=Decimal("500"), status=Status.BETAALD,
                       gematchte_betalingen=[betaling])
    c.upsert_history([res], "2026-06")
    # Tweede keer binnen dezelfde maand -> nog steeds 1 regel (upsert, geen dubbele).
    c.upsert_history([res], "2026-06")
    regels = c.get_geschiedenis("Kamer 1")
    assert len(regels) == 1
    r = regels[0]
    assert r.maand == "2026-06"
    assert r.huurder == "Jan"
    assert r.status == Status.BETAALD
    assert r.verwacht_bedrag == Decimal("500.00")
    assert r.ontvangen_bedrag == Decimal("500.00")
    assert r.betaaldatum == date(2026, 6, 3)


def test_upsert_history_bevriest_huurdernaam(client):
    c, _ = client
    t = _tenant(c, "Kamer 1", "Jan", Decimal("500"))
    c.upsert_history([TenantResult(tenant=t, ontvangen_bedrag=Decimal("500"), status=Status.BETAALD)], "2026-06")
    # Nieuwe huurder ingevoerd, maar de bestaande junimaand-regel moet "Jan" houden.
    t2 = Tenant(row_index=t.row_index, naam="Piet", kamer="Kamer 1", verwacht_bedrag=Decimal("500"))
    c.upsert_history([TenantResult(tenant=t2, ontvangen_bedrag=Decimal("0"), status=Status.NIET_ONTVANGEN)], "2026-06")
    regels = c.get_geschiedenis("Kamer 1")
    assert len(regels) == 1
    assert regels[0].huurder == "Jan"  # bevroren


def test_upsert_history_meerdere_maanden_apart(client):
    c, _ = client
    t = _tenant(c, "Kamer 1", "Jan", Decimal("500"))
    for maand in ["2026-05", "2026-06", "2026-07"]:
        c.upsert_history([TenantResult(tenant=t, ontvangen_bedrag=Decimal("500"), status=Status.BETAALD)], maand)
    regels = c.get_geschiedenis("Kamer 1")
    assert [r.maand for r in regels] == ["2026-05", "2026-06", "2026-07"]  # gesorteerd


def test_verwijder_geschiedenis_voor_instapdatum(client):
    c, _ = client
    t = _tenant(c, "Kamer 1", "Jan", Decimal("500"))
    for maand in ["2026-03", "2026-04", "2026-05"]:
        c.upsert_history([TenantResult(tenant=t, ontvangen_bedrag=Decimal("500"), status=Status.BETAALD)], maand)
    verwijderd = c.verwijder_geschiedenis_voor_instapdatum("Kamer 1", "Jan", "2026-05")
    assert verwijderd == 2
    assert [r.maand for r in c.get_geschiedenis("Kamer 1")] == ["2026-05"]


def test_verwijder_geschiedenis_laat_andere_huurder_met_rust(client):
    c, _ = client
    t = _tenant(c, "Kamer 1", "Jan", Decimal("500"))
    c.upsert_history([TenantResult(tenant=t, ontvangen_bedrag=Decimal("500"), status=Status.BETAALD)], "2026-01")
    # andere huurder, zelfde kamer, andere maand (historie is op kamernaam gesleuteld,
    # maar de naam staat in de regel - verwijderen filtert ook op naam).
    t2 = Tenant(row_index=t.row_index, naam="Piet", kamer="Kamer 1", verwacht_bedrag=Decimal("500"))
    c.upsert_history([TenantResult(tenant=t2, ontvangen_bedrag=Decimal("500"), status=Status.BETAALD)], "2026-02")
    verwijderd = c.verwijder_geschiedenis_voor_instapdatum("Kamer 1", "Piet", "2026-06")
    assert verwijderd == 1  # alleen Piets regel
    overig = c.get_geschiedenis("Kamer 1")
    assert {r.huurder for r in overig} == {"Jan"}


def test_dedupliceer_is_noop(client):
    c, _ = client
    assert c.dedupliceer_geschiedenis() == 0


# --- Aanmeldingen ---------------------------------------------------------

def _aanmelding(naam="Kees"):
    return Aanmelding(
        naam=naam, email="kees@x.nl", telefoon="0611112222", huidig_adres="Straat 1",
        studie="Bouwkunde", studentnummer="s123", gewenste_ingangsdatum="2026-08-01",
        gewenste_huurduur="1 jaar", inkomstenbron="DUO", inkomsten_bedrag="400",
        borgsteller="ouder", bezichtiging="ja", videobel_nummer="",
        bewijs_inschrijving_link="http://x", borgsteller_naam="Ouder K",
        borgsteller_relatie="vader", borgsteller_email="ouder@x.nl",
    )


def test_aanmeldingen_toevoegen_en_lezen(client):
    c, _ = client
    c.add_aanmelding("Kamer 1", _aanmelding("Kees"))
    c.add_aanmelding("Kamer 2", _aanmelding("Lisa"))
    rijen = c.get_aanmeldingen()
    assert len(rijen) == 2
    # kolomvolgorde = _AANMELDINGEN_HEADER (datum, kamer, naam, email, ...)
    assert rijen[0][1] == "Kamer 1"
    assert rijen[0][2] == "Kees"
    assert rijen[0][3] == "kees@x.nl"
    assert rijen[1][2] == "Lisa"
    assert all(len(r) == 19 for r in rijen)


def test_wis_aanmeldingen(client):
    c, _ = client
    c.add_aanmelding("Kamer 1", _aanmelding())
    c.wis_aanmeldingen()
    assert c.get_aanmeldingen() == []


# --- Bezichtigingen -------------------------------------------------------

def _afspraak(naam="Kees", kamer="Kamer 1"):
    return {
        "tijd_start": "14:00", "tijd_eind": "14:20", "kamer": kamer, "naam": naam,
        "email": "kees@x.nl", "telefoon": "0611112222", "bezichtiging": "fysiek",
        "bel_nummer": "",
    }


def test_bezichtigingen_toevoegen_lezen_verwijderen(client):
    c, _ = client
    c.add_bezichtiging("2026-08-10", _afspraak("Kees"))
    c.add_bezichtiging("2026-08-10", _afspraak("Lisa"))
    met_nr = c.get_bezichtigingen_met_rijnummer()
    assert len(met_nr) == 2
    assert [rij[4] for _id, rij in met_nr] == ["Kees", "Lisa"]  # kolom 5 = naam
    assert c.get_bezichtigingen() == [rij for _id, rij in met_nr]
    # verwijder de eerste
    eerste_id = met_nr[0][0]
    c.verwijder_bezichtiging(eerste_id)
    resterend = c.get_bezichtigingen_met_rijnummer()
    assert [rij[4] for _id, rij in resterend] == ["Lisa"]


def test_bezichtiging_reactie_via_token(client):
    c, _ = client
    c.add_bezichtiging("2026-08-10", _afspraak("Kees"), token="kees-token")
    c.add_bezichtiging("2026-08-10", _afspraak("Lisa"), token="lisa-token")

    # vers = nog geen reactie
    rijk = {b["naam"]: b for b in c.get_bezichtigingen_rijk()}
    assert rijk["Kees"]["reactie"] == "" and rijk["Kees"]["token"] == "kees-token"

    # Kees bevestigt, Lisa zegt af
    bevestigd = c.zet_reactie_via_token("kees-token", "bevestigd")
    assert bevestigd["naam"] == "Kees" and bevestigd["reactie"] == "bevestigd"
    assert bevestigd["reactie_op"]  # tijdstempel gezet
    assert c.zet_reactie_via_token("lisa-token", "afgezegd")["reactie"] == "afgezegd"

    rijk = {b["naam"]: b for b in c.get_bezichtigingen_rijk()}
    assert rijk["Kees"]["reactie"] == "bevestigd"
    assert rijk["Lisa"]["reactie"] == "afgezegd"

    # laatste klik wint (van gedachten veranderd)
    assert c.zet_reactie_via_token("lisa-token", "bevestigd")["reactie"] == "bevestigd"

    # onbekende token -> None
    assert c.zet_reactie_via_token("bestaat-niet", "bevestigd") is None
    assert c.zet_reactie_via_token("", "bevestigd") is None


def test_bezichtiging_token_is_pandgebonden(client, tmp_path):
    c, cfg = client
    c.add_bezichtiging("2026-08-10", _afspraak("Kees"), token="gedeelde-token")
    # een ander pand mag met dezelfde token niets kunnen wijzigen
    ander = DbClient(cfg, _pand(slug="ander-pand"))
    assert ander.zet_reactie_via_token("gedeelde-token", "afgezegd") is None
    assert c.get_bezichtigingen_rijk()[0]["reactie"] == ""


# --- Vertrokken huurders --------------------------------------------------

def test_archiveer_en_lees_vertrokken(client):
    c, _ = client
    kamer = Tenant(row_index=1, naam="Jan", kamer="Kamer 1", verwacht_bedrag=Decimal("500"),
                   email="jan@x.nl", telefoonnummer="0612345678", contract_einddatum="01-01-2020")
    c.archiveer_vertrokken_huurder(kamer)
    allen = c.get_alle_vertrokken_huurders()
    assert len(allen) == 1
    v = allen[0]
    assert v.naam == "Jan"
    assert v.kamer == "Kamer 1"
    assert v.email == "jan@x.nl"
    assert v.vertrokken_op == date.today()
    assert v.row_index >= 1
    # opvraagbaar op row_index
    assert c.get_vertrokken_huurder(v.row_index).naam == "Jan"
    assert c.get_vertrokken_huurder(99999) is None


def test_archiveer_lege_naam_doet_niets(client):
    c, _ = client
    c.archiveer_vertrokken_huurder(Tenant(row_index=1, naam="", kamer="Kamer 1", verwacht_bedrag=Decimal("0")))
    assert c.get_alle_vertrokken_huurders() == []


def test_recent_vertrokken_filtert_op_termijn(client):
    c, _ = client
    # Contract einddatum lang geleden -> valt buiten de 31-dagen-termijn.
    oud = Tenant(row_index=1, naam="Oud", kamer="Kamer 1", verwacht_bedrag=Decimal("0"),
                 contract_einddatum="01-01-2020")
    c.archiveer_vertrokken_huurder(oud)
    assert c.get_alle_vertrokken_huurders()  # staat er wel permanent
    assert c.get_recent_vertrokken_huurders() == []  # maar niet "recent"


# --- Pand-isolatie --------------------------------------------------------

def test_panden_zijn_geisoleerd(tmp_path):
    cfg = _config(tmp_path)
    a = DbClient(cfg, _pand("pand-a"))
    b = DbClient(cfg, _pand("pand-b"))
    a.voeg_kamer_toe("Kamer A", "Jan")
    b.voeg_kamer_toe("Kamer B", "Piet")
    assert [k.kamer for k in a.get_kamers()] == ["Kamer A"]
    assert [k.kamer for k in b.get_kamers()] == ["Kamer B"]


# --- Panden-opslag (db.py) ------------------------------------------------

def test_pand_opslaan_en_laden(tmp_path):
    cfg = _config(tmp_path)
    gegevens = {
        "naam": "Mahoniestraat 15", "google_sheet_id": "sheet123",
        "bunq_rekening_iban": "NL00 BUNQ 0000 1111", "extra_bcc": ["a@x.nl", "b@x.nl"],
        "postcode": "3000AA", "plaats": "Rotterdam",
        "verhuurders": [{"naam": "Jurian", "adres": "Ergens 1"}],
        "heeft_bold_slot": True, "hypotheek_rente_per_maand": "850,50",
        "hypotheek_schuld": "200000",
        "aantal_eigenaren": "2", "sleutels": ["voordeur", "berging"], "kleur": "#1b7a43",
    }
    db.zet_pand(cfg, "mahoniestraat", gegevens)
    panden = db.laad_panden(cfg)
    assert len(panden) == 1
    p = panden[0]
    assert p.slug == "mahoniestraat"
    assert p.naam == "Mahoniestraat 15"
    assert p.bunq_rekening_iban == "NL00BUNQ00001111"  # genormaliseerd
    assert p.extra_bcc == ["a@x.nl", "b@x.nl"]
    assert p.verhuurders[0].naam == "Jurian"
    assert p.hypotheek_rente_per_maand == Decimal("850.50")
    assert p.hypotheek_schuld == Decimal("200000")
    assert p.aantal_eigenaren == 2
    assert p.sleutels == ["voordeur", "berging"]
    assert p.kleur == "#1b7a43"


def test_pand_bijwerken_op_slug(tmp_path):
    cfg = _config(tmp_path)
    db.zet_pand(cfg, "x", {"naam": "Oud", "google_sheet_id": "s", "bunq_rekening_iban": "NL00"})
    db.zet_pand(cfg, "x", {"naam": "Nieuw", "google_sheet_id": "s", "bunq_rekening_iban": "NL00"})
    panden = db.laad_panden(cfg)
    assert len(panden) == 1
    assert panden[0].naam == "Nieuw"


def test_pand_verwijderen_ruimt_kamers_op(tmp_path):
    cfg = _config(tmp_path)
    db.zet_pand(cfg, "x", {"naam": "X", "google_sheet_id": "s", "bunq_rekening_iban": "NL00"})
    DbClient(cfg, _pand("x")).voeg_kamer_toe("Kamer 1", "Jan")
    db.verwijder_pand(cfg, "x")
    assert db.laad_panden(cfg) == []
    assert DbClient(cfg, _pand("x")).get_kamers() == []


def test_lege_optionele_bedragen_blijven_none(tmp_path):
    cfg = _config(tmp_path)
    db.zet_pand(cfg, "x", {
        "naam": "X", "google_sheet_id": "s", "bunq_rekening_iban": "NL00",
        "hypotheek_rente_per_maand": None, "aantal_eigenaren": None, "hypotheek_schuld": None,
    })
    p = db.laad_panden(cfg)[0]
    assert p.hypotheek_rente_per_maand is None
    assert p.hypotheek_schuld is None
    assert p.aantal_eigenaren is None


def test_panden_volgorde_blijft(tmp_path):
    cfg = _config(tmp_path)
    for slug in ["een", "twee", "drie"]:
        db.zet_pand(cfg, slug, {"naam": slug, "google_sheet_id": "s", "bunq_rekening_iban": "NL00"})
    assert [p.slug for p in db.laad_panden(cfg)] == ["een", "twee", "drie"]
