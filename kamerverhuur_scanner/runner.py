"""Voert een betaalcontrole uit voor één pand: sheet lezen, bunq-betalingen
ophalen, matchen, en (tenzij dry-run) de sheet + geschiedenis bijwerken en
het resultaat cachen voor de website."""
from __future__ import annotations

import calendar
import logging
from datetime import date, timedelta

from . import state
from .bunq_client import BunqClient
from .config import Config
from .matcher import match_tenants_to_payments
from .models import Pand, Payment, Tenant, TenantResult
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

    logger.info("[%s] Geschiedenis aanvullen sinds %s...", pand.slug, zoek_vanaf)
    sheet = SheetClient(config, pand)
    tenants = sheet.get_tenants()

    bunq = BunqClient(config)
    payments = bunq.get_incoming_payments(pand, since=zoek_vanaf)

    for jaar, maand in maanden:
        maand_start = date(jaar, maand, 1)
        laatste_dag = calendar.monthrange(jaar, maand)[1]
        maand_eind = date(jaar, maand, laatste_dag)
        maand_betalingen = [p for p in payments if maand_start <= p.datum <= maand_eind]
        resultaten, _unmatched = match_tenants_to_payments(tenants, maand_betalingen, config.bedrag_tolerantie)
        sheet.upsert_history(resultaten, f"{jaar}-{maand:02d}")

    logger.info("[%s] Geschiedenis aangevuld voor %d maand(en).", pand.slug, len(maanden))
    return len(maanden)
