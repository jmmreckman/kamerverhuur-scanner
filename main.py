from __future__ import annotations

import logging
import sys
from datetime import date
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rotterdam_scanner import pipeline, report
from rotterdam_scanner.config import load_config
from rotterdam_scanner.mailer import send_report

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

    subject = f"Kamerverhuur-scanner Rotterdam — {len(result.alle_actief)} openstaande kansen ({today.strftime('%d-%m-%Y')})"
    html_body = report.build_html_report(result, today)
    text_body = report.build_text_report(result, today)

    try:
        send_report(config, subject, html_body, text_body)
    except Exception:
        logger.exception("Versturen van het rapport is mislukt")
        return 1

    logger.info(
        "Klaar: %d nieuw actief, %d nieuw afgevallen, %d onbekend adres, %d totaal open.",
        len(result.nieuw_actief),
        len(result.nieuw_afgevallen),
        len(result.nieuw_onbekend_adres),
        len(result.alle_actief),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
