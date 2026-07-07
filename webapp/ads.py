"""Genereert een kant-en-klare advertentietekst per kamer (om te kopieren/plakken
op Kamernet e.d.).

Er is geen publieke Kamernet-API voor individuele verhuurders (alleen een
XML-feed voor makelaars/vastgoedbeheerders via een zakelijk contact met
Kamernet) - vandaar dat dit alleen een tekst-generator is, geen automatische
plaatsing.
"""
from __future__ import annotations

from kamerverhuur_scanner.models import Pand, Tenant


def genereer_advertentie(pand: Pand, kamer: Tenant) -> dict[str, str]:
    titel = f"Kamer te huur - {pand.naam} (kamer {kamer.kamer}) - EUR {kamer.verwacht_bedrag:.0f} p/m"
    beschrijving = (
        f"Te huur: gestoffeerde kamer ({kamer.kamer}) in een gedeeld studentenhuis aan de {pand.naam}.\n\n"
        f"- Huurprijs: EUR {kamer.verwacht_bedrag:.2f} per maand (vul aan: in-/exclusief gas/water/licht)\n"
        "- Gedeelde keuken en badkamer met de andere huisgenoten\n"
        "- Rustige, studentvriendelijke buurt\n"
        "- Beschikbaar per: [vul datum in]\n\n"
        "Interesse? Stuur een bericht met een korte introductie!\n\n"
        "[Vul hier eventuele extra details aan: oppervlakte, verdieping, balkon, "
        "internet inbegrepen, huisdierenbeleid, foto's toevoegen, etc.]"
    )
    return {"titel": titel, "beschrijving": beschrijving}
