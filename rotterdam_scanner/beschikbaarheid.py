"""Checkt of een al bekende Funda-woning nog beschikbaar is, door gewoon de
eigen advertentiepagina rechtstreeks op te halen (geen betaalde scraper/
zoek-actor nodig - dat bleek in de praktijk onbetrouwbaar, zowel bij het
missen van hele zoekgebieden als bij het missen van losse woningen binnen
een werkend gebied). Funda's paginatitel is een consistent en simpel signaal:
"<type> te koop: <adres>" voor een actieve advertentie, "<type> verkocht:
<adres>" zodra hij verkocht is (geverifieerd tegen echte voorbeelden van
beide, juli 2026).

Geen bot-detectie-omzeiling ingebouwd (geen proxy, geen browser-emulatie) -
dit is bewust een gratis, best-effort aanpak: een enkele advertentiepagina
per dag per woning ophalen is een veel lichtere belasting dan het
doorzoeken van hele zoekresultatenpaginas, maar Funda kan dit op termijn
alsnog gaan blokkeren. controleer_beschikbaar() geeft dan None terug (i.p.v.
te crashen of ten onrechte "verkocht" te concluderen) zodat de aanroeper de
woning gewoon met rust laat."""
from __future__ import annotations

import re
import time

import requests

_TIMEOUT_SECONDEN = 15
# Beleefdheidspauze tussen aanvragen - honderden woningen per dag rechtstreeks
# opvragen zonder enige vertraging vergroot het risico op een blokkade.
_PAUZE_SECONDEN = 2.0
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def controleer_beschikbaar(url: str, pauzeer: bool = True) -> bool | None:
    """True = staat nog te koop, False = verkocht, None = kon niet vastgesteld
    worden (netwerkfout, blokkade, onherkende pagina - dus best-effort:
    de aanroeper laat de woning dan met rust in plaats van 'm te verwijderen)."""
    if pauzeer:
        time.sleep(_PAUZE_SECONDEN)
    try:
        resp = requests.get(
            url, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT_SECONDEN,
        )
    except requests.RequestException:
        return None

    if resp.status_code != 200:
        return None

    match = _TITLE_RE.search(resp.text)
    if not match:
        return None
    titel = match.group(1).lower()

    if "verkocht" in titel:
        return False
    if "te koop" in titel:
        return True
    return None
