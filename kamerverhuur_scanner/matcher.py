"""Koppelt binnengekomen bunq-betalingen aan huurders uit de sheet.

Matching-volgorde per huurder:
  1. Als een IBAN is opgegeven: alleen betalingen van precies dat IBAN.
  2. Anders: betalingen waarvan de tegenpartijnaam of omschrijving het
     'zoekwoord' bevat (of, als dat leeg is, de volledige naam van de huurder).

Een betaling wordt aan maximaal 1 huurder toegekend (op volgorde van de sheet),
zodat bedragen niet dubbel meetellen.
"""
from __future__ import annotations

from decimal import Decimal

from .models import Payment, Status, Tenant, TenantResult


def match_tenants_to_payments(
    tenants: list[Tenant],
    payments: list[Payment],
    tolerantie: Decimal = Decimal("0.01"),
) -> tuple[list[TenantResult], list[Payment]]:
    """Geeft (resultaten per huurder, niet-gekoppelde betalingen) terug."""
    remaining = list(payments)
    results: list[TenantResult] = []

    for tenant in tenants:
        matched = [p for p in remaining if _matches(tenant, p)]
        for payment in matched:
            remaining.remove(payment)
        ontvangen = sum((p.bedrag for p in matched), Decimal("0"))
        status = _bepaal_status(ontvangen, tenant.verwacht_bedrag, tolerantie)
        results.append(
            TenantResult(tenant=tenant, ontvangen_bedrag=ontvangen, status=status, gematchte_betalingen=matched)
        )

    return results, remaining


def _matches(tenant: Tenant, payment: Payment) -> bool:
    if tenant.iban:
        payment_iban = (payment.tegenpartij_iban or "").replace(" ", "").upper()
        return payment_iban == tenant.iban

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


def _bepaal_status(ontvangen: Decimal, verwacht: Decimal, tolerantie: Decimal) -> Status:
    if ontvangen <= 0:
        return Status.NIET_ONTVANGEN
    verschil = ontvangen - verwacht
    if abs(verschil) <= tolerantie:
        return Status.BETAALD
    return Status.TE_VEEL if verschil > 0 else Status.TE_WEINIG
