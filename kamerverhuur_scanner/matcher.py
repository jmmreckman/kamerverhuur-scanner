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

from .models import HistorieRegel, Payment, Status, Tenant, TenantResult

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
    openstaand_tekort: dict[str, Decimal] | None = None,
) -> tuple[list[TenantResult], list[Payment]]:
    """Geeft (resultaten per huurder, niet-gekoppelde betalingen) terug.

    `ruimere_tolerantie_kamers` (kameromers) krijgen een procentuele tolerantie
    van 10% i.p.v. de normale (bijna exacte) tolerantie in centen - bedoeld
    voor de instapmaand, waar de pro-rata huur + borg vaker een paar euro
    afwijkt door afrondingsverschillen (bv. een dag verschil in de
    ingangsdatum) dan een normale volle-maand huur.

    `openstaand_tekort` (per kamer) is een nog openstaande achterstand van
    eerdere maanden (zie openstaand_tekort_uit_geschiedenis()) - een
    overschot deze maand lost dat eerst af voordat de rest als 'te veel
    ontvangen' voor déze maand telt."""
    remaining = list(payments)
    toegekend: dict[int, list[Payment]] = {id(t): [] for t in tenants}

    # Twee rondes: eerst alleen de sterke, ondubbelzinnige matches (IBAN of
    # de volledige zoekwoord/naam-frase letterlijk), dan pas de losse-
    # naamdelen-fallback voor wat daarna nog overblijft. Zonder deze
    # volgorde kon een eerdere huurder in de sheet met alleen een zwakke
    # naamdelen-match een betaling wegkapen die eigenlijk exact bij een
    # latere huurder hoorde (IBAN of letterlijke zoekwoord-match) -
    # sheetvolgorde mag nooit boven een exacte match gaan.
    for matcher_functie in (_matches_sterk, _matches_los):
        for tenant in tenants:
            matched = [p for p in remaining if matcher_functie(tenant, p)]
            for payment in matched:
                remaining.remove(payment)
            toegekend[id(tenant)].extend(matched)

    results: list[TenantResult] = []
    for tenant in tenants:
        matched = toegekend[id(tenant)]
        ontvangen = sum((p.bedrag for p in matched), Decimal("0"))
        percentage = _INSTAPMAAND_TOLERANTIE_PERCENTAGE if tenant.kamer in (ruimere_tolerantie_kamers or set()) else Decimal("0")
        tekort = (openstaand_tekort or {}).get(tenant.kamer, Decimal("0"))
        status, _ = _verwerk_maand(ontvangen, tenant.verwacht_bedrag, tolerantie, percentage, tekort)
        results.append(
            TenantResult(tenant=tenant, ontvangen_bedrag=ontvangen, status=status, gematchte_betalingen=matched)
        )

    return results, remaining


def openstaand_tekort_uit_geschiedenis(geschiedenis: list[HistorieRegel], voor_maand: str) -> Decimal:
    """Som van de opeenvolgende openstaande tekorten (Nog niet ontvangen/Te
    weinig ontvangen) direct vóór `voor_maand` (formaat 'jjjj-mm'), terug-
    gerekend tot en met de eerste maand die wél volledig (of te veel) betaald
    was. Zo telt een latere overbetaling eerst als aflossing van deze
    achterstand, in plaats van als 'te veel ontvangen' voor de nieuwe maand
    - zie match_tenants_to_payments(). `geschiedenis` moet oplopend op maand
    gesorteerd zijn (zie SheetClient.get_geschiedenis())."""
    tekort = Decimal("0")
    for regel in reversed(geschiedenis):
        if regel.maand >= voor_maand:
            continue
        if regel.status not in (Status.NIET_ONTVANGEN, Status.TE_WEINIG):
            break
        tekort += regel.verwacht_bedrag - regel.ontvangen_bedrag
    return tekort


def _matches_sterk(tenant: Tenant, payment: Payment) -> bool:
    """Ondubbelzinnige match: exact IBAN, of de volledige zoekwoord/naam-frase
    letterlijk in de betaling."""
    if tenant.iban:
        payment_iban = (payment.tegenpartij_iban or "").replace(" ", "").upper()
        if payment_iban == tenant.iban:
            return True
        # Geen exacte IBAN-match: val terug op naam-matching hieronder in
        # plaats van meteen "geen match" te zeggen - het IBAN op de sheet kan
        # verouderd zijn, of iemand anders betaalt namens de huurder.

    haystack = f"{payment.tegenpartij_naam} {payment.omschrijving}".lower()
    zoekterm = (tenant.zoekwoord or tenant.naam).strip().lower()
    return bool(zoekterm) and zoekterm in haystack


