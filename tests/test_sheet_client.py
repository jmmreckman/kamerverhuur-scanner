"""Tests voor de kolomparsing/-opslag van SheetClient, zonder een echte Google
Sheets-verbinding: we bouwen een SheetClient met een neppe worksheet."""
from decimal import Decimal

from kamerverhuur_scanner.models import Pand
from kamerverhuur_scanner.sheet_client import SheetClient


class FakeWorksheet:
    def __init__(self, rows):
        self._rows = rows
        self.batch_updates = []

    def get_all_values(self):
        return self._rows

    def batch_update(self, updates, value_input_option="USER_ENTERED"):
        self.batch_updates.append(updates)


def _sheet_client(rows) -> tuple[SheetClient, FakeWorksheet]:
    client = object.__new__(SheetClient)
    client._pand = Pand(
        slug="test", naam="Test", google_sheet_id="x", google_sheet_worksheet="y",
        history_worksheet="Historie", google_drive_folder_id=None, bunq_rekening_iban="NL00TEST0000000000",
    )
    ws = FakeWorksheet(rows)
    client._worksheet = ws
    return client, ws


HEADER = ["Kamer", "Huurder", "Kale", "Service", "Totaal", "Einddatum", "Opmerking", "IBAN", "Zoekwoord",
          "Status", "Ontvangen", "Laatst", "Beschikbaar", "Omschrijving", "Map ID"]


def test_get_kamers_leest_beschikbaar_en_omschrijving():
    rows = [
        HEADER,
        ["1", "Jan", "", "", "650,00", "", "", "", "", "", "", "", "JA", "Nice room", "map123"],
        ["2", "", "", "", "600,00", "", "", "", "", "", "", "", "NEE", "", ""],
    ]
    client, _ = _sheet_client(rows)
    kamers = client.get_kamers()
    assert kamers[0].beschikbaar is True
    assert kamers[0].advertentie_omschrijving == "Nice room"
    assert kamers[0].advertentie_map_id == "map123"
    assert kamers[1].beschikbaar is False
    assert kamers[1].advertentie_omschrijving is None


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
    assert len(appended[0]) == 15  # kolom A t/m O
    assert appended[0][12:] == ["", "", ""]  # Beschikbaar/Omschrijving/Map ID nog leeg
