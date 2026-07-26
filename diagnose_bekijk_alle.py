"""Eenmalig diagnose-scriptje: zoekt in recente Funda-alertmails naar de
"Bekijk alle X woningen"-link, haalt de volledige (niet-afgekapte) href eruit
en probeert die vervolgens zelf direct op te halen - om te testen of dat
(net als losse woning-links, zie funda_mail.py) een 403 geeft bij niet-
browserverkeer, of dat de pagina wél gewoon bruikbaar is. Wijzigt niets,
stuurt geen mail - alleen uitlezen, ophalen en printen.

Gebruik: docker compose exec fundazoeker python3 diagnose_bekijk_alle.py
"""
from __future__ import annotations

import email
import imaplib
import re
from datetime import datetime, timedelta

import requests

from rotterdam_scanner.config import load_config
from rotterdam_scanner.funda_mail import _get_body

# Zelfde vriendelijke, browser-achtige headers als beschikbaarheid.py.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_TIMEOUT_SECONDEN = 15

# Zoekt terug vanaf "Bekijk alle" naar de dichtstbijzijnde openende <a ...
# href="...">, ongeacht hoeveel opmaak/attributen ertussen zitten.
_HREF_VOOR_BEKIJK_ALLE_RE = re.compile(
    r'<a\s+[^>]*?href="(?P<url>[^"]+)"[^>]*>(?:(?!</a>).)*?Bekijk alle',
    re.IGNORECASE | re.DOTALL,
)


def _test_fetch(url: str) -> str:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT_SECONDEN,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        return f"FOUT bij ophalen: {exc}"
    return (
        f"status {resp.status_code}, uiteindelijke URL: {resp.url}, "
        f"lengte body: {len(resp.text)} tekens"
    )


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

        geteste_urls: set[str] = set()

        for msg_id in message_ids:
            status, msg_data = imap.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data or msg_data[0] is None:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            subject = msg.get("Subject", "(geen onderwerp)")
            body = _get_body(msg)

            for match in _HREF_VOOR_BEKIJK_ALLE_RE.finditer(body):
                url = match.group("url")
                print("=" * 80)
                print(f"Mail: {subject}")
                print(f"Volledige link: {url}")
                if url in geteste_urls:
                    print("(al eerder getest in dit run, overgeslagen)")
                    continue
                geteste_urls.add(url)
                print(f"Test-ophalen: {_test_fetch(url)}")
                print()


if __name__ == "__main__":
    main()
