"""Tests voor de kolomparsing/-opslag van SheetClient, zonder een echte Google
Sheets-verbinding: we bouwen een SheetClient met een neppe worksheet."""
import re
from datetime import date, timedelta
from decimal import Decimal

from kamerverhuur_scanner.models import Aanmelding, Pand, Payment, Status, Tenant, TenantResult
from kamerverhuur_scanner.sheet_client import (
    _AANMELDINGEN_HEADER,
    _BEZICHTIGINGEN_HEADER,
    SheetClient,
)


class FakeWorksheet:
    def __init__(self, rows, col_count=26):
        self._rows = rows
        self.batch_updates = []
        self.appended_rows = []
        self.laatste_value_input_option = None
        self.col_count = col_count
        self.resize_aanroepen = []

    def get_all_values(self):
        return self._rows

    def resize(self, rows=None, cols=None):
        self.resize_aanroepen.append({"rows": rows, "cols": cols})
        if cols is not None:
            self.col_count = cols

    def batch_update(self, updates, value_input_option="USER_ENTERED"):
        self.laatste_value_input_option = value_input_option
        self.batch_updates.append(updates)
        for u in updates:
            # simuleer het effect op _rows, zodat opeenvolgende aanroepen
            # (bv. get_all_values erna) de update ook echt terugzien - de
            # kolomletter(s) doen er hier niet toe (kan ook "AA2" zijn), alleen
            # het rijnummer (de cijfers aan het einde van de A1-notatie).
            rij = int(re.search(r"\d+", u["range"].split(":")[0]).group())
            while len(self._rows) <= rij - 1:
                self._rows.append([])
            self._rows[rij - 1] = u["values"][0]

    def append_rows(self, rows, value_input_option="USER_ENTERED"):
        self.laatste_value_input_option = value_input_option
        self.appended_rows.extend(rows)
        self._rows.extend(rows)

    def append_row(self, row, value_input_option="USER_ENTERED"):
        self.laatste_value_input_option = value_input_option
        self.appended_rows.append(row)
        self._rows.append(row)

    def delete_rows(self, start_index, end_index=None):
        del self._rows[start_index - 1:(end_index or start_index)]

    def clear(self):
        self._rows = []


def _sheet_client(rows) -> tuple[SheetClient, FakeWorksheet]:
    client = object.__new__(SheetClient)
    client._pand = Pand(
        slug="test", naam="Test", google_sheet_id="x", google_sheet_worksheet="y",
        history_worksheet="Historie", bunq_rekening_iban="NL00TEST0000000000",
    )
    ws = FakeWorksheet(rows)
    client._worksheet = ws
    return client, ws


def _sheet_client_met_historie(historie_rows) -> tuple[SheetClient, FakeWorksheet]:
    client = object.__new__(SheetClient)
    client._pand = Pand(
        slug="test", naam="Test", google_sheet_id="x", google_sheet_worksheet="y",
        history_worksheet="Historie", bunq_rekening_iban="NL00TEST0000000000",
    )
    historie_ws = FakeWorksheet(historie_rows)
    client._history_worksheet = lambda: historie_ws
    return client, historie_ws


def _sheet_client_met_vertrokken(vertrokken_rows) -> tuple[SheetClient, FakeWorksheet]:
    client = object.__new__(SheetClient)
    client._pand = Pand(
        slug="test", naam="Test", google_sheet_id="x", google_sheet_worksheet="y",
        history_worksheet="Historie", bunq_rekening_iban="NL00TEST0000000000",
    )
    vertrokken_ws = FakeWorksheet(vertrokken_rows)
    client._vertrokken_worksheet = lambda: vertrokken_ws
    return client, vertrokken_ws


HISTORIE_HEADER = ["Maand", "Kamer", "Huurder", "Verwacht bedrag", "Ontvangen bedrag", "Status", "Betaaldatum"]


def _result(kamer="1", naam="Jan", bedrag="650.00", ontvangen="650.00", status=Status.BETAALD, betaaldatum=None):
    tenant = Tenant(row_index=2, naam=naam, kamer=kamer, verwacht_bedrag=Decimal(bedrag))
    betalingen = [Payment(bedrag=Decimal(ontvangen), valuta="EUR", tegenpartij_naam=naam,
                           tegenpartij_iban=None, omschrijving="huur", datum=betaaldatum)] if betaaldatum else []
    return TenantResult(tenant=tenant, ontvangen_bedrag=Decimal(ontvangen), status=status, gematchte_betalingen=betalingen)


HEADER = ["Kamer", "Huurder", "Kale", "Service", "Totaal", "Einddatum", "Opmerking", "IBAN", "Zoekwoord",
          "Status", "Ontvangen", "Laatst", "Beschikbaar", "Omschrijving", "Map ID", "Mail", "Telefoonnummer"]


def test_get_kamers_leest_beschikbaar_en_omschrijving():
    rows = [
        HEADER,
        ["1", "Jan", "", "", "650,00", "", "", "", "", "", "", "", "JA", "Nice room", "map123", "jan@example.com", "0612345678"],
        ["2", "", "", "", "600,00", "", "", "", "", "", "", "", "NEE", "", "", "", ""],
    ]
    client, _ = _sheet_client(rows)
    kamers = client.get_kamers()
    assert kamers[0].beschikbaar is True
    assert kamers[0].advertentie_omschrijving == "Nice room"
    assert kamers[0].advertentie_map_id == "map123"
    assert kamers[0].email == "jan@example.com"
    assert kamers[0].telefoonnummer == "0612345678"
    assert kamers[1].beschikbaar is False
    assert kamers[1].advertentie_omschrijving is None
    assert kamers[1].email is None


