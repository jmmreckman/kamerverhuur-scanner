"""Signaleert wanneer een tijdelijk huurcontract binnenkort 'aangezegd' moet
worden: volgens Nederlands huurrecht (art. 7:271 BW) moet de verhuurder de
huurder tussen 1 en 3 maanden vóór de einddatum schriftelijk laten weten dat
het tijdelijke contract echt afloopt - gebeurt dat niet op tijd, dan wordt het
contract stilzwijgend voor onbepaalde tijd.

Dit is alleen een informatieve waarschuwing op basis van de datum in de sheet
(kolom "Contract einddatum"); geen juridisch advies en geen automatische
verzending (dat komt in een latere fase).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class AanzegStatus:
    einddatum: date
    dagen_tot_einddatum: int
    venster_start: date  # 3 maanden voor de einddatum
    venster_einde: date  # 1 maand voor de einddatum
    moet_nu_aanzeggen: bool
    venster_verstreken: bool  # binnen 1 maand voor einde (of erna), zonder dat we het bijhielden


def _parse_datum(tekst: str) -> date | None:
    for formaat in ("%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(tekst.strip(), formaat).date()
        except ValueError:
            continue
    return None


def _min_maanden(d: date, maanden: int) -> date:
    maand_index = d.month - 1 - maanden
    jaar = d.year + maand_index // 12
    maand = maand_index % 12 + 1
    laatste_dag = _dagen_in_maand(jaar, maand)
    return date(jaar, maand, min(d.day, laatste_dag))


def _dagen_in_maand(jaar: int, maand: int) -> int:
    volgende = date(jaar + 1, 1, 1) if maand == 12 else date(jaar, maand + 1, 1)
    return (volgende - date(jaar, maand, 1)).days


def bereken_aanzeg_status(contract_einddatum: str | None, vandaag: date | None = None) -> AanzegStatus | None:
    """Geeft None terug als er geen (parsbare) einddatum is, bv. bij 'onbepaalde tijd'."""
    if not contract_einddatum:
        return None
    einddatum = _parse_datum(contract_einddatum)
    if einddatum is None:
        return None

    vandaag = vandaag or date.today()
    venster_start = _min_maanden(einddatum, 3)
    venster_einde = _min_maanden(einddatum, 1)

    return AanzegStatus(
        einddatum=einddatum,
        dagen_tot_einddatum=(einddatum - vandaag).days,
        venster_start=venster_start,
        venster_einde=venster_einde,
        moet_nu_aanzeggen=venster_start <= vandaag <= venster_einde,
        venster_verstreken=venster_einde < vandaag <= einddatum,
    )
