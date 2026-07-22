"""Winstberekening per pand: huurinkomsten (IN) min kosten (UIT) = winst.

Kosten bestaan uit drie delen:
- een vaste belastingpost van BELASTING_PER_MAAND per pand;
- de instelbare onderhoudsreserve (Pand.onderhoud_reserve_per_maand, zelf in
  te vullen bij "Panden beheren" - bewust geen automatische aanname/
  percentage, dat is een financiële keuze van de beheerder zelf);
- automatisch herkende terugkerende vaste lasten (energie, internet, VvE,
  hypotheek, etc.), gescand uit de uitgaande bunq-transacties van de
  rekening van dit pand (zie herken_terugkerende_lasten()).

Leegstand telt bewust niet mee (in de praktijk verwaarloosbaar voor deze
panden) - de huurinkomsten komen rechtstreeks uit de bestaande betaalcontrole
(dezelfde "ontvangen"-som als op het dashboard), niet uit een aparte aanname."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .models import Payment

BELASTING_PER_MAAND = Decimal("75.00")

# Een tegenpartij moet in minstens dit aantal verschillende kalendermaanden
# voorkomen om als "terugkerende vaste last" te tellen - onderscheidt een
# vaste last (elke maand energie/internet/VvE) van een eenmalige uitgave.
_TERUGKEREND_MINIMUM_MAANDEN = 2

# Hoe ver terug te scannen om terugkerende lasten te herkennen (~3 maanden
# geeft normaal gesproken 2-3 kansen om eenzelfde tegenpartij terug te zien).
SCAN_TERUGBLIK_DAGEN = 95


@dataclass(frozen=True)
class Last:
    omschrijving: str
    bedrag: Decimal  # gemiddeld bedrag per maand, over de gevonden periode


@dataclass(frozen=True)
class Winstoverzicht:
    inkomsten: Decimal
    lasten: list[Last] = field(default_factory=list)
    belasting: Decimal = BELASTING_PER_MAAND
    onderhoud_reserve: Decimal = Decimal("0")

    @property
    def totaal_lasten(self) -> Decimal:
        return sum((last.bedrag for last in self.lasten), Decimal("0")) + self.belasting + self.onderhoud_reserve

    @property
    def winst(self) -> Decimal:
        return self.inkomsten - self.totaal_lasten


def _tegenpartij_sleutel(betaling: Payment) -> str:
    return (betaling.tegenpartij_iban or betaling.tegenpartij_naam or betaling.omschrijving).strip().lower()


def herken_terugkerende_lasten(uitgaande_betalingen: list[Payment]) -> list[Last]:
    """Groepeert uitgaande betalingen op tegenpartij (IBAN, of anders naam/
    omschrijving) en houdt alleen groepen over die in minstens
    `_TERUGKEREND_MINIMUM_MAANDEN` verschillende kalendermaanden voorkomen.
    Bedrag per last = gemiddelde van de gevonden bedragen (vangt kleine
    schommelingen op, bv. een variabel energiebedrag), gesorteerd van hoog
    naar laag."""
    groepen: dict[str, list[Payment]] = {}
    for betaling in uitgaande_betalingen:
        groepen.setdefault(_tegenpartij_sleutel(betaling), []).append(betaling)

    lasten = []
    for reeks in groepen.values():
        maanden = {betaling.datum.strftime("%Y-%m") for betaling in reeks}
        if len(maanden) < _TERUGKEREND_MINIMUM_MAANDEN:
            continue
        gemiddeld = sum((betaling.bedrag for betaling in reeks), Decimal("0")) / len(reeks)
        laatste = reeks[-1]
        omschrijving = laatste.tegenpartij_naam or laatste.omschrijving or "Onbekend"
        lasten.append(Last(omschrijving=omschrijving, bedrag=gemiddeld.quantize(Decimal("0.01"))))
    return sorted(lasten, key=lambda last: last.bedrag, reverse=True)


def bereken_winst(inkomsten: Decimal, lasten: list[Last], onderhoud_reserve: Decimal | None) -> Winstoverzicht:
    return Winstoverzicht(inkomsten=inkomsten, lasten=lasten, onderhoud_reserve=onderhoud_reserve or Decimal("0"))


def verdeelde_winst(winst: Decimal, aantal_beheerders: int) -> Decimal:
    """Winst van een pand met meerdere beheerders wordt gelijk verdeeld (1
    beheerder = volle winst); zie webapp/app.py: _aantal_beheerders()."""
    if aantal_beheerders <= 1:
        return winst
    return (winst / aantal_beheerders).quantize(Decimal("0.01"))


def gecombineerde_winst_over_tijd(
    reeksen: dict[str, list[dict]], aantal_beheerders: dict[str, int]
) -> list[dict]:
    """Combineert de winst-geschiedenis van meerdere panden (zie
    state.laad_winst_geschiedenis(), sowieso al oplopend gesorteerd op datum)
    tot 1 tijdlijn met de gedeelde totale winst per datum, voor de
    "totale winst alle panden"-grafiek op de pandkiezerpagina.

    Voor elk pand wordt op elke datum het laatst bekende punt tot en met die
    datum gebruikt (forward-fill) en gedeeld door het aantal beheerders van
    dat pand (zie verdeelde_winst()) - zo tellen panden die niet exact op
    dezelfde dag een nieuw datapunt kregen toch correct mee. Panden zonder
    enig datapunt tellen nergens in mee."""
    alle_datums = sorted({punt["datum"] for reeks in reeksen.values() for punt in reeks})
    resultaat = []
    for datum in alle_datums:
        totaal = Decimal("0")
        for pand_slug, reeks in reeksen.items():
            bekend_tot_nu = [punt for punt in reeks if punt["datum"] <= datum]
            if not bekend_tot_nu:
                continue
            laatste_winst = Decimal(bekend_tot_nu[-1]["winst"])
            totaal += verdeelde_winst(laatste_winst, aantal_beheerders.get(pand_slug, 1))
        resultaat.append({"datum": datum, "winst": str(totaal.quantize(Decimal("0.01")))})
    return resultaat
