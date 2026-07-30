"""Checks voor kamerbewoning (omzettingsvergunning) in Den Haag.

Anders dan Rotterdam (nulquotum, 50-meter-regel, opkoopbescherming/WOZ) draait
Den Haag om twee harde, automatisch te controleren voorwaarden plus een reeks
informatieve punten die je zelf bij de gemeente natrekt (net als in de scanner
van Wout, waar die als "[i]" verschijnen).

Bron regels: gemeente Den Haag, "Kamerbewoning" + Nota Woningvoorraad Den Haag
2025 (RIS323747). Kort:
- Vanaf 3 bewoners is een omzettingsvergunning nodig; maximaal 8 bewoners.
- Minstens 18 m² gebruiksoppervlakte per bewoner -> max bewoners = m² // 18.
- Vergunningen worden alleen afgegeven in wijken die in de 2 meest recente
  Leefbaarometer-metingen 'goed' tot 'uitstekend' scoren (zie TOEGESTANE_WIJKEN).
- Vanaf 5 bewoners gelden extra geluidsisolatie-eisen; vanaf 5 kamers extra
  brandveiligheidseisen + een gebruiksmelding via het Omgevingsloket.
- Per wijk max. 10% van de woningen als omzetting; per gebouw/aaneengesloten rij
  max. 33,3%. De actuele stand daarvan is niet publiek op te vragen -> informatief.
- Opkoopbescherming/WOZ is voor omzettingsvergunningen GESCHRAPT (Nota p.14) -> in
  Den Haag dus GEEN filter, alleen ter info.
"""
from __future__ import annotations

from dataclasses import dataclass

# Wijken waar Den Haag omzettingsvergunningen afgeeft: 'goed', 'zeer goed' of
# 'uitstekend' op de Leefbaarometer-indicator Leefbaarheidssituatie in ZOWEL de
# meting van 2022 als die van 2024 (de 2 meest recente). Afgeleid van
# https://www.leefbaarometer.nl (schaal Wijk, gemeente GM0518 Den Haag).
# Dit komt exact overeen met de wijken die in de scanner van Wout "toegestaan"
# zijn. Leefbaarometer meet ~eens per 2 jaar, dus deze lijst hoeft alleen bij een
# nieuwe meting herzien te worden (dan opnieuw de 2 laatste metingen nalopen).
LEEFBAAROMETER_METINGEN = "2022 en 2024"
TOEGESTANE_WIJKEN = {
    "Belgisch Park",
    "Westbroekpark en Duttendel",
    "Benoordenhout",
    "Archipelbuurt",
    "Van Stolkpark en Scheveningse Bosjes",
    "Scheveningen",
    "Duindorp",
    "Geuzen- en Statenkwartier",
    "Zorgvliet",
    "Duinoord",
    "Bomen- en Bloemenbuurt",
    "Vogelwijk",
    "Bohemen en Meer en Bos",
    "Kijkduin en Ockenburgh",
    "Kraayenstein en Vroondaal",
    "Waldeck",
    "Vruchtenbuurt",
    "Valkenboskwartier",
    "Regentessekwartier",
    "Zeeheldenkwartier",
    "Willemspark",
    "Haagse Bos",
    "Bezuidenhout",
    "Centrum",
    "Wateringse Veld",
    "Hoornwijk",
    "Ypenburg",
    "Forepark",
    "Leidschenveen",
}

# PDOK/CBS levert de wijknaam soms met andere leestekens/spaties dan hierboven
# (bv. "Bomen en Bloemenbuurt" i.p.v. "Bomen- en Bloemenbuurt"). Door bij het
# vergelijken koppeltekens door spaties te vervangen en dubbele spaties op te
# ruimen hoeven we PDOK's exacte schrijfwijze niet te volgen.
def _normaliseer(naam: str) -> str:
    return " ".join(naam.strip().lower().replace("-", " ").split())


_TOEGESTANE_WIJKEN_GENORMALISEERD = {_normaliseer(w) for w in TOEGESTANE_WIJKEN}

# Woonplaatsnaam zoals PDOK die voor Den Haag teruggeeft is "'s-Gravenhage";
# "Den Haag" nemen we voor de zekerheid mee (bv. handmatig aangeleverd adres).
DEN_HAAG_WOONPLAATSEN = {"'s-gravenhage", "den haag", "'s gravenhage"}

_PERSOON_OPPERVLAKTE = 18  # m² gebruiksoppervlakte per bewoner
_MAX_BEWONERS_CAP = 8  # harde bovengrens van de gemeente


def is_den_haag(woonplaats: str) -> bool:
    return woonplaats.strip().lower() in DEN_HAAG_WOONPLAATSEN


