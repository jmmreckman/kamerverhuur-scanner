"""Haalt woningen op via een eigen (niet-Apify) Funda-zoekopdracht door de
zoekresultatenpagina met een gewone, onaangepaste Playwright/Chromium-browser te
bezoeken - net zoals een gebruiker dat zelf zou doen (geen scraping-dienst, geen
fingerprint-spoofing, geen proxy-rotatie of CAPTCHA-omzeiling).

De browser voert gewoon JavaScript uit en wacht even, zoals elke browser dat doet -
dat is ook alles wat nodig is om (indien aanwezig) funda's eigen anti-bot-controle
netjes te doorlopen. Vervolgens wordt de zichtbare paginatekst overgenomen (zoals bij
een handmatige kopieer/plak) en door dezelfde beproefde tekstdump-parser gehaald als
"Handmatig toevoegen" (rotterdam_scanner.handmatig.parse_funda_tekstdump, getest tegen
een echte kopieer-plak van 410 funda-resultaten) - geen aparte, kwetsbaardere set
CSS-selectors nodig.

Bewust rustig tempo tussen meerdere zoekopdrachten (zie haal_listings_van_zoekopdrachten
in pipeline.py) - dit is bedoeld voor een handvol eigen zoekopdrachten, een paar keer
per dag, niet voor grootschalig/parallel ophalen."""
from __future__ import annotations

from datetime import date

from .funda_mail import FundaListing
from .handmatig import parse_funda_tekstdump

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_PAGINA_TIMEOUT_MS = 30_000
# Even wachten na het laden geeft eventuele anti-bot-controle (die zichzelf na het
# uitvoeren van wat JavaScript herlaadt naar de echte pagina) de kans om af te ronden,
# net zoals een mens ook even zou wachten voor de pagina volledig toont.
_WACHTTIJD_NA_LADEN_MS = 4_000

# Tekst die funda's eigen anti-bot-tussenpagina laat zien i.p.v. de zoekresultaten -
# als dit voorkomt, zijn er geen "0 woningen gevonden" maar is de controle zelf
# vastgelopen; dat verdient een duidelijke waarschuwing i.p.v. stil "niets gevonden".
_ANTIBOT_SIGNALEN = (
    "bijna op de pagina die je zoekt",
    "controleren of je een mens bent",
    "even geduld",
)


class BrowserScraperError(RuntimeError):
    pass


def _lijkt_op_antibot_pagina(tekst: str) -> bool:
    lower = tekst.lower()
    return any(signaal in lower for signaal in _ANTIBOT_SIGNALEN)


def _haal_paginatekst_op(url: str) -> str:
    # Losse import: playwright (en de chromium-download) is een relatief zware
    # dependency, alleen nodig zodra dit pad daadwerkelijk gebruikt wordt.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=_USER_AGENT, locale="nl-NL")
            page.goto(url, timeout=_PAGINA_TIMEOUT_MS, wait_until="domcontentloaded")
            page.wait_for_timeout(_WACHTTIJD_NA_LADEN_MS)
            return page.inner_text("body")
        finally:
            browser.close()


def haal_listings_op(url: str, vandaag: date | None = None) -> tuple[list[FundaListing], list[str]]:
    """Bezoekt `url` (een eigen funda-zoekopdracht, zie browser_zoekopdrachten.py) en
    herkent de woningen op de resultatenpagina. Geeft (listings, waarschuwingen) terug -
    crasht nooit; een storing bij deze ene zoekopdracht mag de rest van de dagelijkse
    scan niet laten mislukken (zie pipeline.py)."""
    try:
        tekst = _haal_paginatekst_op(url)
    except Exception as exc:  # noqa: BLE001 - nooit de hele scan laten crashen op 1 zoekopdracht
        return [], [f"Kon browser-zoekopdracht niet ophalen ({url}): {exc}"]

    if _lijkt_op_antibot_pagina(tekst):
        return [], [
            f"Funda gaf een anti-bot-controle terug voor zoekopdracht {url} i.p.v. de "
            "zoekresultaten - waarschijnlijk tijdelijk, probeer het bij de volgende "
            "controle opnieuw."
        ]

    return parse_funda_tekstdump(tekst, vandaag)
