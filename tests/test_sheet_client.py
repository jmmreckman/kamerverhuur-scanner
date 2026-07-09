"""Tests voor de kolomparsing/-opslag van SheetClient, zonder een echte Google
Sheets-verbinding: we bouwen een SheetClient met een neppe worksheet."""
from datetime import date
from decimal import Decimal

from kamerverhuur_scanner.models import Pand, Payment, Status, Tenant, TenantResult
from kamerverhuur_scanner.sheet_client import SheetClient


class FakeWorksheet:
    def __init__(self, rows):
        self._rows = rows
        self.batch_updates = []
        self.appended_rows = []
        self.laatste_value_input_option = None

    def get_all_values(self):
        return self._rows

    def batch_update(self, updates, value_input_option="USER_ENTERED"):
        self.laatste_value_input_option = value_input_option
        self.batch_updates.append(updates)
        for u in updates:
            # simuleer het effect op _rows, zodat opeenvolgende aanroepen
            # (bv. get_all_values erna) de update ook echt terugzien
            kolom_start, rij = u["range"][0], int(u["range"].split(":")[0][1:])
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

    def clear(self):
        self._rows = []


def _sheet_client(rows) -> tuple[SheetClient, FakeWorksheet]:
    client = object.__new__(SheetClient)
    client._pand = Pand(
        slug="test", naam="Test", google_sheet_id="x", google_sheet_worksheet="y",
        history_worksheet="Historie", google_drive_folder_id=None, bunq_rekening_iban="NL00TEST0000000000",
    )
    ws = FakeWorksheet(rows)
    client._worksheet = ws
    return client, ws


def _sheet_client_met_historie(historie_rows) -> tuple[SheetClient, FakeWorksheet]:
    client = object.__new__(SheetClient)
    client._pand = Pand(
        slug="test", naam="Test", google_sheet_id="x", google_sheet_worksheet="y",
        history_worksheet="Historie", google_drive_folder_id=None, bunq_rekening_iban="NL00TEST0000000000",
    )
    historie_ws = FakeWorksheet(historie_rows)
    client._history_worksheet = lambda: historie_ws
    return client, historie_ws


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


def test_add_kamer_voegt_lege_aanbod_kolommen_toe():
    rows = [HEADER]
    client, ws = _sheet_client(rows)
    appended = []
    ws.append_row = lambda row, value_input_option="USER_ENTERED": appended.append(row)
    client.add_kamer(naam="Piet", kamer="3", verwacht_bedrag=Decimal("700.00"), iban=None, zoekwoord=None)
    assert len(appended[0]) == 25  # kolom A t/m Y
    assert appended[0][12:15] == ["", "", ""]  # Beschikbaar/Omschrijving/Map ID nog leeg
    assert appended[0][15:17] == ["", ""]  # Mail/Telefoonnummer nog leeg
    assert appended[0][17:] == ["", "", "", "", "", "", "", ""]  # contractvelden + borg nog leeg


def test_add_kamer_met_contactgegevens():
    rows = [HEADER]
    client, ws = _sheet_client(rows)
    appended = []
    ws.append_row = lambda row, value_input_option="USER_ENTERED": appended.append(row)
    client.add_kamer(
        naam="Piet", kamer="3", verwacht_bedrag=Decimal("700.00"), iban=None, zoekwoord=None,
        email="piet@example.com", telefoonnummer="0698765432",
    )
    assert appended[0][15:17] == ["piet@example.com", "0698765432"]


def test_update_kamer_schrijft_contactgegevens():
    rows = [HEADER, ["1", "Jan", "", "", "650,00"]]
    client, ws = _sheet_client(rows)
    client.update_kamer(
        row_index=2, naam="Jan", kamer="1", verwacht_bedrag=Decimal("650.00"), iban=None, zoekwoord=None,
        email="jan@example.com", telefoonnummer="0612345678",
    )
    ranges = {u["range"]: u["values"][0][0] for u in ws.batch_updates[0]}
    assert ranges["P2"] == "jan@example.com"
    assert ranges["Q2"] == "0612345678"


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