def wijk_toegestaan(*wijknamen: str) -> bool:
    """True als één van de opgegeven namen (bv. de PDOK-wijknaam én de -buurtnaam,
    afhankelijk van op welk niveau PDOK de naam teruggeeft) op de groene lijst staat."""
    return any(_normaliseer(naam) in _TOEGESTANE_WIJKEN_GENORMALISEERD for naam in wijknamen if naam)


def bereken_max_bewoners(oppervlakte: int | None) -> int | None:
    """Max. aantal bewoners = gebruiksoppervlakte // 18, met de harde cap van 8.
    None als de oppervlakte onbekend is."""
    if not oppervlakte:
        return None
    return min(oppervlakte // _PERSOON_OPPERVLAKTE, _MAX_BEWONERS_CAP)


@dataclass(frozen=True)
class DenHaagResultaat:
    valt_af: bool
    afvalreden: str | None
    wijk_toegestaan: bool
    max_bewoners: int | None
    # Informatieve punten die je zelf bij de gemeente moet natrekken (niet
    # automatisch hard te controleren) - bedoeld om in het rapport te tonen.
    signalen: list[str]


def beoordeel(
    wijknaam: str,
    buurtnaam: str,
    oppervlakte: int | None,
    min_bewoners: int,
    aantal_woningen_in_pand: int | None = None,
) -> DenHaagResultaat:
    """Past de twee harde Den Haag-filters toe (toegestane wijk + genoeg
    capaciteit) en verzamelt de informatieve punten. `wijknaam`/`buurtnaam` zijn
    de twee PDOK-niveaus (we matchen op beide, zie wijk_toegestaan)."""
    toegestaan = wijk_toegestaan(wijknaam, buurtnaam)
    max_bewoners = bereken_max_bewoners(oppervlakte)

    if not toegestaan:
        return DenHaagResultaat(
            valt_af=True,
            afvalreden=(
                f"Wijk '{wijknaam}' geeft geen omzettingsvergunning voor kamerbewoning "
                f"(niet 'goed'-'uitstekend' op de Leefbaarometer, meting {LEEFBAAROMETER_METINGEN})."
            ),
            wijk_toegestaan=False,
            max_bewoners=max_bewoners,
            signalen=[],
        )

    if max_bewoners is not None and max_bewoners < min_bewoners:
        return DenHaagResultaat(
            valt_af=True,
            afvalreden=(
                f"Te weinig capaciteit: max {max_bewoners} bewoner(s) mogelijk "
                f"(minimaal {min_bewoners} gewenst)."
            ),
            wijk_toegestaan=True,
            max_bewoners=max_bewoners,
            signalen=[],
        )

    signalen: list[str] = []
    if max_bewoners is None:
        signalen.append(
            "Oppervlakte onbekend: max. aantal bewoners (m² / 18) kon niet bepaald worden."
        )
    if max_bewoners is not None and max_bewoners >= 5:
        signalen.append(
            "Vanaf 5 bewoners gelden extra geluidsisolatie-eisen (luchtgeluid ≥47 dB, "
            "contactgeluid ≤59 dB)."
        )
        signalen.append(
            "Vanaf 5 kamers gelden extra brandveiligheidseisen + een gebruiksmelding via "
            "het Omgevingsloket."
        )
    if aantal_woningen_in_pand is not None:
        max_omzettingen = aantal_woningen_in_pand // 3
        signalen.append(
            f"Pand-quotum: pand heeft {aantal_woningen_in_pand} woning(en); per gebouw/rij "
            f"mag max. 33,3% kamerbewoning zijn (≈{max_omzettingen} vergunning(en)). "
            "Check bij de gemeente of er al één vergund is."
        )
    else:
        signalen.append(
            "Pand-quotum: per gebouw/aaneengesloten rij mag max. 33,3% kamerbewoning zijn; "
            "check bij de gemeente."
        )
    signalen.append(
        "Wijk-quotum: per wijk max. 10% van de woningen als omzetting; actuele stand niet "
        "publiek op te vragen, check bij de gemeente."
    )
    signalen.append(
        "MSW/woonoverlast: meldingen bij het Meld- en Steunpunt Woonoverlast kunnen een "
        "reden zijn om de vergunning te weigeren (checkt de gemeente bij de aanvraag)."
    )
    signalen.append(
        "Opkoopbescherming/WOZ is voor omzettingsvergunningen geschrapt (Nota p.14) - in "
        "Den Haag dus geen belemmering."
    )

    return DenHaagResultaat(
        valt_af=False,
        afvalreden=None,
        wijk_toegestaan=True,
        max_bewoners=max_bewoners,
        signalen=signalen,
    )