def test_get_kamers_leest_contractvelden():
    rows = [
        HEADER,
        ["1", "Jan", "", "", "650,00", "", "", "", "", "", "", "", "", "", "", "", "",
         "27-11-2000", "Tatabánya, Hungary", "1124601", "Consultancy", "Tamás Neumayer", "Vader", "01-07-2026",
         "1000,00"],
    ]
    client, _ = _sheet_client(rows)
    kamer = client.get_kamers()[0]
    assert kamer.geboortedatum == "27-11-2000"
    assert kamer.geboorteplaats == "Tatabánya, Hungary"
    assert kamer.studentnummer == "1124601"
    assert kamer.studierichting == "Consultancy"
    assert kamer.borgsteller_naam == "Tamás Neumayer"
    assert kamer.borgsteller_relatie == "Vader"
    assert kamer.contract_startdatum == "01-07-2026"
    assert kamer.borg_bedrag == Decimal("1000.00")


def test_update_kamer_schrijft_contractvelden():
    rows = [HEADER, ["1", "Jan", "", "", "650,00"]]
    client, ws = _sheet_client(rows)
    client.update_kamer(
        row_index=2, naam="Jan", kamer="1", verwacht_bedrag=Decimal("650.00"), iban=None, zoekwoord=None,
        geboortedatum="27-11-2000", geboorteplaats="Tatabánya, Hungary", studentnummer="1124601",
        studierichting="Consultancy", borgsteller_naam="Tamás Neumayer", borgsteller_relatie="Vader",
        contract_startdatum="01-07-2026", borg_bedrag=Decimal("1000.00"),
    )
    ranges = {u["range"]: u["values"][0][0] for u in ws.batch_updates[0]}
    assert ranges["R2"] == "27-11-2000"
    assert ranges["S2"] == "Tatabánya, Hungary"
    assert ranges["T2"] == "1124601"
    assert ranges["U2"] == "Consultancy"
    assert ranges["V2"] == "Tamás Neumayer"
    assert ranges["W2"] == "Vader"
    assert ranges["X2"] == "01-07-2026"
    assert ranges["Y2"] == "1000,00"


def test_get_kamers_werkt_ook_met_korte_rijen_zonder_nieuwe_kolommen():
    rows = [HEADER, ["1", "Jan", "", "", "650,00"]]
    client, _ = _sheet_client(rows)
    kamers = client.get_kamers()
    assert kamers[0].beschikbaar is False
    assert kamers[0].advertentie_map_id is None


def test_update_aanbod_schrijft_alleen_aanbod_kolommen():
    rows = [HEADER, ["1", "Jan", "", "", "650,00"]]
    client, ws = _sheet_client(rows)
    client.update_aanbod(row_index=2, beschikbaar=True, omschrijving="Great room", map_id="map456")
    assert len(ws.batch_updates) == 1
    ranges = {u["range"]: u["values"][0][0] for u in ws.batch_updates[0]}
    assert ranges["M2"] == "JA"
    assert ranges["N2"] == "Great room"
    assert ranges["O2"] == "map456"
    # zonder opgegeven advertentievelden blijven die leeg, niet "None"
    assert ranges["Z2"] == ""
    assert ranges["AA2"] == ""


def test_update_aanbod_schrijft_advertentievelden():
    rows = [HEADER, ["1", "Jan", "", "", "650,00"]]
    client, ws = _sheet_client(rows)
    client.update_aanbod(
        row_index=2, beschikbaar=True, omschrijving="Great room", map_id="map456",
        prijs=Decimal("725.00"), oppervlakte="18 m²", beschikbaar_per="01-09-2026",
        beschikbaar_tot="01-07-2027", borg=Decimal("1000.00"),
    )
    ranges = {u["range"]: u["values"][0][0] for u in ws.batch_updates[0]}
    assert ranges["Z2"] == "725,00"
    assert ranges["AA2"] == "18 m²"
    assert ranges["AB2"] == "01-09-2026"
    assert ranges["AC2"] == "01-07-2027"
    assert ranges["AD2"] == "1000,00"


def test_update_aanbod_breidt_sheet_uit_als_grid_te_klein_is():
    # Regressietest voor een echt gemelde crash: een sheet die nog nooit tot
    # kolom AD is uitgebreid (het gebruikelijke standaard-grid van 26
    # kolommen, A t/m Z) gaf een "exceeds grid limits"-APIError van Google
    # zodra er naar kolom AA e.v. geschreven werd - de Sheets API breidt het
    # aantal kolommen namelijk niet vanzelf uit (in tegenstelling tot rijen).
    rows = [HEADER, ["1", "Jan", "", "", "650,00"]]
    client, ws = _sheet_client(rows)
    assert ws.col_count == 26  # het standaard-grid, zoals op de live sheet
    client.update_aanbod(row_index=2, beschikbaar=True, omschrijving="Great room", map_id="map456")
    assert ws.resize_aanroepen == [{"rows": None, "cols": 30}]
    assert ws.col_count == 30


