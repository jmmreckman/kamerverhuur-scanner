"""Berekent een eenvoudige betrouwbaarheidsscore per kamer op basis van de
opgebouwde betaalgeschiedenis (het 'Historie' tabblad)."""
from __future__ import annotations

from kamerverhuur_scanner.models import HistorieRegel, Status


def bereken_betrouwbaarheid(geschiedenis: list[HistorieRegel]) -> dict | None:
    if not geschiedenis:
        return None
    op_orde = sum(1 for regel in geschiedenis if regel.status == Status.BETAALD)
    totaal = len(geschiedenis)
    return {"percentage": round(100 * op_orde / totaal), "op_orde": op_orde, "totaal": totaal}
