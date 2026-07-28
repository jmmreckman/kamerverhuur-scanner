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

Twee dingen die het meer op een echt mens laten lijken (i.p.v. detectie-omzeiling):
- Een "warme" sessie: eerst de homepage bezoeken (en een cookiebanner wegklikken,
  als die verschijnt) in plaats van in koude toestand meteen naar de zoekpagina te
  springen.
- Optioneel inloggen met een echt funda-account (FUNDA_EMAIL/FUNDA_WACHTWOORD in
  .env) vóór het bezoeken van de zoekresultaten - alleen als dat is ingesteld; zonder
  is het gewoon een anonieme (maar wel warme) sessie. De inlogpagina kan zonder live
  toegang niet geverifieerd worden, dus dit gebruikt bewust generieke selectors en
  geeft het best-effort op (met een duidelijke waarschuwing) als iets niet lukt -
  nooit de rest van de scan blokkeren op een mislukte login.

Bewust rustig tempo tussen meerdere zoekopdrachten (zie _haal_browser_zoekopdrachten_listings
in pipeline.py) - dit is bedoeld voor een handvol eigen zoekopdrachten, een paar keer
per dag, niet voor grootschalig/parallel ophalen."""
from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

from .funda_mail import FundaListing
from .handmatig import parse_funda_tekstdump

if TYPE_CHECKING:
    from .config import Config

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_PAGINA_TIMEOUT_MS = 30_000
# Even wachten na het laden geeft eventuele anti-bot-controle (die zichzelf na het
# uitvoeren van wat JavaScript herlaadt naar de echte pagina) de kans om af te ronden,
# net zoals een mens ook even zou wachten voor de pagina volledig toont.
_WACHTTIJD_NA_LADEN_MS = 4_000
_WACHTTIJD_OP_HOMEPAGE_MS = 3_000
_WACHTTIJD_NA_INLOGGEN_MS = 3_000

_FUNDA_HOMEPAGE = "https://www.funda.nl/"
_FUNDA_INLOGPAGINA = "https://www.funda.nl/mijn/inloggen/"
# Cookiebanner-knoppen wisselen weleens van tekst - een paar voor de hand liggende
# varianten proberen, en het gewoon opgeven als geen ervan verschijnt (banner kan al
# geaccepteerd zijn via een eerdere cookie, of niet getoond worden).
_COOKIE_KNOP_TEKSTEN = ("Accepteren", "Akkoord", "Alles accepteren", "Accept all")

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


def _accepteer_cookies_indien_aanwezig(page) -> None:
    for tekst in _COOKIE_KNOP_TEKSTEN:
        try:
            page.get_by_role("button", name=tekst).click(timeout=2000)
            return
        except Exception:  # noqa: BLE001 - gewoon de volgende tekst proberen
            continue


def _debug_map(config: "Config | None"):
    """Map voor debug-screenshots/HTML (zie _maak_debug_snapshot) - alleen
    beschikbaar als er een Config is (dus niet in de losse unit-tests). Zit in
    dezelfde, al bestaande data-map als state.json, die op de VPS als bind-mount
    (./data) rechtstreeks in te zien is - geen docker cp nodig."""
    if config is None:
        return None
    from pathlib import Path

    pad = Path(config.state_path).parent / "browser_debug"
    pad.mkdir(parents=True, exist_ok=True)
    return pad


def _maak_debug_snapshot(page, config: "Config | None", naam: str) -> None:
    """Legt vast wat de browser op dit moment daadwerkelijk ziet (screenshot +
    ruwe HTML, telkens overschreven onder dezelfde naam) - puur om te kunnen
    zien wat een geautomatiseerde poging wel/niet te zien krijgt, zonder daar
    zelf steeds live bij te kunnen kijken. Best-effort: mag nooit de rest laten
    stranden als het wegschrijven zelf al misgaat."""
    debug_map = _debug_map(config)
    if debug_map is None:
        return
    try:
        page.screenshot(path=str(debug_map / f"{naam}.png"), full_page=True)
        (debug_map / f"{naam}.html").write_text(page.content(), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _inloggen_indien_geconfigureerd(page, config: "Config | None") -> None:
    """Best-effort: probeert in te loggen als FUNDA_EMAIL/FUNDA_WACHTWOORD zijn
    ingesteld. De inlogpagina is niet live te verifiëren (wordt zelf ook
    geblokkeerd), dus dit gebruikt generieke selectors (op input-type, niet op
    specifieke CSS-classes die inmiddels anders kunnen zijn) en geeft het gewoon
    op - met een duidelijke logregel, nooit een crash - als iets niet lukt."""
    if config is None or not config.funda_email or not config.funda_wachtwoord:
        return
    try:
        page.goto(_FUNDA_INLOGPAGINA, timeout=_PAGINA_TIMEOUT_MS, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        _accepteer_cookies_indien_aanwezig(page)
        _maak_debug_snapshot(page, config, "inlogpagina")
        page.locator('input[type="email"], input[name*="email" i], input[type="text"]').first.fill(
            config.funda_email, timeout=5000
        )
        page.locator('input[type="password"]').first.fill(config.funda_wachtwoord, timeout=5000)
        page.locator('button[type="submit"], button:has-text("Inloggen")').first.click(timeout=5000)
        page.wait_for_timeout(_WACHTTIJD_NA_INLOGGEN_MS)
        _maak_debug_snapshot(page, config, "na_inloggen")
    except Exception as exc:  # noqa: BLE001 - best-effort, nooit de scan hierop laten stranden
        logger.warning("Inloggen op funda is niet gelukt (%s) - ga door zonder ingelogde sessie.", exc)


def _haal_paginatekst_op(url: str, config: "Config | None" = None) -> str:
    # Losse import: playwright (en de chromium-download) is een relatief zware
    # dependency, alleen nodig zodra dit pad daadwerkelijk gebruikt wordt.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=_USER_AGENT, locale="nl-NL")

            # "Warme" sessie i.p.v. in koude toestand meteen naar de zoekpagina
            # springen - eerst de homepage bezoeken, zoals een mens dat ook zou doen.
            page.goto(_FUNDA_HOMEPAGE, timeout=_PAGINA_TIMEOUT_MS, wait_until="domcontentloaded")
            page.wait_for_timeout(_WACHTTIJD_OP_HOMEPAGE_MS)
            _accepteer_cookies_indien_aanwezig(page)
            _maak_debug_snapshot(page, config, "homepage")

            _inloggen_indien_geconfigureerd(page, config)

            page.goto(url, timeout=_PAGINA_TIMEOUT_MS, wait_until="domcontentloaded")
            page.wait_for_timeout(_WACHTTIJD_NA_LADEN_MS)
            _maak_debug_snapshot(page, config, "zoekresultaten")
            return page.inner_text("body")
        finally:
            browser.close()


def haal_listings_op(
    url: str, vandaag: date | None = None, config: "Config | None" = None
) -> tuple[list[FundaListing], list[str]]:
    """Bezoekt `url` (een eigen funda-zoekopdracht, zie browser_zoekopdrachten.py) en
    herkent de woningen op de resultatenpagina. Geeft (listings, waarschuwingen) terug -
    crasht nooit; een storing bij deze ene zoekopdracht mag de rest van de dagelijkse
    scan niet laten mislukken (zie pipeline.py). `config` is optioneel - zonder wordt
    er niet ingelogd (alleen de "warme" sessie), zoals ook bij de handmatige "Testen"-
    knop waar geen Config-object beschikbaar hoeft te zijn."""
    try:
        tekst = _haal_paginatekst_op(url, config)
    except Exception as exc:  # noqa: BLE001 - nooit de hele scan laten crashen op 1 zoekopdracht
        return [], [f"Kon browser-zoekopdracht niet ophalen ({url}): {exc}"]

    if _lijkt_op_antibot_pagina(tekst):
        return [], [
            f"Funda gaf een anti-bot-controle terug voor zoekopdracht {url} i.p.v. de "
            "zoekresultaten - waarschijnlijk tijdelijk, probeer het bij de volgende "
            "controle opnieuw."
        ]

    return parse_funda_tekstdump(tekst, vandaag)