def test_update_aanbod_breidt_niet_onnodig_uit_als_grid_al_groot_genoeg_is():
    rows = [HEADER, ["1", "Jan", "", "", "650,00"]]
    client, ws = _sheet_client(rows)
    ws.col_count = 40
    client.update_aanbod(row_index=2, beschikbaar=True, omschrijving="Great room", map_id="map456")
    assert ws.resize_aanroepen == []


def test_update_kamer_breidt_sheet_uit_als_grid_te_klein_is():
    rows = [HEADER, ["1", "Jan", "", "", "650,00"]]
    client, ws = _sheet_client(rows)
    ws.col_count = 20  # kleiner dan kolom Y (25, "Borg")
    client.update_kamer(row_index=2, naam="Jan", kamer="1", verwacht_bedrag=Decimal("650.00"), iban=None, zoekwoord=None)
    assert ws.resize_aanroepen == [{"rows": None, "cols": 25}]


def test_get_kamers_leest_advertentievelden():
    rows = [
        HEADER,
        ["1", "Jan", "", "", "650,00", "", "", "", "", "", "", "", "", "", "", "", "",
         "", "", "", "", "", "", "", "", "725,00", "18 m²", "01-09-2026", "01-07-2027", "1000,00"],
    ]
    client, _ = _sheet_client(rows)
    kamer = client.get_kamers()[0]
    assert kamer.advertentie_prijs == Decimal("725.00")
    assert kamer.advertentie_oppervlakte == "18 m²"
    assert kamer.advertentie_beschikbaar_per == "01-09-2026"
    assert kamer.advertentie_beschikbaar_tot == "01-07-2027"
    assert kamer.advertentie_borg == Decimal("1000.00")


def test_get_kamers_zonder_advertentievelden_geeft_none():
    rows = [HEADER, ["1", "Jan", "", "", "650,00"]]
    client, _ = _sheet_client(rows)
    kamer = client.get_kamers()[0]
    assert kamer.advertentie_prijs is None
    assert kamer.advertentie_oppervlakte is None
    assert kamer.advertentie_beschikbaar_per is None
    assert kamer.advertentie_beschikbaar_tot is None
    assert kamer.advertentie_borg is None


def test_update_kamer_schrijft_contactgegevens():
    rows = [HEADER, ["1", "Jan", "", "", "650,00"]]
    client, ws = _sheet_client(rows)
    client.update_kamer(
        row_index=2, naam="Jan", kamer="1", verwacht_bedrag=Decimal("650.00"), iban=None, zoekwoord=None,
        email="jan@example.com", telefoonnummer="0612345678",
    )
    ranges = {u["range"]: u["values"][0][0] for updates in ws.batch_updates for u in updates}
    assert ranges["P2"] == "jan@example.com"
    assert ranges["Q2"] == "0612345678"


def test_update_kamer_schrijft_telefoonnummer_met_raw_zodat_voorloopnul_blijft_staan():
    # Regressietest: bij USER_ENTERED interpreteert Google Sheets "0612345678"
    # als getal (voorloop-nul valt weg) of "+31612345678" soms als het begin
    # van een formule - RAW slaat het altijd letterlijk op.
    rows = [HEADER, ["1", "Jan", "", "", "650,00"]]
    client, ws = _sheet_client(rows)
    client.update_kamer(
        row_index=2, naam="Jan", kamer="1", verwacht_bedrag=Decimal("650.00"), iban=None, zoekwoord=None,
        telefoonnummer="0612345678",
    )
    telefoon_update = next(u for updates in ws.batch_updates for u in updates if u["range"] == "Q2")
    assert telefoon_update["values"][0][0] == "0612345678"
    assert ws.laatste_value_input_option == "RAW"  # laatste aanroep was de losse telefoonnummer-update


def test_upsert_history_voegt_nieuwe_maand_toe():
    client, ws = _sheet_client_met_historie([HISTORIE_HEADER])
    resultaat = _result(betaaldatum=date(2026, 7, 3))
    client.upsert_history([resultaat], maand="2026-07")

    assert len(ws.appended_rows) == 1
    rij = ws.appended_rows[0]
    assert rij[0] == "2026-07"
    assert rij[1] == "1"
    assert rij[5] == "Betaald"
    assert rij[6] == "03-07-2026"


def test_upsert_history_werkt_zelfde_maand_bij_in_plaats_van_nieuwe_regel():
    bestaand = [
        HISTORIE_HEADER,
        ["2026-07", "1", "Jan", "650,00", "0,00", "Nog niet ontvangen", ""],
    ]
    client, ws = _sheet_client_met_historie(bestaand)

    resultaat = _result(betaaldatum=date(2026, 7, 5))
    client.upsert_history([resultaat], maand="2026-07")

    # Geen nieuwe rij - de bestaande regel voor kamer 1 / juli is bijgewerkt.
    assert ws.appended_rows == []
    assert len(ws.batch_updates) == 1
    bijgewerkte_rij = ws.batch_updates[0][0]["values"][0]
    assert bijgewerkte_rij[5] == "Betaald"
    assert bijgewerkte_rij[6] == "05-07-2026"


