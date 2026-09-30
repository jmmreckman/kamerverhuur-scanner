from __future__ import annotations

import logging
import sys
from datetime import date
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rotterdam_scanner import mail_voorkeuren, pipeline, report, rente_update
from rotterdam_scanner.config import Config
from rotterdam_scanner.config import load_config
from rotterdam_scanner.mailer import send_mail, send_report

LOG_DIR = Path(__file__).resolve().parent / "data"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(LOG_DIR / "scanner.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"),
    ],
)
logger = logging.getLogger("kamerverhuur_scanner")


def main() -> int:
    today = date.today()
    try:
        config = load_config()
    except RuntimeError as exc:
        logger.error(str(exc))
        return 1

    logger.info("Start dagelijkse scan voor %s", today.isoformat())
    result = pipeline.run(config, today=today)

    for fout in result.fouten:
        logger.warning(fout)

    ontvangers = mail_voorkeuren.ontvangers_voor(config, "dagelijkse_kansen")
    if not ontvangers:
        logger.info("Dagrapport: niemand heeft 'dagelijkse kansen' aan staan; niet verstuurd.")
    else:
        subject = f"Kamerverhuur-scanner Rotterdam — {len(result.alle_actief)} openstaande kansen ({today.strftime('%d-%m-%Y')})"
        html_body = report.build_html_report(result, today, config.gmail_address, config.listing_expiry_days)
        text_body = report.build_text_report(result, today, config.gmail_address)
        try:
            send_report(config, subject, html_body, text_body, recipients=ontvangers)
        except Exception:
            logger.exception("Versturen van het rapport is mislukt")
            return 1

    # Actuele Domivest-rente ophalen en (bij wijziging) de globale rente in het
    # rekenmodel bijwerken + een melding mailen. Fail-safe: mag de dagelijkse run
    # nooit laten falen, dus alle fouten worden hier opgevangen.
    try:
        _werk_domivest_rente_bij(config)
    except Exception:
        logger.exception("Bijwerken van de Domivest-rente is mislukt")

    logger.info(
        "Klaar: %d nieuw actief, %d nieuw afgevallen, %d onbekend adres, %d totaal open.",
        len(result.nieuw_actief),
        len(result.nieuw_afgevallen),
        len(result.nieuw_onbekend_adres),
        len(result.alle_actief),
    )
    return 0


def _pct(fractie: float) -> str:
    return f"{fractie * 100:.2f}".replace(".", ",") + "%"


def _werk_domivest_rente_bij(config: Config) -> None:
    """Leest de actuele Domivest-rente, noteert die in de rentegrafiek-historie (vaste
    cel 80% LTV / 5 jaar), trekt de globale rente in het rekenmodel gelijk, en mailt
    bij een wijziging een korte melding (van info@steenhub.nl, mits zo ingesteld via
    SMTP_FROM_EMAIL) naar de rapport-ontvanger(s)."""
    # Eenmalig de handmatig bijgehouden startpunten samenvoegen (idempotent).
    rente_update.backfill_historie(config)

    if not config.domivest_rente_auto:
        return

    # Eén keer ophalen, gedeeld door historie + model-update.
    tabel = rente_update.domivest_rente.haal_rentetabel(config.domivest_rente_url)
    if tabel is None:
        logger.warning("Domivest-rente kon niet worden opgehaald; historie/rente ongewijzigd")
        return
    rente_update.noteer_historie(config, tabel, date.today().isoformat())

    wijziging = rente_update.werk_rente_bij(config, tabel)
    if wijziging is None:
        return

    periode = wijziging.periode_jaren
    periode_tekst = "variabel" if periode == rente_update.domivest_rente.VARIABEL else f"{periode} jaar vast"
    ltv_tekst = f"t/m {round(wijziging.ltv * 100)}% LTV"
    oud, nieuw = _pct(wijziging.oude_rente), _pct(wijziging.nieuwe_rente)
    richting = "gestegen" if wijziging.nieuwe_rente > wijziging.oude_rente else "gedaald"

    logger.info("Domivest-rente %s: %s -> %s (%s, %s)", richting, oud, nieuw, ltv_tekst, periode_tekst)

    ontvangers = mail_voorkeuren.ontvangers_voor(config, "rente_updates")
    if not ontvangers:
        logger.info("Rentemelding: niemand heeft 'rentewijzigingen' aan staan; niet verstuurd.")
        return

    subject = f"Rente aangepast: {oud} -> {nieuw} (Domivest {ltv_tekst}, {periode_tekst})"
    text_body = (
        f"De verhuurhypotheekrente van Domivest is {richting}.\n\n"
        f"Van {oud} naar {nieuw} ({ltv_tekst}, {periode_tekst}).\n\n"
        f"De rente in het rekenmodel op kansen.steenhub.nl is automatisch bijgewerkt "
        f"naar {nieuw}. De BAR en je overige instellingen zijn ongewijzigd gebleven.\n\n"
        f"Bron: {config.domivest_rente_url}\n"
    )
    html_body = (
        f"<p>De verhuurhypotheekrente van Domivest is <strong>{richting}</strong>.</p>"
        f"<p>Van <strong>{oud}</strong> naar <strong>{nieuw}</strong> "
        f"({ltv_tekst}, {periode_tekst}).</p>"
        f"<p>De rente in het rekenmodel op kansen.steenhub.nl is automatisch bijgewerkt "
        f"naar <strong>{nieuw}</strong>. De BAR en je overige instellingen zijn "
        f"ongewijzigd gebleven.</p>"
        f'<p>Bron: <a href="{config.domivest_rente_url}">{config.domivest_rente_url}</a></p>'
    )
    try:
        send_mail(config, subject, html_body, text_body, recipients=ontvangers)
    except Exception:
        logger.exception("Versturen van de rente-melding is mislukt")


if __name__ == "__main__":
    sys.exit(main())
