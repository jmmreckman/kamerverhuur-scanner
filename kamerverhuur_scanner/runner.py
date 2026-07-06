"""Voert een volledige huurcontrole uit: sheet lezen, bunq-betalingen ophalen,
matchen, sheet bijwerken en rapport mailen."""
from __future__ import annotations

import logging
from datetime import date

from .bunq_client import BunqClient
from .config import Config
from .mailer import send_report
from .matcher import match_tenants_to_payments
from .report import build_report
from .sheet_client import SheetClient

logger = logging.getLogger(__name__)


def run(config: Config, dry_run: bool = False) -> None:
    vandaag = date.today()
    start_van_de_maand = vandaag.replace(day=1)

    logger.info("Huurders ophalen uit Google Sheet...")
    sheet = SheetClient(config)
    tenants = sheet.get_tenants()
    logger.info("%d huurders gevonden", len(tenants))

    logger.info("Betalingen ophalen via bunq sinds %s...", start_van_de_maand)
    bunq = BunqClient(config)
    payments = bunq.get_incoming_payments(since=start_van_de_maand)
    logger.info("%d inkomende betalingen gevonden deze maand", len(payments))

    results, unmatched = match_tenants_to_payments(tenants, payments, config.bedrag_tolerantie)

    subject, html_body, text_body = build_report(results, unmatched, vandaag)

    if dry_run:
        print(f"Onderwerp: {subject}\n")
        print(text_body)
        logger.info("Dry-run: geen e-mail verstuurd en sheet niet bijgewerkt.")
        return

    sheet.write_results(results)
    send_report(config, subject, html_body, text_body)
    logger.info("Rapport verstuurd naar %s", config.email_to)
