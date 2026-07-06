"""Kleine gedeelde hulpfuncties."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


def parse_bedrag(raw: str | None) -> Decimal:
    """Parseert een bedrag uit de sheet of van bunq naar een Decimal.

    Accepteert zowel "650.00" (bunq) als "650,00" of "€ 650,00" (Google Sheets, NL-notatie).
    """
    if raw is None:
        return Decimal("0")
    text = str(raw).strip().replace("€", "").replace(" ", "")
    if not text:
        return Decimal("0")
    if "," in text and "." in text:
        # NL notatie met duizendtal-punt: "1.234,56"
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Kon bedrag '{raw}' niet interpreteren") from exc
