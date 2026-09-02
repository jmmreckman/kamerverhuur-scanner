"""Stelt de (Engelstalige) tekst op voor de twee knoppen op de
Betalingen-pagina: een vriendelijke betaalherinnering en een formele
ingebrekestelling. De beheerder kan de tekst nog aanpassen op het
voorbeeldscherm voordat 'm daadwerkelijk verstuurd wordt.

Geen juridisch advies - de ingebrekestelling is een standaardformulering
(redelijke termijn, art. 6:82 BW) maar laat dit voor belangrijke gevallen
altijd even meelezen door een jurist/rechtsbijstand.
"""
from __future__ import annotations

from datetime import date, timedelta

from kamerverhuur_scanner.models import Pand, Tenant

INGEBREKESTELLING_TERMIJN_DAGEN = 5

# Ondertekening van beide e-mails.
AFZENDER_NAAM = "Jurian Reckman"

_MAAND_NAMEN_EN = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


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
        f"Kind regards,\n{AFZENDER_NAAM}"
    )
    return {"onderwerp": onderwerp, "tekst": tekst}


def bouw_ingebrekestelling(pand: Pand, kamer: Tenant, ontvangen_bedrag) -> dict[str, str]:
    vandaag = date.today()
    deadline = vandaag + timedelta(days=INGEBREKESTELLING_TERMIJN_DAGEN)
    openstaand = kamer.verwacht_bedrag - ontvangen_bedrag
    onderwerp = f"Notice of default - outstanding rent {_maandnaam_en(vandaag)}"
    tekst = (
        f"Dear {kamer.naam},\n\n"
        f"Despite an earlier reminder, we have not yet received your (full) rent "
        f"for {_maandnaam_en(vandaag)} for room {kamer.kamer} at {pand.naam}.\n\n"
        f"Outstanding amount: EUR {openstaand:.2f}\n\n"
        f"We hereby formally give you notice of default and request - and, to the "
        f"extent necessary, demand - that you transfer the outstanding amount "
        f"within {INGEBREKESTELLING_TERMIJN_DAGEN} days of the date of this "
        f"e-mail, i.e. no later than {deadline.strftime('%d-%m-%Y')}, to "
        f"{pand.bunq_rekening_iban}, stating your name and room number as "
        f"reference.\n\n"
        f"If we have not received payment within this period, we reserve the "
        f"right to take further action, including charging statutory interest "
        f"and collection costs in accordance with the tenancy agreement and "
        f"Dutch law (art. 6:82 of the Dutch Civil Code).\n\n"
        f"If you have already made the payment, please disregard this message.\n\n"
        f"Kind regards,\n{AFZENDER_NAAM}"
    )
    return {"onderwerp": onderwerp, "tekst": tekst}
