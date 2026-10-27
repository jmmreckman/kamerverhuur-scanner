"""Tests voor het automatisch opbouwen van de tabbladen + koprijen in een nieuwe
pand-sheet (bouw_sheet_structuur) en het uitlezen van een Sheet-ID uit een geplakte
link. Geen echte Google-verbinding: we gebruiken een neppe spreadsheet."""
import re

from kamerverhuur_scanner.models import Pand
from kamerverhuur_scanner.sheet_client import (
    _AANMELDINGEN_HEADER,
    _BEZICHTIGINGEN_HEADER,
    _HISTORIE_HEADER,
    _VERTROKKEN_HEADER,
    COL_ADVERTENTIE_BORG,
    HUURDERS_HEADER,
    bouw_sheet_structuur,
    sheet_id_uit_invoer,
)


class FakeWorksheet:
    def __init__(self, title, rows=None, col_count=26):
        self.title = title
        self._rows = rows or []
        self.col_count = col_count

    def get_all_values(self):
        return self._rows

    def update_title(self, title):
        self.title = title

    def resize(self, rows=None, cols=None):
        if cols is not None:
            self.col_count = cols

    def batch_update(self, updates, value_input_option="USER_ENTERED"):
        for u in updates:
            rij = int(re.search(r"\d+", u["range"].split(":")[0]).group())
            while len(self._rows) < rij:
                self._rows.append([])
            self._rows[rij - 1] = u["values"][0]


class FakeSpreadsheet:
    def __init__(self, worksheets):
        self._ws = list(worksheets)

    def worksheets(self):
        return list(self._ws)

    def add_worksheet(self, title, rows, cols):
        ws = FakeWorksheet(title, col_count=cols)
        self._ws.append(ws)
        return ws


def _pand():
    return Pand(
        slug="menkemaborgstraat", naam="Menkemaborgstraat 6",
        google_sheet_id="x", google_sheet_worksheet="Huurders",
        history_worksheet="Historie", bunq_rekening_iban="NL00TEST0000000000",
    )


def _titels(ss):
    return {ws.title for ws in ss.worksheets()}


def _kopregel(ss, titel):
    ws = next(w for w in ss.worksheets() if w.title == titel)
    return ws.get_all_values()[0]


def test_lege_nieuwe_sheet_krijgt_alle_tabbladen_en_kopregels():
    # Zoals een gloednieuwe Google Sheet: één leeg standaardtabblad "Blad1".
    ss = FakeSpreadsheet([FakeWorksheet("Blad1", rows=[])])
    r = bouw_sheet_structuur(ss, _pand())

    # Het lege "Blad1" is hernoemd naar "Huurders" (geen verweesd leeg tabblad).
    assert "Blad1" not in _titels(ss)
    assert _titels(ss) == {"Huurders", "Historie", "Aanmeldingen", "Bezichtigingen", "Vertrokken"}
    # Alle vijf gelden als "aangemaakt", niets ongewijzigd.
    assert set(r["aangemaakt"]) == {"Huurders", "Historie", "Aanmeldingen", "Bezichtigingen", "Vertrokken"}
    assert r["ongewijzigd"] == []
    # De koprijen kloppen.
    assert _kopregel(ss, "Huurders") == HUURDERS_HEADER
    assert _kopregel(ss, "Historie") == _HISTORIE_HEADER
    assert _kopregel(ss, "Aanmeldingen") == _AANMELDINGEN_HEADER
    assert _kopregel(ss, "Bezichtigingen") == _BEZICHTIGINGEN_HEADER
    assert _kopregel(ss, "Vertrokken") == _VERTROKKEN_HEADER


def test_huurders_kopregel_is_30_kolommen_breed():
    assert len(HUURDERS_HEADER) == COL_ADVERTENTIE_BORG == 30
    ss = FakeSpreadsheet([FakeWorksheet("Blad1", rows=[])])
    bouw_sheet_structuur(ss, _pand())
    huurders = next(w for w in ss.worksheets() if w.title == "Huurders")
    assert huurders.col_count >= 30  # grid is breed genoeg gemaakt voor kolom AD


def test_idempotent_bestaande_kloppende_tabbladen_blijven_ongemoeid():
    ss = FakeSpreadsheet([
        FakeWorksheet("Huurders", rows=[list(HUURDERS_HEADER)], col_count=30),
        FakeWorksheet("Historie", rows=[list(_HISTORIE_HEADER)]),
        FakeWorksheet("Aanmeldingen", rows=[list(_AANMELDINGEN_HEADER)]),
        FakeWorksheet("Bezichtigingen", rows=[list(_BEZICHTIGINGEN_HEADER)]),
        FakeWorksheet("Vertrokken", rows=[list(_VERTROKKEN_HEADER)]),
    ])
    r = bouw_sheet_structuur(ss, _pand())
    assert r["aangemaakt"] == []
    assert r["kopregel_gezet"] == []
    assert set(r["ongewijzigd"]) == {"Huurders", "Historie", "Aanmeldingen", "Bezichtigingen", "Vertrokken"}


def test_ontbrekend_tabblad_wordt_toegevoegd_naast_bestaande():
    # Huurders bestaat al correct; de rest ontbreekt (bv. een half opgezette sheet).
    ss = FakeSpreadsheet([FakeWorksheet("Huurders", rows=[list(HUURDERS_HEADER)], col_count=30)])
    r = bouw_sheet_structuur(ss, _pand())
    assert r["ongewijzigd"] == ["Huurders"]
    assert set(r["aangemaakt"]) == {"Historie", "Aanmeldingen", "Bezichtigingen", "Vertrokken"}


def test_verkeerde_kopregel_wordt_hersteld():
    ss = FakeSpreadsheet([
        FakeWorksheet("Huurders", rows=[["Kamer", "Naam", "Huur"]], col_count=30),  # oude/foute koppen
    ])
    r = bouw_sheet_structuur(ss, _pand())
    assert "Huurders" in r["kopregel_gezet"]
    assert _kopregel(ss, "Huurders") == HUURDERS_HEADER


def test_niet_leeg_standaardtabblad_wordt_niet_hernoemd():
    # Als "Blad1" al data bevat, laten we 'm staan en maken we "Huurders" apart aan
    # (we overschrijven nooit per ongeluk bestaande gegevens).
    ss = FakeSpreadsheet([FakeWorksheet("Blad1", rows=[["iets", "data"]])])
    bouw_sheet_structuur(ss, _pand())
    assert "Blad1" in _titels(ss)
    assert "Huurders" in _titels(ss)


def test_sheet_id_uit_volledige_link():
    link = "https://docs.google.com/spreadsheets/d/1AbC_dEF-123xyz/edit#gid=0"
    assert sheet_id_uit_invoer(link) == "1AbC_dEF-123xyz"


def test_sheet_id_kale_id_blijft_ongewijzigd():
    assert sheet_id_uit_invoer("  1AbC_dEF-123xyz  ") == "1AbC_dEF-123xyz"
