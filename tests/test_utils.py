"""Tests voor kamerverhuur_scanner/utils.py: parse_bedrag() moet alle in de
praktijk getypte/geplakte bedragnotaties aankunnen zonder te crashen - een
onafgevangen ValueError hier eindigt namelijk als een kale 500-fout in elk
formulier dat een bedrag verwerkt (Huurders, Aanbod beheren, Contract, etc.)."""
import pytest

from decimal import Decimal

from kamerverhuur_scanner.utils import format_bedrag_nl, parse_bedrag


@pytest.mark.parametrize("raw, verwacht", [
    ("650.00", "650.00"),  # bunq-notatie
    ("650,00", "650.00"),  # NL-notatie
    ("€ 650,00", "650.00"),  # sheet-notatie met €-teken
    ("1.234,56", "1234.56"),  # NL-notatie met duizendtal-punt
    ("725", "725"),  # zonder centen
    ("725,-", "725.00"),  # NL-gewoonte voor een rond bedrag zonder centen
    ("€725,-", "725.00"),
    ("1.000,-", "1000.00"),
    ("", "0"),
    (None, "0"),
])
def test_parse_bedrag_herkent_alle_notaties(raw, verwacht):
    assert parse_bedrag(raw) == Decimal(verwacht)


def test_parse_bedrag_onherkenbare_tekst_geeft_duidelijke_fout():
    with pytest.raises(ValueError, match="niet interpreteren"):
        parse_bedrag("geen bedrag")


def test_format_bedrag_nl_omgekeerde_van_parse_bedrag():
    assert format_bedrag_nl(Decimal("1234.56")) == "1.234,56"
    assert format_bedrag_nl(Decimal("725.00")) == "725,00"
