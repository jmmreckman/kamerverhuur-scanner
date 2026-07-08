"""Voert een betaalcontrole uit voor één pand: sheet lezen, bunq-betalingen
ophalen, matchen, en (tenzij dry-run) de sheet + geschiedenis bijwerken en
het resultaat cachen voor de website."""
from __future__ import annotations

import calendar
import logging
from datetime import date, timedelta

from decimal import Decimal

from . import state
from .bunq_client import BunqClient
from .config import Config
from .matcher import _bepaal_status, match_tenants_to_payments
from .models import Pand, Payment, Status, Tenant, TenantResult
from .sheet_client import SheetClient

logger = logging.getLogger(__name__)


def run_check(
    config: Config, pand: Pand, dry_run: bool = False
) -> tuple[list[Tenant], list[TenantResult], list[Payment]]:
    vandaag = date.today()
    start_van_de_maand = vandaag.replace(day=1)
    # Sommige huurders betalen ruim vooruit (soms al vanaf de 20e voor de maand
    # erna) - zoek daarom ook een stuk voor de 1e, zodat die betalingen niet
    # gemist worden.
    zoek_vanaf = start_van_de_maand - timedelta(days=config.vooruitbetaling_dagen)

    logger.info("[%s] Kamers ophalen uit Google Sheet...", pand.slug)
    sheet = SheetClient(config, pand)
    tenants = sheet.get_tenants()
    logger.info("[%s] %d kamers met huurder gevonden", pand.slug, len(tenants))

    logger.info("[%s] Betalingen ophalen via bunq sinds %s...", pand.slug, zoek_vanaf)
    bunq = BunqClient(config)
    payments = bunq.get_incoming_payments(pand, since=zoek_vanaf)
    logger.info("[%s] %d inkomende betalingen gevonden deze maand", pand.slug, len(payments))

    results, unmatched = match_tenants_to_payments(tenants, payments, config.bedrag_tolerantie)

    if not dry_run:
        sheet.write_results(results)
        sheet.upsert_history(results, vandaag.strftime("%Y-%m"))
        state.save(pand.slug, results, len(unmatched), config.state_dir)
        logger.info("[%s] Sheet en geschiedenis bijgewerkt.", pand.slug)

    return tenants, results, unmatched


def _voorgaande_maanden(vandaag: date, aantal: int) -> list[tuple[int, int]]:
    """Geeft `aantal` kalendermaanden vóór (dus exclusief) de maand van
    `vandaag` terug, oudste eerst. De huidige maand wordt bewust overgeslagen -
    die wordt al door run_check() bijgehouden (met de vooruitbetaling-marge)."""
    maanden = []
    jaar, maand = vandaag.year, vandaag.month
    for _ in range(aantal):
        maand -= 1
        if maand == 0:
            maand, jaar = 12, jaar - 1
        maanden.append((jaar, maand))
    maanden.reverse()
    return maanden


def _verdeel_over_maanden(
    verwacht_bedrag: Decimal,
    betalingen: list[Payment],
    maanden: list[tuple[int, int]],
    tolerantie: Decimal,
) -> dict[str, tuple[Decimal, Status, date | None]]:
    """Bepaalt per maand het ontvangen bedrag/status op basis van wat er ECHT
    in die kalendermaand is binnengekomen - met één gerichte uitzondering:
    als een maand niets ontvangen heeft én de eropvolgende maand ongeveer het
    dubbele bedrag ontving (een inhaalbetaling), telt dat als 'Betaald' voor
    allebei de maanden - de oudere met de datum van de inhaalbetaling als
    betaaldatum (dus zichtbaar dat het laat was), in plaats van de oudere
    maand als 'Nog niet ontvangen' en de nieuwere als 'Te veel ontvangen' te
    laten staan.

    Bewust GEEN cumulatieve verrekening over de hele periode: een
    huurverhoging halverwege de teruggezochte maanden zou dan het
    verwachte/ontvangen bedrag van alle latere maanden laten verschuiven en
    fout weergeven (de sheet houdt geen historische huurbedragen bij). Deze
    aanpak kijkt daarom alleen naar dit ene aangrenzende-maandenpatroon, dus
    andere maanden blijven onaangetast door wat er verderop gebeurt."""
    per_maand: dict[tuple[int, int], tuple[Decimal, date | None]] = {}
    for jaar, maand in maanden:
        maand_start = date(jaar, maand, 1)
        maand_eind = date(jaar, maand, calendar.monthrange(jaar, maand)[1])
        maand_betalingen = [p for p in betalingen if maand_start <= p.datum <= maand_eind]
        ontvangen = sum((p.bedrag for p in maand_betalingen), Decimal("0"))
        laatste_datum = max((p.datum for p in maand_betalingen), default=None)
        per_maand[(jaar, maand)] = (ontvangen, laatste_datum)

    resultaat: dict[str, tuple[Decimal, Status, date | None]] = {}
    overgeslagen: set[tuple[int, int]] = set()

    for i, sleutel in enumerate(maanden):
        if sleutel in overgeslagen:
            continue
        ontvangen, laatste_datum = per_maand[sleutel]
        maand_key = f"{sleutel[0]}-{sleutel[1]:02d}"

        if ontvangen <= tolerantie and i + 1 < len(maanden):
            volgende_sleutel = maanden[i + 1]
            volgende_ontvangen, volgende_datum = per_maand[volgende_sleutel]
            if volgende_ontvangen >= 2 * verwacht_bedrag - tolerantie:
                volgende_maand_key = f"{volgende_sleutel[0]}-{volgende_sleutel[1]:02d}"
                resultaat[maand_key] = (verwacht_bedrag, Status.BETAALD, volgende_datum)
                resultaat[volgende_maand_key] = (verwacht_bedrag, Status.BETAALD, volgende_datum)
                overgeslagen.add(volgende_sleutel)
                continue

        status = _bepaal_status(ontvangen, verwacht_bedrag, tolerantie)
        resultaat[maand_key] = (ontvangen, status, laatste_datum)

    return resultaat


