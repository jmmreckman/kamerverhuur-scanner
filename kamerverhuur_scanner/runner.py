"""Voert een betaalcontrole uit: sheet lezen, bunq-betalingen ophalen, matchen,
en (tenzij dry-run) de sheet + geschiedenis bijwerken en het resultaat cachen
voor de website."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from . import state
from .bunq_client import BunqClient
from .config import Config
from .matcher import match_tenants_to_payments
from .models import Payment, Tenant, TenantResult
from .sheet_client import SheetClient

logger = logging.getLogger(__name__)


def run_check(config: Config, dry_run: bool = False) -> tuple[list[Tenant], list[TenantResult], list[Payment]]:
    vandaag = date.today()
    start_van_de_maand = vandaag.replace(day=1)
    # Sommige huurders betalen ruim vooruit (soms al vanaf de 20e voor de maand
    # erna) - zoek daarom ook een stuk voor de 1e, zodat die betalingen niet
    # gemist worden.
    zoek_vanaf = start_van_de_maand - timedelta(days=config.vooruitbetaling_dagen)

    logger.info("Kamers ophalen uit Google Sheet...")
    sheet = SheetClient(config)
    tenants = sheet.get_tenants()
    logger.info("%d kamers met huurder gevonden", len(tenants))

    logger.info("Betalingen ophalen via bunq sinds %s...", zoek_vanaf)
    bunq = BunqClient(config)
    payments = bunq.get_incoming_payments(since=zoek_vanaf)
    logger.info("%d inkomende betalingen gevonden deze maand", len(payments))

    results, unmatched = match_tenants_to_payments(tenants, payments, config.bedrag_tolerantie)

    if not dry_run:
        sheet.write_results(results)
        sheet.append_history(results, vandaag)
        state.save(results, len(unmatched))
        logger.info("Sheet en geschiedenis bijgewerkt.")

    return tenants, results, unmatched
