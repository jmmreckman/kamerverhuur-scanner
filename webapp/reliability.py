"""Berekent een eenvoudige betrouwbaarheidsscore per kamer op basis van de
opgebouwde betaalgeschiedenis (het 'Historie' tabblad)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from kamerverhuur_scanner.models import HistorieRegel, Status


def bereken_betrouwbaarheid(geschiedenis: list[HistorieRegel]) -> dict | None:
    if not geschiedenis:
        return None
    op_orde = sum(1 for regel in geschiedenis if regel.status == Status.BETAALD)
    totaal = len(geschiedenis)
    return {"percentage": round(100 * op_orde / totaal), "op_orde": op_orde, "totaal": totaal}


def voeg_actuele_maand_toe(
    geschiedenis: list[HistorieRegel],
    cache_status: dict | None,
    kamer_naam: str,
    huurder_naam: str,
    vandaag: date | None = None,
) -> list[HistorieRegel]:
    """Zorgt dat de betaalgeschiedenis altijd een regel voor de lopende
    kalendermaand bevat, gebaseerd op de laatste 'Nu controleren'-uitkomst
    (state-cache), ook als de Historie-sheet die maand nog niet (of nog niet
    bijgewerkt) bevat - bv. omdat de dagelijkse controle vandaag nog niet is
    geweest, of de laatste sheet-schrijfactie is mislukt. Zo staat de huidige
    maand vanaf de 1e gewoon in de lijst, in plaats van pas te verschijnen
    zodra een volgende controle de sheet succesvol bijwerkt."""
    vandaag = vandaag or date.today()
    huidige_maand = vandaag.strftime("%Y-%m")
    if any(regel.maand == huidige_maand for regel in geschiedenis):
        return geschiedenis
    if not cache_status:
        return geschiedenis
    actuele_regel = HistorieRegel(
        maand=huidige_maand,
        kamer=kamer_naam,
        huurder=huurder_naam,
        verwacht_bedrag=Decimal(cache_status["verwacht_bedrag"]),
        ontvangen_bedrag=Decimal(cache_status["ontvangen_bedrag"]),
        status=Status(cache_status["status"]),
        betaaldatum=None,
    )
    return sorted([*geschiedenis, actuele_regel], key=lambda regel: regel.maand)