def test_upsert_history_maakt_nieuwe_regel_voor_nieuwe_maand_zelfde_kamer():
    bestaand = [
        HISTORIE_HEADER,
        ["2026-06", "1", "Jan", "650,00", "650,00", "Betaald", "01-06-2026"],
    ]
    client, ws = _sheet_client_met_historie(bestaand)

    resultaat = _result(betaaldatum=date(2026, 7, 2))
    client.upsert_history([resultaat], maand="2026-07")

    assert len(ws.appended_rows) == 1
    assert ws.appended_rows[0][0] == "2026-07"
    # De juni-regel blijft ongemoeid staan.
    assert ws.get_all_values()[1][0] == "2026-06"


def test_upsert_history_herkent_bestaande_rij_ondanks_google_sheets_datumconversie():
    # Regressietest voor een echt gemelde situatie: Google Sheets herkende een
    # eerder geschreven "2026-06" zelf als datum en sloeg 'm op/toonde 'm als
    # "01-06-2026" - zonder normalisatie vond upsert_history de bestaande rij
    # dan niet meer terug en bleef een nieuwe regel toevoegen i.p.v. bijwerken.
    bestaand = [
        HISTORIE_HEADER,
        ["01-06-2026", "1", "Jan", "650,00", "0,00", "Nog niet ontvangen", ""],
    ]
    client, ws = _sheet_client_met_historie(bestaand)

    resultaat = _result(betaaldatum=date(2026, 6, 15))
    client.upsert_history([resultaat], maand="2026-06")

    assert ws.appended_rows == []  # geen dubbele rij - de bestaande regel is bijgewerkt
    assert len(ws.batch_updates) == 1
    bijgewerkte_rij = ws.batch_updates[0][0]["values"][0]
    assert bijgewerkte_rij[5] == "Betaald"


def test_upsert_history_verandert_naam_van_bestaande_regel_niet():
    # Regressietest voor een echt gemelde situatie: een nieuwe huurder
    # (Thomas) alvast invullen voor een kamer waarvan de huidige huurder
    # (Matias) pas volgende maand vertrekt, overschreef bij de eerstvolgende
    # automatische controle de lopende-maand-regel van Matias met Thomas'
    # naam - terwijl de betaling zelf (bedrag/status) prima bleef matchen.
    # De naam van een al bestaande regel moet dus bevroren blijven.
    bestaand = [
        HISTORIE_HEADER,
        ["2026-07", "1", "Matias", "870,00", "0,00", "Nog niet ontvangen", ""],
    ]
    client, ws = _sheet_client_met_historie(bestaand)

    resultaat = _result(naam="Thomas", bedrag="870.00", ontvangen="870.00", betaaldatum=date(2026, 7, 16))
    client.upsert_history([resultaat], maand="2026-07")

    assert ws.appended_rows == []
    bijgewerkte_rij = ws.batch_updates[0][0]["values"][0]
    assert bijgewerkte_rij[2] == "Matias"  # naam blijft ongewijzigd
    assert bijgewerkte_rij[5] == "Betaald"  # status/bedrag worden wel bijgewerkt
    assert bijgewerkte_rij[6] == "16-07-2026"


def test_upsert_history_gebruikt_actuele_naam_voor_gloednieuwe_regel():
    # Bij een compleet nieuwe (kamer, maand)-regel is er geen eerdere naam om
    # te bevriezen - dan moet gewoon de huidige huurder gebruikt worden (bv.
    # augustus, zodra Thomas' contract daadwerkelijk ingaat).
    client, ws = _sheet_client_met_historie([HISTORIE_HEADER])
    resultaat = _result(naam="Thomas", bedrag="870.00", ontvangen="870.00", betaaldatum=date(2026, 8, 1))
    client.upsert_history([resultaat], maand="2026-08")

    assert len(ws.appended_rows) == 1
    assert ws.appended_rows[0][2] == "Thomas"


def test_upsert_history_schrijft_met_raw_input_option():
    # value_input_option=RAW voorkomt dat Google Sheets "2026-07" zelf als
    # datum gaat interpreteren en omzetten naar "01-07-2026".
    client, ws = _sheet_client_met_historie([HISTORIE_HEADER])
    resultaat = _result(betaaldatum=date(2026, 7, 3))
    client.upsert_history([resultaat], maand="2026-07")
    assert ws.laatste_value_input_option == "RAW"


def test_dedupliceer_geschiedenis_herstelt_door_sheets_omgezette_maandwaarden():
    # Zelfde datumconversie-scenario als hierboven, maar dan in combinatie
    # met een echte duplicaat - dedupliceer_geschiedenis moet beide rijen als
    # dezelfde (kamer, maand) herkennen én de overblijvende rij genezen.
    rows = [
        HISTORIE_HEADER,
        ["01-06-2026", "1", "Jan", "650,00", "0,00", "Nog niet ontvangen", ""],
        ["2026-06", "1", "Jan", "650,00", "650,00", "Betaald", "15-06-2026"],
    ]
    client, ws = _sheet_client_met_historie(rows)

    verwijderd = client.dedupliceer_geschiedenis()

    assert verwijderd == 1
    overgebleven = ws.get_all_values()
    assert len(overgebleven) == 2  # koprij + 1
    assert overgebleven[1][0] == "2026-06"  # genezen naar het canonieke formaat
    assert overgebleven[1][5] == "Betaald"  # de onderste (meest recente) regel is bewaard


def test_dedupliceer_geschiedenis_geneest_ook_zonder_duplicaten():
    rows = [
        HISTORIE_HEADER,
        ["01-06-2026", "1", "Jan", "650,00", "650,00", "Betaald", "15-06-2026"],
    ]
    client, ws = _sheet_client_met_historie(rows)

    client.dedupliceer_geschiedenis()

    assert ws.get_all_values()[1][0] == "2026-06"


