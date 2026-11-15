"""VvE-filter voor kansen.steenhub.nl: wel/geen Vereniging van Eigenaars + de
maandelijkse bijdrage.

De Move-kenmerken leveren "Bijdrage VVE p/m" (bv. "€ 78,75") en een VvE-checklist
("Periodieke bijdrage: Ja (€ 78,75 p.m.)", Reservefonds, Onderhoudsplan, ...). Een
woonhuis heeft normaal géén VvE; een appartement vrijwel altijd wel. We leiden dus af
uit het woningtype + de aanwezige VvE-signalen, en parsen de bijdrage los.

Pure functies, geen externe dependencies (alleen Decimal), dus los testbaar.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# "€ 78,75" of "Ja (€ 78,75 p.m.)" of "78,75" -> Decimal("78.75"). Nederlandse notatie:
# punt = duizendtal, komma = decimaal.
_BEDRAG_RE = re.compile(r"(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{1,2}))?")


def parse_vve_bijdrage(waarde: str | None) -> Decimal | None:
    """Haalt het maandbedrag uit een VvE-bijdrage-string. None als er geen bedrag staat
    (of bv. 'Geen'/'n.v.t.')."""
    if not waarde:
        return None
    tekst = waarde.replace(" ", " ")
    m = _BEDRAG_RE.search(tekst)
    if not m:
        return None
    heel = m.group(1).replace(".", "")
    decimalen = m.group(2) or "00"
    try:
        bedrag = Decimal(f"{heel}.{decimalen}")
    except InvalidOperation:
        return None
    return bedrag if bedrag > 0 else None


def classificeer_vve(
    woningtype: str | None,
    bijdrage_pm: Decimal | None = None,
    heeft_vve_signaal: bool | None = None,
) -> dict:
    """Bepaalt of er een VvE is + de bijdrage.

    `woningtype` is de grove classificatie ('appartement'/'woonhuis'/None, zie
    woningkenmerken.classificeer_woningtype). `heeft_vve_signaal` is een expliciet
    ja/nee als de bron dat geeft (bv. de VvE-checklist); anders leiden we af:
    woonhuis -> geen VvE, appartement -> wel, verder onbekend.
    Geeft: {"heeft_vve": True|False|None, "bijdrage_pm": Decimal|None}."""
    if heeft_vve_signaal is not None:
        heeft = heeft_vve_signaal
    elif woningtype == "woonhuis":
        heeft = False
    elif bijdrage_pm is not None:
        heeft = True
    elif woningtype == "appartement":
        heeft = True
    else:
        heeft = None
    # Een woonhuis zonder VvE heeft logischerwijs geen bijdrage.
    return {"heeft_vve": heeft, "bijdrage_pm": None if heeft is False else bijdrage_pm}
