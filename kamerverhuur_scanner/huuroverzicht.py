"""Huuroverzicht ("bankview"): per pand de kale huur / servicekosten / totale
huur per kamer, plus de maandelijkse hypotheeklasten, en daaruit de voor
hypotheekverstrekkers relevante kerngetallen:

- **netto** = kale huur - hypotheekrente (bewust ALLEEN deze twee; andere lasten
  horen op de reguliere winstpagina, niet hier);
- **jouw aandeel** van die netto = netto gedeeld door het aantal eigenaren van
  het pand (1 eigenaar = volle netto; zie `PandHuur.aantal_eigenaren`);
- **ICR** = kale huur / hypotheekrente (de Domivest/bank-definitie: bruto kale
  huur gedeeld door de rente, géén kostenafslag).

Dit is een pure rekenlaag zonder I/O: de regels (uit de Google Sheet + eventuele
handmatig ingevulde regels voor oude huurders) en de hypotheekbedragen worden er
kant-en-klaar ingestopt. Zo is alles los testbaar zonder gspread/Flask. De
koppeling naar de sheet/state zit in webapp/app.py (_bouw_huuroverzicht)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


def _cent(bedrag: Decimal) -> Decimal:
    return bedrag.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class HuurRegel:
    """Eén kamer op het huuroverzicht. `handmatig` = zelf ingevoerd (bv. een oude
    huurder of een kamer die nog niet in de Sheet staat), i.t.t. een regel die
    live uit de Huurders-sheet komt."""
    kamer: str
    naam: str
    kale: Decimal
    servicekosten: Decimal
    handmatig: bool = False
    # id van de handmatige regel in de state (voor verwijderen); 0 voor een regel
    # die live uit de Huurders-sheet komt.
    regel_id: int = 0

    @property
    def totaal(self) -> Decimal:
        return self.kale + self.servicekosten


@dataclass(frozen=True)
class PandHuur:
    slug: str
    naam: str
    regels: list[HuurRegel]
    rente: Decimal | None  # hypotheekrente per maand (voor netto + ICR)
    last: Decimal | None  # totale hypotheeklast per maand (rente + aflossing); alleen ter info
    aantal_eigenaren: int = 1
    # Gevuld als de Huurders-sheet niet gelezen kon worden; de handmatige regels
    # (indien aanwezig) worden dan nog wél getoond, met deze waarschuwing erbij.
    fout: str | None = None

    @property
    def kale_totaal(self) -> Decimal:
        return sum((r.kale for r in self.regels), Decimal("0"))

    @property
    def service_totaal(self) -> Decimal:
        return sum((r.servicekosten for r in self.regels), Decimal("0"))

    @property
    def totaal(self) -> Decimal:
        return self.kale_totaal + self.service_totaal

    @property
    def gedeeld(self) -> bool:
        return self.aantal_eigenaren > 1

    @property
    def netto(self) -> Decimal | None:
        """Kale huur - hypotheekrente (volledig pand). None als de rente onbekend is."""
        if self.rente is None:
            return None
        return self.kale_totaal - self.rente

    @property
    def netto_eigen(self) -> Decimal | None:
        """Jouw aandeel van de netto (netto / aantal eigenaren)."""
        netto = self.netto
        if netto is None:
            return None
        if self.aantal_eigenaren <= 1:
            return netto
        return _cent(netto / self.aantal_eigenaren)

    @property
    def icr(self) -> Decimal | None:
        """Kale huur / hypotheekrente. None als er geen (positieve) rente bekend is."""
        if not self.rente or self.rente <= 0:
            return None
        return _cent(self.kale_totaal / self.rente)


@dataclass(frozen=True)
class PersoonlijkeLening:
    """Een lening buiten de hypotheken om (bv. een familielening bij vader), op
    portefeuilleniveau. Puur bedoeld voor JOUW totale-rentedekkingscheck - dit
    telt NIET mee in Domivest's eigen ICR (die kijkt alleen naar huur/hypotheek-
    rente per onderpand; een familielening is voor Domivest 'eigen middelen')."""
    omschrijving: str
    bedrag: Decimal
    jaarrente: Decimal  # procent per jaar, bv. Decimal("6") = 6%
    lening_id: int = 0

    @property
    def maandrente(self) -> Decimal:
        """Rente per maand = bedrag × jaarrente% / 12. Alleen rente (aflossing
        is geen rentelast en hoort niet in een dekkingsratio)."""
        if self.bedrag <= 0 or self.jaarrente <= 0:
            return Decimal("0")
        return _cent(self.bedrag * self.jaarrente / Decimal("1200"))


def som_maandrente(leningen: list[PersoonlijkeLening]) -> Decimal:
    return sum((lening.maandrente for lening in leningen), Decimal("0"))


def rentedekking(kale_huur: Decimal, rentelast: Decimal | None) -> Decimal | None:
    """Totale rentedekking = kale huur / rentelast. None als er geen (positieve)
    rentelast is. Dit is JOUW huishoud-dekkingscheck (alle huur t.o.v. alle
    rentelasten), niet Domivest's per-pand-ICR."""
    if rentelast is None or rentelast <= 0:
        return None
    return _cent(kale_huur / rentelast)


@dataclass(frozen=True)
class Totalen:
    kale: Decimal
    service: Decimal
    totaal: Decimal
    rente: Decimal  # som van de bekende rentes
    last: Decimal  # som van de bekende maandlasten
    netto_vol: Decimal | None  # som van de per-pand netto (volledig)
    netto_eigen: Decimal | None  # som van jouw aandeel per pand
    icr: Decimal | None  # portefeuille-ICR: som kale (van panden mét rente) / som rente
    panden_met_rente: int


def totaliseer(panden: list[PandHuur]) -> Totalen:
    """Telt de panden op tot portefeuille-totalen. De netto-regels tellen alleen
    panden mee waarvoor de rente bekend is; de portefeuille-ICR deelt de kale huur
    van die panden door hun totale rente (zo vertekent een pand zónder ingevulde
    rente het kengetal niet)."""
    kale = sum((p.kale_totaal for p in panden), Decimal("0"))
    service = sum((p.service_totaal for p in panden), Decimal("0"))
    rente = sum((p.rente for p in panden if p.rente is not None), Decimal("0"))
    last = sum((p.last for p in panden if p.last is not None), Decimal("0"))

    met_netto = [p for p in panden if p.netto is not None]
    netto_vol = sum((p.netto for p in met_netto), Decimal("0")) if met_netto else None
    netto_eigen = sum((p.netto_eigen for p in met_netto), Decimal("0")) if met_netto else None

    met_rente = [p for p in panden if p.rente is not None and p.rente > 0]
    kale_met_rente = sum((p.kale_totaal for p in met_rente), Decimal("0"))
    rente_pos = sum((p.rente for p in met_rente), Decimal("0"))
    icr = _cent(kale_met_rente / rente_pos) if rente_pos > 0 else None

    return Totalen(
        kale=kale, service=service, totaal=kale + service, rente=rente, last=last,
        netto_vol=netto_vol, netto_eigen=netto_eigen, icr=icr, panden_met_rente=len(met_rente),
    )