def test_get_geschiedenis_herkent_door_sheets_omgezette_maandwaarde():
    rows = [
        HISTORIE_HEADER,
        ["01-06-2026", "1", "Stefania", "1471,83", "1447,00", "Betaald", "15-06-2026"],
    ]
    client, _ = _sheet_client_met_historie(rows)

    geschiedenis = client.get_geschiedenis("1")

    assert len(geschiedenis) == 1
    assert geschiedenis[0].maand == "2026-06"
    assert geschiedenis[0].ontvangen_bedrag == Decimal("1447.00")


def test_get_geschiedenis_negeert_oud_datumformaat():
    rows = [
        HISTORIE_HEADER,
        ["03-07-2026", "1", "Jan", "650,00", "650,00", "Betaald", ""],  # oude indeling (voor de wijziging)
        ["2026-07", "1", "Jan", "650,00", "650,00", "Betaald", "03-07-2026"],
    ]
    client, _ = _sheet_client_met_historie(rows)
    geschiedenis = client.get_geschiedenis("1")

    assert len(geschiedenis) == 1
    assert geschiedenis[0].maand == "2026-07"
    assert geschiedenis[0].betaaldatum == date(2026, 7, 3)


def test_upsert_history_meerdere_bestaande_maanden_update_juiste_rij():
    # Regressietest: bij meerdere bestaande maanden voor dezelfde kamer moest
    # upsert_history de rij bijwerken die echt bij de opgegeven maand hoort -
    # eerder werd (door alleen op kamer te sleutelen) soms de verkeerde/
    # laatst geziene rij vergeleken, waardoor er per ongeluk een dubbele rij
    # bijkwam in plaats van de bestaande bijgewerkt te worden.
    bestaand = [
        HISTORIE_HEADER,
        ["2026-04", "1", "Jan", "650,00", "650,00", "Betaald", "03-04-2026"],
        ["2026-05", "1", "Jan", "650,00", "0,00", "Nog niet ontvangen", ""],
        ["2026-06", "1", "Jan", "650,00", "1300,00", "Te veel ontvangen", "10-06-2026"],
    ]
    client, ws = _sheet_client_met_historie(bestaand)

    resultaat = _result(betaaldatum=date(2026, 4, 8))
    client.upsert_history([resultaat], maand="2026-04")

    assert ws.appended_rows == []  # geen dubbele rij - de bestaande aprilrij is bijgewerkt
    assert len(ws.batch_updates) == 1
    bijgewerkte_rij = ws.batch_updates[0][0]["values"][0]
    assert bijgewerkte_rij[0] == "2026-04"
    assert bijgewerkte_rij[6] == "08-04-2026"
    # mei- en junirij blijven ongemoeid staan
    assert ws.get_all_values()[2][0] == "2026-05"
    assert ws.get_all_values()[3][0] == "2026-06"


def test_dedupliceer_geschiedenis_houdt_laatste_regel_en_verwijdert_rest():
    rows = [
        HISTORIE_HEADER,
        ["2026-05", "1", "Jan", "650,00", "0,00", "Nog niet ontvangen", ""],  # dubbel, oud
        ["2026-06", "1", "Jan", "650,00", "1300,00", "Te veel ontvangen", "10-06-2026"],  # dubbel, oud
        ["2026-05", "1", "Jan", "650,00", "650,00", "Betaald", "10-06-2026"],  # dubbel, nieuw (correct)
        ["2026-06", "1", "Jan", "650,00", "650,00", "Betaald", "10-06-2026"],  # dubbel, nieuw (correct)
        ["2026-05", "2", "Piet", "700,00", "700,00", "Betaald", "02-05-2026"],  # geen duplicaat
    ]
    client, ws = _sheet_client_met_historie(rows)

    verwijderd = client.dedupliceer_geschiedenis()

    assert verwijderd == 2
    overgebleven = ws.get_all_values()
    assert len(overgebleven) == 4  # koprij + 3 unieke (kamer, maand)-combinaties
    kamer1_mei = next(r for r in overgebleven[1:] if r[1] == "1" and r[0] == "2026-05")
    assert kamer1_mei[5] == "Betaald"  # de nieuwe/onderste variant is bewaard, niet de oude


def test_dedupliceer_geschiedenis_zonder_duplicaten_doet_niets():
    rows = [
        HISTORIE_HEADER,
        ["2026-05", "1", "Jan", "650,00", "650,00", "Betaald", "02-05-2026"],
        ["2026-06", "1", "Jan", "650,00", "650,00", "Betaald", "03-06-2026"],
    ]
    client, ws = _sheet_client_met_historie(rows)

    verwijderd = client.dedupliceer_geschiedenis()

    assert verwijderd == 0
    assert ws.get_all_values() == rows


