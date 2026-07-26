"""Eenmalig diagnose-scriptje: zoekt in recente Funda-alertmails naar de
"Bekijk alle X woningen"-link, haalt de volledige (niet-afgekapte) href eruit,
probeert die zelf direct op te halen (net als beschikbaarheid.py) en
analyseert vervolgens de opgehaalde pagina: staat er een titel/inlogmuur, en
zitten er daadwerkelijk woning-links (zelfde patroon als in de alertmail
zelf) in? Wijzigt niets, stuurt geen mail - alleen uitlezen, ophalen en
printen.

Gebruik: docker compose exec fundazoeker python3 diagnose_bekijk_alle.py
"""
from __future__ import annotations

import email
import imaplib
import re
from datetime import datetime, timedelta

import requests

from rotterdam_scanner.config import load_config
from rotterdam_scanner.funda_mail import _LISTING_LINK_RE, _get_body

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
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_LOGIN_SIGNALEN = ("inloggen", "log in", "wachtwoord", "welkom terug")


def _analyseer(html: str) -> str:
    titel_match = _TITLE_RE.search(html)
    titel = titel_match.group(1).strip() if titel_match else "(geen <title> gevonden)"
    laag = html.lower()
    login_muur = any(signaal in laag for signaal in _LOGIN_SIGNALEN)
    aantal_euro = laag.count("&#8364;") + laag.count("€")
    aantal_woning_links = len(_LISTING_LINK_RE.findall(html))
    return (
        f"titel: {titel!r} | mogelijke inlogmuur: {login_muur} | "
        f"'€'-tekens gevonden: {aantal_euro} | herkenbare woning-links: {aantal_woning_links}"
    )


def _test_fetch(url: str) -> tuple[str, str]:
    """Geeft (statusregel, analyse-of-foutmelding) terug."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT_SECONDEN,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        return f"FOUT bij ophalen: {exc}", ""

    statusregel = (
        f"status {resp.status_code}, uiteindelijke URL: {resp.url}, "
        f"lengte body: {len(resp.text)} tekens"
    )
    if resp.status_code != 200:
        return statusregel, ""
    return statusregel, _analyseer(resp.text)


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
                statusregel, analyse = _test_fetch(url)
                print(f"Test-ophalen: {statusregel}")
                if analyse:
                    print(f"Analyse van de opgehaalde pagina: {analyse}")
                print()


if __name__ == "__main__":
    main()
