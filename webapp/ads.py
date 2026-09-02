"""Genereert een kant-en-klare advertentietekst per kamer (om te kopieren/plakken
op Kamernet e.d.).

Er is geen publieke Kamernet-API voor individuele verhuurders (alleen een
XML-feed voor makelaars/vastgoedbeheerders via een zakelijk contact met
Kamernet) - vandaar dat dit alleen een tekst-generator is, geen automatische
plaatsing.
"""
from __future__ import annotations

from decimal import Decimal

from kamerverhuur_scanner.models import Pand, Tenant


def weergave_prijs(kamer: Tenant) -> Decimal:
    """De prijs die op de advertentie/aanbodpagina getoond wordt - de apart
    ingevulde advertentieprijs (kan afwijken van de huur van de huidige/
    vorige huurder, en is vaak al bekend vóórdat er een huurder is), anders
    de gewone "Totale huur"."""
    return kamer.advertentie_prijs if kamer.advertentie_prijs is not None else kamer.verwacht_bedrag


def genereer_advertentie(pand: Pand, kamer: Tenant) -> dict[str, str]:
    prijs = weergave_prijs(kamer)
    titel = f"Kamer te huur - {pand.naam} (kamer {kamer.kamer}) - EUR {prijs:.0f} p/m"
    oppervlakte_regel = (
        f"- Oppervlakte: {kamer.advertentie_oppervlakte}\n" if kamer.advertentie_oppervlakte else ""
    )
    beschikbaar_regel = (
        f"- Beschikbaar per: {kamer.advertentie_beschikbaar_per}"
        + (f" t/m {kamer.advertentie_beschikbaar_tot}" if kamer.advertentie_beschikbaar_tot else "")
        + "\n"
        if kamer.advertentie_beschikbaar_per else "- Beschikbaar per: [vul datum in]\n"
    )
    borg = kamer.advertentie_borg if kamer.advertentie_borg is not None else kamer.borg_bedrag
    borg_regel = f"- Waarborgsom: EUR {borg:.2f}\n" if borg is not None else ""
    beschrijving = (
        f"Te huur: gestoffeerde kamer ({kamer.kamer}) in een gedeeld studentenhuis aan de {pand.naam}.\n\n"
        f"- Huurprijs: EUR {prijs:.2f} per maand (vul aan: in-/exclusief gas/water/licht)\n"
        f"{oppervlakte_regel}"
        "- Gedeelde keuken en badkamer met de andere huisgenoten\n"
        "- Rustige, studentvriendelijke buurt\n"
        f"{beschikbaar_regel}"
        f"{borg_regel}"
        "\nInteresse? Stuur een bericht met een korte introductie!\n\n"
        "[Vul hier eventuele extra details aan: verdieping, balkon, "
        "internet inbegrepen, huisdierenbeleid, foto's toevoegen, etc.]"
    )
    return {"titel": titel, "beschrijving": beschrijving}