def test_verwijder_geschiedenis_voor_instapdatum_ruimt_alleen_oude_regels_van_deze_huurder_op():
    rows = [
        HISTORIE_HEADER,
        ["2026-03", "1", "Bence", "650,00", "0,00", "Niet ontvangen", ""],  # vóór de instapdatum - moet weg
        ["2026-04", "1", "Bence", "650,00", "0,00", "Niet ontvangen", ""],  # vóór de instapdatum - moet weg
        ["2026-07", "1", "Bence", "650,00", "650,00", "Betaald", "01-07-2026"],  # instapmaand zelf - blijft staan
        ["2026-04", "1", "Oud-Huurder", "600,00", "600,00", "Betaald", "02-04-2026"],  # vorige huurder, zelfde kamer - blijft staan
        ["2026-04", "2", "Piet", "700,00", "700,00", "Betaald", "02-04-2026"],  # andere kamer - blijft staan
    ]
    client, ws = _sheet_client_met_historie(rows)

    verwijderd = client.verwijder_geschiedenis_voor_instapdatum(kamer="1", huurder="Bence", oudste_geldige_maand="2026-07")

    assert verwijderd == 2
    overgebleven = ws.get_all_values()
    assert len(overgebleven) == 4  # koprij + 3 regels
    maanden_bence = [r[0] for r in overgebleven[1:] if r[2] == "Bence"]
    assert maanden_bence == ["2026-07"]
    assert any(r[2] == "Oud-Huurder" for r in overgebleven[1:])
    assert any(r[1] == "2" for r in overgebleven[1:])


def test_verwijder_geschiedenis_voor_instapdatum_zonder_oude_regels_doet_niets():
    rows = [
        HISTORIE_HEADER,
        ["2026-07", "1", "Bence", "650,00", "650,00", "Betaald", "01-07-2026"],
    ]
    client, ws = _sheet_client_met_historie(rows)

    verwijderd = client.verwijder_geschiedenis_voor_instapdatum(kamer="1", huurder="Bence", oudste_geldige_maand="2026-07")

    assert verwijderd == 0
    assert ws.get_all_values() == rows


# --- Vertrokken huurders (archief, blijft nog even zichtbaar op Huurders-pagina) ---

VERTROKKEN_HEADER = ["Kamer", "Naam", "Mail", "Telefoonnummer", "Contract einddatum", "Vertrokken op"]


def test_archiveer_vertrokken_huurder_voegt_rij_toe():
    client, ws = _sheet_client_met_vertrokken([VERTROKKEN_HEADER])
    kamer = Tenant(
        row_index=2, naam="Bence Neumayer", kamer="1", verwacht_bedrag=Decimal("919.00"),
        email="bence@example.com", telefoonnummer="0612345678", contract_einddatum="01-07-2026",
    )

    client.archiveer_vertrokken_huurder(kamer)

    assert len(ws.appended_rows) == 1
    rij = ws.appended_rows[0]
    assert rij[0] == "1"
    assert rij[1] == "Bence Neumayer"
    assert rij[2] == "bence@example.com"
    assert rij[3] == "0612345678"
    assert rij[4] == "01-07-2026"
    assert rij[5] == date.today().strftime("%d-%m-%Y")


def test_archiveer_vertrokken_huurder_zonder_naam_doet_niets():
    client, ws = _sheet_client_met_vertrokken([VERTROKKEN_HEADER])
    lege_kamer = Tenant(row_index=3, naam="", kamer="2", verwacht_bedrag=Decimal("650.00"))

    client.archiveer_vertrokken_huurder(lege_kamer)

    assert ws.appended_rows == []


def test_get_recent_vertrokken_huurders_binnen_termijn_wordt_getoond():
    einddatum = (date.today() - timedelta(days=10)).strftime("%d-%m-%Y")
    vertrokken_op = date.today().strftime("%d-%m-%Y")
    rows = [
        VERTROKKEN_HEADER,
        ["1", "Bence Neumayer", "bence@example.com", "0612345678", einddatum, vertrokken_op],
    ]
    client, _ = _sheet_client_met_vertrokken(rows)

    resultaat = client.get_recent_vertrokken_huurders()

    assert len(resultaat) == 1
    assert resultaat[0].naam == "Bence Neumayer"
    assert resultaat[0].kamer == "1"
    assert resultaat[0].email == "bence@example.com"
    assert resultaat[0].contract_einddatum == einddatum


def test_get_recent_vertrokken_huurders_buiten_termijn_verdwijnt_vanzelf():
    # meer dan 31 dagen ná de contract-einddatum - moet niet meer getoond worden
    einddatum = (date.today() - timedelta(days=40)).strftime("%d-%m-%Y")
    vertrokken_op = (date.today() - timedelta(days=40)).strftime("%d-%m-%Y")
    rows = [
        VERTROKKEN_HEADER,
        ["1", "Bence Neumayer", "bence@example.com", "0612345678", einddatum, vertrokken_op],
    ]
    client, _ = _sheet_client_met_vertrokken(rows)

    assert client.get_recent_vertrokken_huurders() == []


def test_get_recent_vertrokken_huurders_met_langere_termijn_toont_meer():
    # 40 dagen na de contract-einddatum: buiten de standaardtermijn (31 dagen,
    # voor het grijze blokje op Huurders), maar wel binnen een langere,
    # expliciet opgegeven termijn (zie "Mail het hele huishouden" - webapp/
    # app.py: huishouden_mailen()).
    einddatum = (date.today() - timedelta(days=40)).strftime("%d-%m-%Y")
    vertrokken_op = (date.today() - timedelta(days=40)).strftime("%d-%m-%Y")
    rows = [
        VERTROKKEN_HEADER,
        ["1", "Bence Neumayer", "bence@example.com", "0612345678", einddatum, vertrokken_op],
    ]
    client, _ = _sheet_client_met_vertrokken(rows)

    assert client.get_recent_vertrokken_huurders() == []  # standaardtermijn
    resultaat = client.get_recent_vertrokken_huurders(dagen=61)
    assert len(resultaat) == 1
    assert resultaat[0].naam == "Bence Neumayer"


