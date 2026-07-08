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

# Ondertekening van de (Engelstalige) vriendelijke betaalherinnering.
HERINNERING_AFZENDER = "Jurian Reckman"

_MAAND_NAMEN_NL = [
    "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
]
_MAAND_NAMEN_EN = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _maandnaam(d: date) -> str:
    return f"{_MAAND_NAMEN_NL[d.month - 1]} {d.year}"


def _maandnaam_en(d: date) -> str:
    return f"{_MAAND_NAMEN_EN[d.month - 1]} {d.year}"


def bouw_herinnering(pand: Pand, kamer: Tenant, ontvangen_bedrag) -> dict[str, str]:
    vandaag = date.today()
    onderwerp = f"Payment reminder - rent {_maandnaam_en(vandaag)}"
    openstaand = kamer.verwacht_bedrag - ontvangen_bedrag
    tekst = (
        f"Dear {kamer.naam},\n\n"
        f"While checking rent payments, we noticed that your rent for "
        f"{_maandnaam_en(vandaag)} has not been (fully) received yet.\n\n"
        f"Expected amount: EUR {kamer.verwacht_bedrag:.2f}\n"
        f"Received so far: EUR {ontvangen_bedrag:.2f}\n"
        f"Outstanding: EUR {openstaand:.2f}\n\n"
        f"Could you please transfer the outstanding amount as soon as possible to "
        f"{pand.bunq_rekening_iban}, stating your name as reference?\n\n"
        f"If you have already made the payment, please disregard this message - it "
        f"can take a few days before everything is processed.\n\n"
        f"If you have any questions, please let us know.\n\n"
        f"Kind regards,\n{HERINNERING_AFZENDER}"
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
