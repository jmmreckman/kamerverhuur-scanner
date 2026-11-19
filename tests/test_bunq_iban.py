"""Tests voor het herkennen van een bunq-IBAN (is_bunq_iban) en de afgeleide
Pand.heeft_bunq_rekening - bepaalt of de automatische betaalcontrole/lastenscan
voor een pand draait of netjes wordt overgeslagen (bv. bij een Rabo-rekening)."""
from kamerverhuur_scanner.models import Pand
from kamerverhuur_scanner.utils import is_bunq_iban


def _pand(iban):
    return Pand(
        slug="x", naam="X", google_sheet_id="x", google_sheet_worksheet="Huurders",
        history_worksheet="Historie", bunq_rekening_iban=iban,
    )


def test_bunq_iban_wordt_herkend():
    assert is_bunq_iban("NL12BUNQ2012345678") is True


def test_bunq_iban_met_spaties_en_kleine_letters():
    assert is_bunq_iban("nl12 bunq 2012 3456 78") is True


def test_rabo_iban_is_geen_bunq():
    assert is_bunq_iban("NL44RABO0123456789") is False


def test_test_iban_is_geen_bunq():
    assert is_bunq_iban("NL00TEST0000000000") is False


def test_leeg_of_none_iban_is_geen_bunq():
    assert is_bunq_iban("") is False
    assert is_bunq_iban(None) is False
    assert is_bunq_iban("NL12") is False  # te kort


def test_pand_heeft_bunq_rekening_property():
    assert _pand("NL12BUNQ2012345678").heeft_bunq_rekening is True
    assert _pand("NL44RABO0123456789").heeft_bunq_rekening is False
