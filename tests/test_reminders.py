"""Tests voor de opgestelde teksten van betaalherinnering/ingebrekestelling."""
from decimal import Decimal

from kamerverhuur_scanner.models import Pand, Tenant
from webapp.reminders import bouw_herinnering, bouw_ingebrekestelling


def _pand() -> Pand:
    return Pand(
        slug="mahoniestraat", naam="Mahoniestraat 15", google_sheet_id="x",
        google_sheet_worksheet="Huurders", history_worksheet="Historie",
        google_drive_folder_id=None, bunq_rekening_iban="NL91ABNA0417164300",
    )


def _kamer() -> Tenant:
    return Tenant(row_index=2, naam="Luisa", kamer="3", verwacht_bedrag=Decimal("650.00"), email="luisa@example.com")


def test_bouw_herinnering_bevat_kernpunten():
    resultaat = bouw_herinnering(_pand(), _kamer(), Decimal("0.00"))
    assert "Luisa" in resultaat["tekst"]
    assert "Mahoniestraat 15" not in resultaat["tekst"]  # geen kameromschrijving/pandnaam in de mail
    assert "kamer" not in resultaat["tekst"].lower()
    assert "650,00" not in resultaat["tekst"]  # we gebruiken punt-notatie, geen NL-komma
    assert "650.00" in resultaat["tekst"]
    assert "NL91ABNA0417164300" in resultaat["tekst"]
    assert "Jurian Reckman" in resultaat["tekst"]
    assert "Dear Luisa" in resultaat["tekst"]
    assert "reminder" in resultaat["onderwerp"].lower()


def test_bouw_ingebrekestelling_bevat_termijn_en_bedrag():
    resultaat = bouw_ingebrekestelling(_pand(), _kamer(), Decimal("300.00"))
    assert "Luisa" in resultaat["tekst"]
    assert "350.00" in resultaat["tekst"]  # 650 - 300 openstaand
    assert "ingebrekestelling" in resultaat["onderwerp"].lower() or "Ingebrekestelling" in resultaat["onderwerp"]
    assert "dagen" in resultaat["tekst"]