def test_get_recent_vertrokken_huurders_zonder_einddatum_gebruikt_vertrokken_op():
    vertrokken_op = (date.today() - timedelta(days=5)).strftime("%d-%m-%Y")
    rows = [
        VERTROKKEN_HEADER,
        ["1", "Dzonatans", "", "", "", vertrokken_op],  # geen bekende contract-einddatum
    ]
    client, _ = _sheet_client_met_vertrokken(rows)

    resultaat = client.get_recent_vertrokken_huurders()

    assert len(resultaat) == 1
    assert resultaat[0].contract_einddatum is None


def test_get_recent_vertrokken_huurders_onherkenbare_rij_wordt_overgeslagen():
    rows = [
        VERTROKKEN_HEADER,
        ["1", "Bence Neumayer", "", "", "", "geen-datum"],  # onherkenbare 'vertrokken op'
    ]
    client, _ = _sheet_client_met_vertrokken(rows)

    assert client.get_recent_vertrokken_huurders() == []


def test_get_recent_vertrokken_huurders_sorteert_meest_recent_eerst():
    oud = (date.today() - timedelta(days=20)).strftime("%d-%m-%Y")
    nieuw = (date.today() - timedelta(days=1)).strftime("%d-%m-%Y")
    rows = [
        VERTROKKEN_HEADER,
        ["1", "Oudste", "", "", "", oud],
        ["2", "Nieuwste", "", "", "", nieuw],
    ]
    client, _ = _sheet_client_met_vertrokken(rows)

    resultaat = client.get_recent_vertrokken_huurders()

    assert [v.naam for v in resultaat] == ["Nieuwste", "Oudste"]


def test_get_alle_vertrokken_huurders_toont_ook_regels_buiten_de_termijn():
    # in tegenstelling tot get_recent_vertrokken_huurders() blijft dit de
    # volledige, permanente lijst - zie de "Oude huurders"-pagina.
    lang_geleden = (date.today() - timedelta(days=400)).strftime("%d-%m-%Y")
    rows = [
        VERTROKKEN_HEADER,
        ["1", "Allang Vertrokken", "oud@example.com", "", "", lang_geleden],
    ]
    client, _ = _sheet_client_met_vertrokken(rows)

    assert client.get_recent_vertrokken_huurders() == []
    resultaat = client.get_alle_vertrokken_huurders()
    assert len(resultaat) == 1
    assert resultaat[0].naam == "Allang Vertrokken"


def test_get_alle_vertrokken_huurders_kent_een_row_index_toe():
    vertrokken_op = date.today().strftime("%d-%m-%Y")
    rows = [
        VERTROKKEN_HEADER,
        ["1", "Eerste", "", "", "", vertrokken_op],
        ["2", "Tweede", "", "", "", vertrokken_op],
    ]
    client, _ = _sheet_client_met_vertrokken(rows)

    resultaat = {v.naam: v.row_index for v in client.get_alle_vertrokken_huurders()}
    assert resultaat == {"Eerste": 2, "Tweede": 3}


def test_get_vertrokken_huurder_vindt_op_row_index():
    vertrokken_op = date.today().strftime("%d-%m-%Y")
    rows = [
        VERTROKKEN_HEADER,
        ["1", "Eerste", "", "", "", vertrokken_op],
        ["2", "Tweede", "", "", "", vertrokken_op],
    ]
    client, _ = _sheet_client_met_vertrokken(rows)

    gevonden = client.get_vertrokken_huurder(3)
    assert gevonden is not None
    assert gevonden.naam == "Tweede"


def test_get_vertrokken_huurder_onbekende_row_index_geeft_none():
    client, _ = _sheet_client_met_vertrokken([VERTROKKEN_HEADER])
    assert client.get_vertrokken_huurder(99) is None


# --- Aanmeldingen (incl. borgsteller-velden) ---

class FakeSpreadsheet:
    def __init__(self, worksheet):
        self._worksheet = worksheet

    def worksheet(self, title):
        return self._worksheet


def _sheet_client_met_aanmeldingen(rows) -> tuple[SheetClient, FakeWorksheet]:
    client = object.__new__(SheetClient)
    client._pand = Pand(
        slug="test", naam="Test", google_sheet_id="x", google_sheet_worksheet="y",
        history_worksheet="Historie", bunq_rekening_iban="NL00TEST0000000000",
    )
    ws = FakeWorksheet(rows)
    client._spreadsheet = FakeSpreadsheet(ws)
    return client, ws


def _aanmelding(**overrides) -> Aanmelding:
    basis = dict(
        naam="Jane Doe", email="jane@example.com", telefoon="+31612345678",
        huidig_adres="Somestreet 1", studie="Computer Science", studentnummer="123456",
        gewenste_ingangsdatum="2026-09-01", gewenste_huurduur="12 months",
        inkomstenbron="Parents", inkomsten_bedrag="1200", borgsteller="Yes",
        bezichtiging="In person", videobel_nummer="", bewijs_inschrijving_link="/link",
        borgsteller_naam="John Doe", borgsteller_relatie="Father", borgsteller_email="john@example.com",
    )
    basis.update(overrides)
    return Aanmelding(**basis)


