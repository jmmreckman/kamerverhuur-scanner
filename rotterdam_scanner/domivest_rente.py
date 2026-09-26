"""Leest de actuele verhuurhypotheekrente van Domivest (https://domivest.com/rente)
en zet 'm om naar een matrix rentevaste-periode x LTV-klasse. Wordt dagelijks
gebruikt om de globale rente in het rekenmodel actueel te houden (zie
rente_update.py). Alles is fail-safe: kan de pagina niet gelezen of begrepen
worden, dan geven we None terug en blijft de bestaande rente ongewijzigd.

De tabel op de pagina heeft als koppen "t/m 50% LTV" ... "t/m 80% LTV" en als
rijen "1 jaar", "3 Jaar", ... "10 Jaar" en "Variabel (3 maanden)". Geverifieerd
tegen de echte pagina (zie tests/test_domivest_rente.py met een opgeslagen
HTML-fragment).
"""
from __future__ import annotations

import html
import re

import requests

RENTE_URL = "https://domivest.com/rente"

# Domivest levert zonder browser-User-Agent soms geen bruikbare pagina; een
# normale UA lost dat af (net als bij rotterdam.nl in gis.py).
_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}

_TABLE_RE = re.compile(r"<table.*?</table>", re.IGNORECASE | re.DOTALL)
_ROW_RE = re.compile(r"<tr.*?</tr>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_PERCENT_RE = re.compile(r"(\d+)\s*,\s*(\d+)\s*%")
_LTV_RE = re.compile(r"(\d+)\s*%")
_JAAR_RE = re.compile(r"(\d+)\s*jaar", re.IGNORECASE)

# Periode-sleutel "variabel" voor de variabele rente-rij.
VARIABEL = "variabel"


def _celtekst(ruw: str) -> str:
    return html.unescape(_TAG_RE.sub("", ruw)).strip()


def _periode_sleutel(label: str):
    if "variabel" in label.lower():
        return VARIABEL
    match = _JAAR_RE.search(label)
    return int(match.group(1)) if match else None


def _percentage(cel: str) -> float | None:
    match = _PERCENT_RE.search(cel)
    if not match:
        return None
    return float(f"{match.group(1)}.{match.group(2)}") / 100


def parse_rentetabel(html_tekst: str) -> dict | None:
    """Zet de HTML om naar {periode: {ltv_procent_int: rente_fractie}}. periode is een
    int (aantal jaar) of de string VARIABEL. Geeft None bij een onbruikbare pagina."""
    tabellen = _TABLE_RE.findall(html_tekst)
    if not tabellen:
        return None
    rijen = _ROW_RE.findall(tabellen[0])
    if len(rijen) < 2:
        return None

    kop_cellen = [_celtekst(c) for c in _CELL_RE.findall(rijen[0])]
    # De eerste kolom is het periode-label ("Perioden"); de rest zijn LTV-klassen.
    ltv_kolommen = []
    for cel in kop_cellen[1:]:
        m = _LTV_RE.search(cel)
        if m:
            ltv_kolommen.append(int(m.group(1)))
    if not ltv_kolommen:
        return None

    tabel: dict = {}
    for rij in rijen[1:]:
        cellen = [_celtekst(c) for c in _CELL_RE.findall(rij)]
        if len(cellen) < 2:
            continue
        periode = _periode_sleutel(cellen[0])
        if periode is None:
            continue
        percentages = [_percentage(c) for c in cellen[1:]]
        rij_dict = {
            ltv: pct
            for ltv, pct in zip(ltv_kolommen, percentages)
            if pct is not None
        }
        if rij_dict:
            tabel[periode] = rij_dict

    return tabel or None


def haal_rentetabel(url: str = RENTE_URL, timeout: int = 30) -> dict | None:
    """Haalt de rentepagina op en parset 'm. Fail-safe: None bij netwerk-/parsefout."""
    try:
        resp = requests.get(url, headers=_HTTP_HEADERS, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    return parse_rentetabel(resp.text)


def rente_voor(tabel: dict, ltv_fractie: float, periode_jaren) -> float | None:
    """Kiest de rente voor een gegeven LTV (fractie, bv. 0.8) en rentevaste periode.
    De LTV-klasse is "t/m X% LTV", dus we pakken de kleinste kolom die de LTV nog
    dekt (>=), en anders de hoogste kolom. Geeft None als de periode ontbreekt of
    de waarde onwaarschijnlijk is (buiten 1%-20%)."""
    rij = tabel.get(periode_jaren)
    if not rij:
        return None
    ltv_procent = round(ltv_fractie * 100)
    passend = sorted(k for k in rij if k >= ltv_procent)
    kolom = passend[0] if passend else max(rij)
    rente = rij.get(kolom)
    if rente is None or not (0.01 <= rente <= 0.20):
        return None
    return rente


def actuele_rente(ltv_fractie: float, periode_jaren, url: str = RENTE_URL) -> float | None:
    """Gemak: haal de tabel op en geef direct de juiste rente-fractie terug (of None)."""
    tabel = haal_rentetabel(url)
    if tabel is None:
        return None
    return rente_voor(tabel, ltv_fractie, periode_jaren)