def backfill_geschiedenis(
    config: Config, pand: Pand, aantal_maanden: int = 12, vandaag: date | None = None
) -> int:
    """Vult de betaalgeschiedenis (Historie-tabblad) met zoveel mogelijk
    maanden terug (standaard de 12 maanden vóór de huidige maand), in één
    keer op basis van de HUIDIGE huurderslijst uit de sheet. Dit werkt het
    beste voor kamers die al langer dezelfde huurder hebben - voor kamers die
    pas onlangs verhuurd zijn kan een oudere maand niets zinnigs opleveren,
    omdat de sheet geen historische huurders bijhoudt. Raakt de Huurders-tab
    (status/ontvangen/laatst gecontroleerd) niet aan, alleen de Historie-tab.
    Geeft het aantal bijgewerkte maanden terug."""
    vandaag = vandaag or date.today()
    maanden = _voorgaande_maanden(vandaag, aantal_maanden)
    if not maanden:
        return 0
    oudste_jaar, oudste_maand = maanden[0]
    zoek_vanaf = date(oudste_jaar, oudste_maand, 1)
    nieuwste_jaar, nieuwste_maand = maanden[-1]
    zoek_tot = date(nieuwste_jaar, nieuwste_maand, calendar.monthrange(nieuwste_jaar, nieuwste_maand)[1])

    logger.info("[%s] Geschiedenis aanvullen sinds %s...", pand.slug, zoek_vanaf)
    sheet = SheetClient(config, pand)
    verwijderd = sheet.dedupliceer_geschiedenis()
    if verwijderd:
        logger.info("[%s] %d dubbele historieregel(s) opgeschoond.", pand.slug, verwijderd)
    tenants = sheet.get_tenants()

    bunq = BunqClient(config)
    alle_betalingen = bunq.get_incoming_payments(pand, since=zoek_vanaf)
    # betalingen van de huidige maand (die run_check() al afhandelt) horen niet mee te tellen
    betalingen_in_venster = [p for p in alle_betalingen if p.datum <= zoek_tot]

    resultaten, _unmatched = match_tenants_to_payments(tenants, betalingen_in_venster, config.bedrag_tolerantie)

    per_maand: dict[str, list[TenantResult]] = {f"{j}-{m:02d}": [] for j, m in maanden}
    for resultaat in resultaten:
        verdeling = _verdeel_over_maanden(
            resultaat.tenant.verwacht_bedrag, resultaat.gematchte_betalingen, maanden, config.bedrag_tolerantie
        )
        for maand_key, (ontvangen, status, betaaldatum) in verdeling.items():
            gematchte_betalingen = (
                [Payment(
                    bedrag=ontvangen, valuta="EUR", tegenpartij_naam=resultaat.tenant.naam,
                    tegenpartij_iban=resultaat.tenant.iban, omschrijving="", datum=betaaldatum,
                )]
                if betaaldatum
                else []
            )
            per_maand[maand_key].append(
                TenantResult(
                    tenant=resultaat.tenant, ontvangen_bedrag=ontvangen, status=status,
                    gematchte_betalingen=gematchte_betalingen,
                )
            )

    for maand_key, tenant_resultaten in per_maand.items():
        sheet.upsert_history(tenant_resultaten, maand_key)

    logger.info("[%s] Geschiedenis aangevuld voor %d maand(en).", pand.slug, len(maanden))
    return len(maanden)
