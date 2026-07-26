"""Eenmalig diagnose-scriptje: zoekt in recente Funda-alertmails naar de tekst
"Bekijk alle" en print de ruwe HTML eromheen, zodat we kunnen zien of dat een
echte aanklikbare link is (en zo ja, waar die naartoe wijst) of alleen platte
tekst. Wijzigt niets, stuurt geen mail - alleen uitlezen en printen.

Gebruik: docker compose exec fundazoeker python3 diagnose_bekijk_alle.py
"""
from __future__ import annotations

import email
import imaplib
import re
from datetime import datetime, timedelta

from rotterdam_scanner.config import load_config
from rotterdam_scanner.funda_mail import _get_body

_VENSTER = 600


def main() -> None:
    config = load_config()
    with imaplib.IMAP4_SSL(config.imap_host) as imap:
        imap.login(config.gmail_address, config.gmail_app_password)
        imap.select(config.funda_mail_folder)

        since = (datetime.now() - timedelta(days=5)).strftime("%d-%b-%Y")
        status, data = imap.search(None, f'(SINCE "{since}" HEADER FROM "funda")')
        if status != "OK":
            print(f"IMAP-zoekopdracht mislukt: {status}")
            return

        message_ids = data[0].split()
        print(f"{len(message_ids)} Funda-mail(s) gevonden in de laatste 5 dagen.\n")

        for msg_id in message_ids:
            status, msg_data = imap.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data or msg_data[0] is None:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            subject = msg.get("Subject", "(geen onderwerp)")
            body = _get_body(msg)

            for match in re.finditer(r"Bekijk alle", body, re.IGNORECASE):
                start = max(0, match.start() - _VENSTER)
                eind = min(len(body), match.end() + 200)
                print("=" * 80)
                print(f"Mail: {subject}")
                print("-" * 80)
                print(body[start:eind])
                print()


if __name__ == "__main__":
    main()