def test_add_aanmelding_schrijft_borgstellervelden_weg():
    client, ws = _sheet_client_met_aanmeldingen([_AANMELDINGEN_HEADER])
    client.add_aanmelding("1", _aanmelding())

    rij = ws.appended_rows[0]
    assert rij[-3:] == ["John Doe", "Father", "john@example.com"]


def test_add_aanmelding_schrijft_met_raw_zodat_telefoonnummer_niet_gemangeld_wordt():
    # Regressietest: bij USER_ENTERED interpreteert Google Sheets
    # "+31612345678" soms als het begin van een formule (leidt tot een
    # foutmelding in de cel) en "0612345678" als getal (voorloop-nul valt
    # weg). RAW slaat het telefoonnummer altijd letterlijk op.
    client, ws = _sheet_client_met_aanmeldingen([_AANMELDINGEN_HEADER])
    client.add_aanmelding("1", _aanmelding(telefoon="+31612345678"))

    assert ws.appended_rows[0][4] == "+31612345678"
    assert ws.laatste_value_input_option == "RAW"


def test_get_aanmeldingen_geeft_borgstellervelden_terug():
    client, _ = _sheet_client_met_aanmeldingen([_AANMELDINGEN_HEADER])
    client.add_aanmelding("1", _aanmelding())

    rijen = client.get_aanmeldingen()

    assert len(rijen) == 1
    assert rijen[0][16:19] == ["John Doe", "Father", "john@example.com"]


def test_get_aanmeldingen_padt_oudere_rijen_zonder_borgstellerkolommen():
    # Rij van vóór de borgsteller-uitbreiding (16 kolommen i.p.v. 19)
    oude_rij = ["10-07-2026", "1", "Piet", "piet@example.com"] + [""] * 12
    client, _ = _sheet_client_met_aanmeldingen([_AANMELDINGEN_HEADER, oude_rij])

    rijen = client.get_aanmeldingen()

    assert len(rijen) == 1
    assert len(rijen[0]) == len(_AANMELDINGEN_HEADER)
    assert rijen[0][16:19] == ["", "", ""]


# --- Bezichtigingen ---

def _sheet_client_met_bezichtigingen(rows) -> tuple[SheetClient, FakeWorksheet]:
    client = object.__new__(SheetClient)
    client._pand = Pand(
        slug="test", naam="Test", google_sheet_id="x", google_sheet_worksheet="y",
        history_worksheet="Historie", bunq_rekening_iban="NL00TEST0000000000",
    )
    ws = FakeWorksheet(rows)
    client._spreadsheet = FakeSpreadsheet(ws)
    return client, ws


def _afspraak(**overrides) -> dict:
    basis = dict(
        tijd_start="14:00", tijd_eind="14:15", kamer="1", naam="Jane Doe",
        email="jane@example.com", telefoon="+31612345678", bezichtiging="In person", bel_nummer="+31612345678",
    )
    basis.update(overrides)
    return basis


def test_add_bezichtiging_schrijft_alle_velden_weg():
    client, ws = _sheet_client_met_bezichtigingen([_BEZICHTIGINGEN_HEADER])
    client.add_bezichtiging("2026-08-01", _afspraak())

    rij = ws.appended_rows[0]
    assert rij[:9] == [
        "2026-08-01", "14:00", "14:15", "1", "Jane Doe", "jane@example.com",
        "+31612345678", "In person", "+31612345678",
    ]
    assert ws.laatste_value_input_option == "RAW"  # anders vallen voorloop-nullen weg


def test_get_bezichtigingen_geeft_toegevoegde_afspraken_terug():
    client, _ = _sheet_client_met_bezichtigingen([_BEZICHTIGINGEN_HEADER])
    client.add_bezichtiging("2026-08-01", _afspraak())
    client.add_bezichtiging("2026-08-01", _afspraak(naam="John Smith", tijd_start="14:15", tijd_eind="14:30"))

    rijen = client.get_bezichtigingen()

    assert len(rijen) == 2
    assert [r[4] for r in rijen] == ["Jane Doe", "John Smith"]


# --- Bezichtigingen: rijnummer + verwijderen ---

def test_get_bezichtigingen_met_rijnummer():
    client, _ = _sheet_client_met_bezichtigingen([_BEZICHTIGINGEN_HEADER])
    client.add_bezichtiging("2026-08-01", _afspraak())
    client.add_bezichtiging("2026-08-01", _afspraak(naam="John Smith"))

    resultaat = client.get_bezichtigingen_met_rijnummer()

    assert [rijnummer for rijnummer, _ in resultaat] == [2, 3]
    assert resultaat[0][1][4] == "Jane Doe"
    assert resultaat[1][1][4] == "John Smith"


def test_verwijder_bezichtiging():
    client, ws = _sheet_client_met_bezichtigingen([_BEZICHTIGINGEN_HEADER])
    client.add_bezichtiging("2026-08-01", _afspraak())
    client.add_bezichtiging("2026-08-01", _afspraak(naam="John Smith"))

    client.verwijder_bezichtiging(2)  # verwijdert Jane Doe (rij 2)

    resultaat = client.get_bezichtigingen_met_rijnummer()
    assert len(resultaat) == 1
    assert resultaat[0][1][4] == "John Smith"
