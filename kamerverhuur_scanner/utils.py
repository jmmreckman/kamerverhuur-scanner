"""Kleine gedeelde hulpfuncties."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


def parse_bedrag(raw: str | None) -> Decimal:
    """Parseert een bedrag uit de sheet, van bunq, of rechtstreeks getypt in
    een formulier, naar een Decimal.

    Accepteert "650.00" (bunq), "650,00" of "€ 650,00" (Google Sheets, NL-
    notatie), en de in NL gangbare notatie voor een rond bedrag zonder centen,
    "650,-" (anders crasht het meteen zodra iemand een prijs zonder centen
    intypt in bv. het aanbod-/huurderformulier).
    """
    if raw is None:
        return Decimal("0")
    text = str(raw).strip().replace("€", "").replace(" ", "")
    if not text:
        return Decimal("0")
    if text.endswith(",-"):
        text = text[:-2] + ",00"
    if "," in text and "." in text:
        # NL notatie met duizendtal-punt: "1.234,56"
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Kon bedrag '{raw}' niet interpreteren") from exc


def format_bedrag_nl(bedrag: Decimal) -> str:
    """Het omgekeerde van parse_bedrag(): een Decimal naar NL-notatie
    ("1234.56" -> "1.234,56"), zonder €-teken (roep dat er zelf voor als
    dat nodig is)."""
    return f"{bedrag:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
