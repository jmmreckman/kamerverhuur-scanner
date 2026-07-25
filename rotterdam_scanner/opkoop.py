from __future__ import annotations

from dataclasses import dataclass

# Bron: https://www.rotterdam.nl/opkoopbescherming (geraadpleegd juli 2026). Rotterdam.nl
# schrijft samengestelde buurtnamen met een koppelteken ("Oud-Charlois"), maar de
# buurtnaam die we via PDOK/CBS binnenkrijgen gebruikt een spatie ("Oud Charlois") --
# vandaar dat we bij het vergelijken koppeltekens en spaties gelijkstellen (zie
# _normaliseer), in plaats van hier exact PDOK's schrijfwijze te moeten volgen.
# Check deze lijst en de WOZ-grens af en toe tegen de website, de gemeente kan dit
# beleid aanpassen of uitbreiden naar meer wijken.
#
# Rozenburg is sinds de gemeentelijke herindeling van 2010 onderdeel van de gemeente
# Rotterdam en valt onder hetzelfde opkoopbeschermingsbeleid als de rest van de stad.
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
    "rozenburg",
    "rubroek",
    "tarwewijk",
}


def _normaliseer(naam: str) -> str:
    return naam.strip().lower().replace("-", " ")


_BESCHERMDE_WIJKEN_GENORMALISEERD = {_normaliseer(w) for w in BESCHERMDE_WIJKEN}

WOZ_WAARDELOKET_URL = "https://www.wozwaardeloket.nl/"


@dataclass(frozen=True)
class OpkoopResultaat:
    in_beschermde_wijk: bool
    valt_af: bool | None  # None = nog onbekend, WOZ-waarde moet (handmatig) gecheckt worden
    woz_check_nodig: bool
    woz_check_url: str | None
    toelichting: str


def check_opkoopbescherming(
    wijknaam: str, woz_grens: int, woz_waarde: int | None = None
) -> OpkoopResultaat:
    if _normaliseer(wijknaam) not in _BESCHERMDE_WIJKEN_GENORMALISEERD:
        return OpkoopResultaat(
            in_beschermde_wijk=False,
            valt_af=False,
            woz_check_nodig=False,
            woz_check_url=None,
            toelichting=f"'{wijknaam}' valt niet onder de opkoopbescherming.",
        )

    woz_grens_tekst = f"{woz_grens:,}".replace(",", ".")

    if woz_waarde is not None:
        valt_af = woz_waarde <= woz_grens
        woz_waarde_tekst = f"{woz_waarde:,}".replace(",", ".")
        if valt_af:
            conclusie = (
                f"WOZ-waarde €{woz_waarde_tekst} zit op of onder de grens van €{woz_grens_tekst} "
                "-> opkoopbescherming is van toepassing, huis valt af."
            )
        else:
            conclusie = (
                f"WOZ-waarde €{woz_waarde_tekst} zit boven de grens van €{woz_grens_tekst} "
                "-> opkoopbescherming is niet van toepassing, huis valt NIET af."
            )
        return OpkoopResultaat(
            in_beschermde_wijk=True,
            valt_af=valt_af,
            woz_check_nodig=False,
            woz_check_url=None,
            toelichting=f"'{wijknaam}' valt onder de opkoopbescherming. {conclusie}",
        )

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