def _matches_los(tenant: Tenant, payment: Payment) -> bool:
    """Zwakke match: losse delen van dezelfde zoekterm (elk woord, en delen
    van koppelnamen) als laatste redmiddel: bij een (internationale)
    overschrijving door bv. een ouder staat een koppelnaam vaak in een
    andere volgorde (achternaam eerst) of zonder koppelteken tussen de
    delen, waardoor de hele frase niet meer letterlijk voorkomt terwijl de
    losse delen dat wel doen. Bewust dezelfde `zoekterm` als in
    _matches_sterk() (dus het zoekwoord als dat is ingevuld, anders de naam)
    en niet altijd tenant.naam: een expliciet ingevuld zoekwoord (bv.
    "kamer3") is vaak juist gekozen om ambigue matching op de eigenlijke
    naam te voorkomen - dat mag deze fallback niet alsnog omzeilen.

    Wordt in match_tenants_to_payments() bewust pas in een tweede ronde
    toegepast, ná alle sterke matches - anders zou een eerdere huurder in de
    sheet met alleen zo'n zwakke match een betaling kunnen wegkapen die
    eigenlijk exact (IBAN of letterlijke zoekwoord-frase) bij een latere
    huurder hoort."""
    haystack = f"{payment.tegenpartij_naam} {payment.omschrijving}".lower()
    zoekterm = (tenant.zoekwoord or tenant.naam).strip().lower()
    return any(deel in haystack for deel in _naam_delen(zoekterm))


def _matches(tenant: Tenant, payment: Payment) -> bool:
    return _matches_sterk(tenant, payment) or _matches_los(tenant, payment)


def betaling_matcht_naam(tegenpartij_naam: str, omschrijving: str, naam: str, *, min_deellengte: int = 4) -> bool:
    """Of een (niet-gekoppelde) inkomende betaling qua tegenpartijnaam of
    omschrijving bij `naam` past. Gebruikt voor het oud-huurder-signaal op de
    betaalpagina: een betaling die aan geen enkele huidige huurder kon worden
    gekoppeld maar wél op de naam van een vertrokken huurder lijkt, is vaak een
    vergeten automatische overschrijving. Iets strenger dan de gewone
    huurder-matching (naamdelen >= 4 i.p.v. 3 tekens) om valse treffers op korte,
    veelvoorkomende voornamen te beperken."""
    haystack = f"{tegenpartij_naam} {omschrijving}".lower()
    naam = naam.strip().lower()
    if not naam:
        return False
    if naam in haystack:
        return True
    delen = [deel for woord in naam.split() for deel in woord.split("-") if len(deel) >= min_deellengte]
    return any(deel in haystack for deel in delen)


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


def _verwerk_maand(
    ontvangen: Decimal,
    verwacht: Decimal,
    tolerantie: Decimal,
    tolerantie_percentage: Decimal,
    lopend_tekort: Decimal,
) -> tuple[Status, Decimal]:
    """Eén stap van de maand-voor-maand afhandeling mét een lopend tekort van
    eerdere maanden (0 als er geen achterstand is - dan is dit gelijk aan
    _bepaal_status()): een overschot deze maand lost eerst dat tekort af,
    pas de rest telt mee als 'te veel ontvangen' voor déze maand. Geeft de
    status van déze maand en het bijgewerkte lopende tekort voor de volgende
    maand terug (0 zodra alles is ingelopen)."""
    effectieve_tolerantie = max(tolerantie, verwacht * tolerantie_percentage)
    verschil = ontvangen - verwacht
    if verschil < -effectieve_tolerantie:
        return (Status.NIET_ONTVANGEN if ontvangen <= 0 else Status.TE_WEINIG), lopend_tekort - verschil

    overschot = max(verschil, Decimal("0"))
    aflossing = min(overschot, lopend_tekort)
    resterend_overschot = overschot - aflossing
    nieuw_tekort = lopend_tekort - aflossing
    status = Status.TE_VEEL if resterend_overschot > effectieve_tolerantie else Status.BETAALD
    return status, nieuw_tekort
