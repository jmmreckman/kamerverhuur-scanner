"""Koppelt binnengekomen bunq-betalingen aan huurders uit de sheet.

Matching per huurder (een betaling telt mee zodra één van deze twee raak is):
  1. Als een IBAN is opgegeven: betalingen van precies dat IBAN.
  2. Betalingen waarvan de tegenpartijnaam of omschrijving het 'zoekwoord'
     bevat (of, als dat leeg is, de volledige naam of een los naamdeel van de
     huurder).

Een IBAN-match is dus geen exclusieve/enige manier om te matchen - als het
IBAN net niet klopt (typefout, of iemand anders betaalt namens de huurder)
valt de site alsnog terug op naam-matching, in plaats van niets te vinden.

Een betaling wordt aan maximaal 1 huurder toegekend (op volgorde van de sheet),
zodat bedragen niet dubbel meetellen.
"""
from __future__ import annotations

from decimal import Decimal

from .models import Payment, Status, Tenant, TenantResult

# Procentuele tolerantie voor de instapmaand (pro-rata huur + borg): die
# berekening is gevoeliger voor kleine afrondingsverschillen (bv. een dag
# verschil in de ingangsdatum, of een maand met een ander aantal dagen dan
# aangenomen) dan een normale volle-maand huur, dus daar geldt een ruimere
# marge dan de normale (bijna exacte) tolerantie in centen.
_INSTAPMAAND_TOLERANTIE_PERCENTAGE = Decimal("0.10")


def match_tenants_to_payments(
    tenants: list[Tenant],
    payments: list[Payment],
    tolerantie: Decimal = Decimal("0.01"),
    ruimere_tolerantie_kamers: set[str] | None = None,
) -> tuple[list[TenantResult], list[Payment]]:
    """Geeft (resultaten per huurder, niet-gekoppelde betalingen) terug.

    `ruimere_tolerantie_kamers` (kameromers) krijgen een procentuele tolerantie
    van 10% i.p.v. de normale (bijna exacte) tolerantie in centen - bedoeld
    voor de instapmaand, waar de pro-rata huur + borg vaker een paar euro
    afwijkt door afrondingsverschillen (bv. een dag verschil in de
    ingangsdatum) dan een normale volle-maand huur."""
    remaining = list(payments)
    results: list[TenantResult] = []

    for tenant in tenants:
        matched = [p for p in remaining if _matches(tenant, p)]
        for payment in matched:
            remaining.remove(payment)
        ontvangen = sum((p.bedrag for p in matched), Decimal("0"))
        percentage = _INSTAPMAAND_TOLERANTIE_PERCENTAGE if tenant.kamer in (ruimere_tolerantie_kamers or set()) else Decimal("0")
        status = _bepaal_status(ontvangen, tenant.verwacht_bedrag, tolerantie, percentage)
        results.append(
            TenantResult(tenant=tenant, ontvangen_bedrag=ontvangen, status=status, gematchte_betalingen=matched)
        )

    return results, remaining


def _matches(tenant: Tenant, payment: Payment) -> bool:
    if tenant.iban:
        payment_iban = (payment.tegenpartij_iban or "").replace(" ", "").upper()
        if payment_iban == tenant.iban:
            return True
        # Geen exacte IBAN-match: val terug op naam-matching hieronder in
        # plaats van meteen "geen match" te zeggen - het IBAN op de sheet kan
        # verouderd zijn, of iemand anders betaalt namens de huurder.

    zoekterm = (tenant.zoekwoord or tenant.naam).strip().lower()
    if not zoekterm:
        return False
    haystack = f"{payment.tegenpartij_naam} {payment.omschrijving}".lower()
    if zoekterm in haystack:
        return True
    if not tenant.zoekwoord:
        # Val terug op losse naamdelen: de betaling komt soms van iemand anders
        # (bv. een ouder) met alleen de voornaam of een deel van een
        # koppelnaam in de omschrijving, of de bank toont een afgekorte naam.
        for deel in _naam_delen(tenant.naam):
            if deel in haystack:
                return True
    return False


def _naam_delen(naam: str) -> list[str]:
    """Alle los bruikbare delen van een naam (elk woord, en delen van
    koppelnamen), gefilterd op minimaal 3 tekens om valse matches te voorkomen."""
    delen = []
    for woord in naam.strip().lower().split():
        for deel in woord.split("-"):
            if len(deel) >= 3:
                delen.append(deel)
    return delen


def _bepaal_status(
    ontvangen: Decimal, verwacht: Decimal, tolerantie: Decimal, tolerantie_percentage: Decimal = Decimal("0")
) -> Status:
    if ontvangen <= 0:
        return Status.NIET_ONTVANGEN
    effectieve_tolerantie = max(tolerantie, verwacht * tolerantie_percentage)
    verschil = ontvangen - verwacht
    if abs(verschil) <= effectieve_tolerantie:
        return Status.BETAALD
    return Status.TE_VEEL if verschil > 0 else Status.TE_WEINIG
