from __future__ import annotations

from dataclasses import dataclass

# Bron: https://www.rotterdam.nl/opkoopbescherming (geraadpleegd juli 2026).
# Check deze lijst en de WOZ-grens af en toe tegen de website, de gemeente kan dit
# beleid aanpassen of uitbreiden naar meer wijken.
BESCHERMDE_WIJKEN = {
    "bergpolder",
    "blijdorp",
    "bloemhof",
    "carnisse",
    "groot-ijsselmonde",
    "hillegersberg-zuid",
    "hillesluis",
    "kralingen-oost",
    "kralingen-west",
    "het lage land",
    "middelland",
    "nieuwe westen",
    "oud-charlois",
    "oud-mathenesse",
    "rubroek",
    "tarwewijk",
}

WOZ_WAARDELOKET_URL = "https://www.wozwaardeloket.nl/"


@dataclass(frozen=True)
class OpkoopResultaat:
    in_beschermde_wijk: bool
    valt_af: bool | None  # None = nog onbekend, WOZ-waarde moet handmatig gecheckt worden
    woz_check_nodig: bool
    woz_check_url: str | None
    toelichting: str


def check_opkoopbescherming(wijknaam: str, woz_grens: int) -> OpkoopResultaat:
    if wijknaam.strip().lower() not in BESCHERMDE_WIJKEN:
        return OpkoopResultaat(
            in_beschermde_wijk=False,
            valt_af=False,
            woz_check_nodig=False,
            woz_check_url=None,
            toelichting=f"'{wijknaam}' valt niet onder de opkoopbescherming.",
        )

    woz_grens_tekst = f"{woz_grens:,}".replace(",", ".")
    return OpkoopResultaat(
        in_beschermde_wijk=True,
        valt_af=None,
        woz_check_nodig=True,
        woz_check_url=WOZ_WAARDELOKET_URL,
        toelichting=(
            f"'{wijknaam}' valt onder de opkoopbescherming. Check de WOZ-waarde op "
            f"{WOZ_WAARDELOKET_URL} — bij een WOZ-waarde boven €{woz_grens_tekst} "
            "(grens van dit moment) valt het huis NIET af, anders wel."
        ),
    )
