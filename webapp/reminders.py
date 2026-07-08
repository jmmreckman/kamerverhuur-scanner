"""Stelt de tekst op voor de twee knoppen op de Betalingen-pagina: een
vriendelijke betaalherinnering en een formele ingebrekestelling. De
beheerder kan de tekst nog aanpassen op het voorbeeldscherm voordat 'm
daadwerkelijk verstuurd wordt.

Geen juridisch advies - de ingebrekestelling is een standaardformulering
(redelijke termijn, art. 6:82 BW) maar laat dit voor belangrijke gevallen
altijd even meelezen door een jurist/rechtsbijstand.
"""
from __future__ import annotations

from datetime import date, timedelta

from kamerverhuur_scanner.models import Pand, Tenant

INGEBREKESTELLING_TERMIJN_DAGEN = 5

_MAAND_NAMEN = [
    "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
]


def _maandnaam(d: date) -> str:
    return f"{_MAAND_NAMEN[d.month - 1]} {d.year}"


def bouw_herinnering(pand: Pand, kamer: Tenant, ontvangen_bedrag) -> dict[str, str]:
    vandaag = date.today()
    onderwerp = f"Betaalherinnering huur {_maandnaam(vandaag)} - {pand.naam}, kamer {kamer.kamer}"
    openstaand = kamer.verwacht_bedrag - ontvangen_bedrag
    tekst = (
        f"Beste {kamer.naam},\n\n"
        f"Bij het controleren van de huurbetalingen zagen we dat de huur van "
        f"{_maandnaam(vandaag)} voor kamer {kamer.kamer} ({pand.naam}) nog niet "
        f"(volledig) is bijgeschreven.\n\n"
        f"Verwacht bedrag: EUR {kamer.verwacht_bedrag:.2f}\n"
        f"Tot nu toe ontvangen: EUR {ontvangen_bedrag:.2f}\n"
        f"Nog openstaand: EUR {openstaand:.2f}\n\n"
        f"Zou je het openstaande bedrag zo spoedig mogelijk willen overmaken naar "
        f"{pand.bunq_rekening_iban}, onder vermelding van je naam en kamernummer?\n\n"
        f"Heb je de betaling inmiddels al gedaan, dan kun je dit bericht als niet "
        f"verzonden beschouwen - het kan een paar dagen duren voordat alles "
        f"verwerkt is.\n\n"
        f"Heb je vragen, laat het gerust weten.\n\n"
        f"Met vriendelijke groet,\n{pand.naam}"
    )
    return {"onderwerp": onderwerp, "tekst": tekst}


def bouw_ingebrekestelling(pand: Pand, kamer: Tenant, ontvangen_bedrag) -> dict[str, str]:
    vandaag = date.today()
    deadline = vandaag + timedelta(days=INGEBREKESTELLING_TERMIJN_DAGEN)
    openstaand = kamer.verwacht_bedrag - ontvangen_bedrag
    onderwerp = f"Ingebrekestelling - openstaande huur {_maandnaam(vandaag)} - {pand.naam}, kamer {kamer.kamer}"
    tekst = (
        f"Beste {kamer.naam},\n\n"
        f"Ondanks eerdere herinnering hebben wij de huur voor {_maandnaam(vandaag)} "
        f"voor kamer {kamer.kamer} ({pand.naam}) nog niet (volledig) ontvangen.\n\n"
        f"Openstaand bedrag: EUR {openstaand:.2f}\n\n"
        f"Bij dezen stellen wij u formeel in gebreke en verzoeken - en voor zover "
        f"nodig sommeren - wij u het openstaande bedrag binnen "
        f"{INGEBREKESTELLING_TERMIJN_DAGEN} dagen na dagtekening van deze e-mail, "
        f"dus uiterlijk op {deadline.strftime('%d-%m-%Y')}, over te maken op "
        f"{pand.bunq_rekening_iban} onder vermelding van uw naam en kamernummer.\n\n"
        f"Indien wij de betaling niet binnen deze termijn hebben ontvangen, "
        f"behouden wij ons het recht voor om verdere maatregelen te treffen, "
        f"waaronder het in rekening brengen van wettelijke rente en incassokosten "
        f"conform de huurovereenkomst en de wet.\n\n"
        f"Heeft u de betaling inmiddels al gedaan, dan kunt u dit bericht als niet "
        f"verzonden beschouwen.\n\n"
        f"Met vriendelijke groet,\n{pand.naam}"
    )
    return {"onderwerp": onderwerp, "tekst": tekst}
