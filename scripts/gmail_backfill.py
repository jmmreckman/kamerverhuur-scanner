#!/usr/bin/env python3
"""Eenmalige backfill: leest historische huurder-communicatie uit het
persoonlijke Gmail-account van de beheerder (IMAP) en zet die per huurder in de
communicatie-db, met een AI-samenvatting. Zo start het communicatiesysteem
meteen met de volledige voorgeschiedenis, zonder dat je jaren mail hoeft terug
te spitten.

Eenmalig draaien op de VPS (in de app-container), nadat je in de env hebt gezet:
    GMAIL_IMAP_USER=jmmreckman@gmail.com
    GMAIL_IMAP_PASSWORD=<een Gmail app-wachtwoord, 2FA aan>
    (optioneel) GMAIL_EIGEN_ADRES=jmmreckman@gmail.com   # bepaalt verzonden/ontvangen

Voorbeeld:
    docker compose exec app python3 -m scripts.gmail_backfill
    # of eerst veilig op 1 huurder testen:
    docker compose exec app python3 -m scripts.gmail_backfill ndevos1@hotmail.com

Na afloop kun je het Gmail app-wachtwoord weer intrekken; de doorlopende flow
(Fase 2) gebruikt info@/onderhoud@, niet je persoonlijke Gmail.

Alleen *huidige* huurders (uit de Huurders-sheet) worden meegenomen. De import
is herhaalbaar: al ingelezen berichten worden op Message-ID overgeslagen.
"""
from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

from kamerverhuur_scanner.config import Config, ConfigError
from kamerverhuur_scanner.properties import PropertiesError, load_properties
from kamerverhuur_scanner.sheet_client import SheetClient
from webapp import communicatie_ai, communicatie_db, mail_import

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("gmail_backfill")

_MAX_BERICHTEN_SAMENVATTING = 120


def main(argv: list[str]) -> int:
    load_dotenv()
    try:
        config = Config.load()
    except ConfigError as exc:
        logger.error("Configuratiefout: %s", exc)
        return 1

    alleen_adres = (argv[1].strip().lower() if len(argv) > 1 else "") or None
    eigen_adres = config.gmail_eigen_adres or config.gmail_imap_user or ""

    logger.info("Inloggen op Gmail (%s)...", config.gmail_imap_user)
    try:
        imap = mail_import.verbind_gmail(config)
    except mail_import.MailImportError as exc:
        logger.error("%s", exc)
        return 1
    logger.info("Ingelogd. Huurders doorlopen%s...",
                f" (alleen {alleen_adres})" if alleen_adres else "")

    db = communicatie_db.verbind(communicatie_db.pad(config.state_dir))
    try:
        panden = load_properties(config.properties_file)
    except PropertiesError as exc:
        logger.error("Pandenfout: %s", exc)
        return 1

    totaal_huurders, totaal_berichten = 0, 0
    for pand in panden:
        try:
            kamers = SheetClient(config, pand).get_kamers()
        except Exception as exc:  # noqa: BLE001 - één pand mag de rest niet stoppen
            logger.warning("  Pand %s overgeslagen (sheet lezen mislukt): %s", pand.naam, exc)
            continue
        for kamer in kamers:
            if not kamer.naam or not kamer.email:
                continue
            if alleen_adres and kamer.email.strip().lower() != alleen_adres:
                continue
            contact_id = communicatie_db.seed_contact(
                db, naam=kamer.naam, pand_slug=pand.slug, kamer=kamer.kamer,
                email=kamer.email, telefoon=kamer.telefoonnummer,
            )
            try:
                n = mail_import.importeer_voor_adres(
                    db, imap, contact_id=contact_id, pand_slug=pand.slug,
                    adres=kamer.email, eigen_adres=eigen_adres,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("  %s (%s): import mislukt: %s", kamer.naam, kamer.email, exc)
                continue
            totaal_huurders += 1
            totaal_berichten += n
            logger.info("  %s (%s): %d nieuw(e) bericht(en)", kamer.naam, kamer.email, n)
            _maak_samenvatting(config, db, contact_id, kamer.naam)

    try:
        imap.logout()
    except Exception:  # noqa: BLE001
        pass
    db.close()
    logger.info("Klaar. %d huurder(s) verwerkt, %d nieuw(e) bericht(en) toegevoegd.",
                totaal_huurders, totaal_berichten)
    return 0


def _maak_samenvatting(config: Config, db, contact_id: int, naam: str) -> None:
    berichten = communicatie_db.berichten_van_contact(db, contact_id)
    if not berichten:
        return
    try:
        samenvatting = communicatie_ai.genereer_samenvatting(
            config, huurder_naam=naam, berichten=berichten[-_MAX_BERICHTEN_SAMENVATTING:],
        )
        communicatie_db.zet_samenvatting(db, contact_id, samenvatting)
    except communicatie_ai.CommunicatieAIError as exc:
        logger.warning("  samenvatting voor %s overgeslagen: %s", naam, exc)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
