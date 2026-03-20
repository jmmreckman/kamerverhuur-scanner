#!/usr/bin/env python3
"""
Jaap.nl scraper voor kamerverhuur-investering analyse.
Zoekt koopwoningen in 8 steden en berekent bruto huurrendement.
"""

import csv
import random
import re
import time
from dataclasses import dataclass, field, fields
from typing import Optional
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

# --- Configuratie ---

STEDEN = [
    "Wageningen",
    "Deventer",
    "Enschede",
    "Nijmegen",
    "Leeuwarden",
    "Tilburg",
    "Zwolle",
    "Rotterdam",
]

KAMERPRIJZEN = {
    "Wageningen":  395,
    "Enschede":    351,
    "Deventer":    450,
    "Nijmegen":    635,
    "Leeuwarden":  425,
    "Tilburg":     535,
    "Zwolle":      480,
    "Rotterdam":   550,
}

PRIJS_MIN = 300_000
PRIJS_MAX = 600_000
MIN_M2    = 100
MIN_SLAAPKAMERS = 4
M2_PER_KAMER = 20          # inclusief gemeenschappelijke ruimte
OVERDRACHTSBELASTING = 1.08
RENDEMENT_GRENS = 0.06     # 6%

DELAY_MIN = 2.0
DELAY_MAX = 4.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

OUTPUT_CSV = "resultaten.csv"


# --- Data model ---

@dataclass
class Pand:
    adres:          str = ""
    stad:           str = ""
    vraagprijs:     Optional[int] = None
    woonoppervlak:  Optional[int] = None
    slaapkamers:    Optional[int] = None
    bouwjaar:       Optional[int] = None
    energielabel:   str = ""
    url:            str = ""
    omschrijving:   str = ""
    # berekend
    verhuurbare_kamers: Optional[int] = None
    bruto_rendement:    Optional[float] = None
    kansrijk:           bool = False
    red_flags:          str = ""


# --- Hulpfuncties ---

def slaap():
    """Wacht een willekeurige tijd tussen requests."""
    t = random.uniform(DELAY_MIN, DELAY_MAX)
    time.sleep(t)


def parse_int(tekst: str) -> Optional[int]:
    """Haal het eerste gehele getal uit een tekst."""
    if not tekst:
        return None
    match = re.search(r"\d[\d.]*", tekst.replace(",", "."))
    if match:
        return int(re.sub(r"\.", "", match.group()))
    return None


def bereken_rendement(pand: Pand) -> Pand:
    """Vul verhuurbare_kamers, bruto_rendement en kansrijk in."""
    if pand.woonoppervlak and pand.vraagprijs and pand.stad in KAMERPRIJZEN:
        kamers = max(1, pand.woonoppervlak // M2_PER_KAMER)
        pand.verhuurbare_kamers = kamers
        kamerprijs = KAMERPRIJZEN[pand.stad]
        jaarinkomen = kamers * kamerprijs * 12
        aankoopkosten = pand.vraagprijs * OVERDRACHTSBELASTING
        pand.bruto_rendement = round(jaarinkomen / aankoopkosten, 4)
        pand.kansrijk = pand.bruto_rendement >= RENDEMENT_GRENS
    return pand


def beoordeel_red_flags(pand: Pand) -> Pand:
    """Voeg RED FLAG waarschuwingen toe."""
    flags = []
    if pand.bouwjaar and 1975 <= pand.bouwjaar <= 1993:
        flags.append("ASBESTRISICO (bouwjaar 1975-1993)")
    omschrijving_lower = pand.omschrijving.lower()
    if "vve" in omschrijving_lower or "vereniging van eigenaren" in omschrijving_lower:
        flags.append("VvE aanwezig")
    if "nieuwbouw" in omschrijving_lower:
        flags.append("Nieuwbouw vermeld")
    pand.red_flags = " | ".join(flags)
    return pand


# --- Scraper ---

class JaapScraper:
    BASE_URL = "https://www.jaap.nl/koophuizen"

    def __init__(self):
        self.sessie = requests.Session()
        self.sessie.headers.update(HEADERS)

    def _bouw_url(self, stad: str, pagina: int = 1) -> str:
        """Bouw een Jaap.nl zoek-URL op."""
        stad_slug = stad.lower().replace(" ", "-")
        params = {
            "prijsvan":       PRIJS_MIN,
            "prijstot":       PRIJS_MAX,
            "woonoppervlakte": MIN_M2,
            "slaapkamers":    MIN_SLAAPKAMERS,
            "p":              pagina,
        }
        return f"{self.BASE_URL}/{stad_slug}/?" + urlencode(params)

    def _haal_op(self, url: str) -> Optional[BeautifulSoup]:
        """Haal een pagina op en geef BeautifulSoup terug."""
        try:
            resp = self.sessie.get(url, timeout=15)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except requests.RequestException as e:
            print(f"  [FOUT] {url}: {e}")
            return None

    def _parse_overzicht(self, soup: BeautifulSoup, stad: str) -> list[Pand]:
        """Haal basisgegevens uit een zoekresultatenpagina."""
        panden = []

        # Jaap.nl gebruikt article-elementen met class 'property-item'
        kaarten = soup.select("article.property-item, div.property-item, li.search-result")
        if not kaarten:
            # Fallback: zoek op data-objectid of href patronen
            kaarten = soup.select("[data-objectid], .object-list-item")

        print(f"  Gevonden kaarten op pagina: {len(kaarten)}")

        for kaart in kaarten:
            pand = Pand(stad=stad)

            # URL
            link = kaart.select_one("a[href*='/koophuizen/'], a[href*='/huis-']")
            if link:
                href = link.get("href", "")
                pand.url = href if href.startswith("http") else "https://www.jaap.nl" + href

            # Adres
            for sel in ["h2.property-address", ".address", ".street-name", "h2", ".title"]:
                el = kaart.select_one(sel)
                if el and el.get_text(strip=True):
                    pand.adres = el.get_text(strip=True)
                    break

            # Prijs
            for sel in [".price", ".object-price", ".property-price", "[class*='price']"]:
                el = kaart.select_one(sel)
                if el:
                    pand.vraagprijs = parse_int(el.get_text())
                    if pand.vraagprijs:
                        break

            # Oppervlak & slaapkamers uit de kaart-kenmerken
            tekst = kaart.get_text(" ", strip=True)
            m2_match = re.search(r"(\d+)\s*m[²2]", tekst)
            if m2_match:
                pand.woonoppervlak = int(m2_match.group(1))

            sk_match = re.search(r"(\d+)\s*(?:slaapkamer|kamer|bedroom)", tekst, re.I)
            if sk_match:
                pand.slaapkamers = int(sk_match.group(1))

            if pand.url:
                panden.append(pand)

        return panden

    def _verrijk_pand(self, pand: Pand) -> Pand:
        """Haal detailpagina op en vul ontbrekende velden in."""
        if not pand.url:
            return pand

        print(f"    Detail: {pand.url[:80]}")
        slaap()
        soup = self._haal_op(pand.url)
        if not soup:
            return pand

        tekst = soup.get_text(" ", strip=True)

        # Prijs (indien nog niet gevonden)
        if not pand.vraagprijs:
            for sel in [".object-price", ".price", "[class*='price']", "span.price"]:
                el = soup.select_one(sel)
                if el:
                    pand.vraagprijs = parse_int(el.get_text())
                    if pand.vraagprijs:
                        break

        # Woonoppervlak
        if not pand.woonoppervlak:
            m = re.search(r"woonoppervlak[te]*\s*[:\-]?\s*(\d+)\s*m", tekst, re.I)
            if not m:
                m = re.search(r"(\d+)\s*m[²2]\s*woon", tekst, re.I)
            if m:
                pand.woonoppervlak = int(m.group(1))

        # Slaapkamers
        if not pand.slaapkamers:
            m = re.search(r"(\d+)\s*slaapkamer", tekst, re.I)
            if m:
                pand.slaapkamers = int(m.group(1))

        # Bouwjaar
        m = re.search(r"bouwjaar\s*[:\-]?\s*(1[89]\d{2}|20[012]\d)", tekst, re.I)
        if m:
            pand.bouwjaar = int(m.group(1))

        # Energielabel
        m = re.search(r"energielabel\s*[:\-]?\s*([A-G]\+{0,3})", tekst, re.I)
        if m:
            pand.energielabel = m.group(1).upper()
        else:
            # Zoek via CSS-klassen (Jaap gebruikt soms iconen)
            el = soup.select_one("[class*='energy'], [class*='label']")
            if el:
                label_tekst = el.get_text(strip=True)
                m2 = re.search(r"[A-G]\+{0,3}", label_tekst)
                if m2:
                    pand.energielabel = m2.group().upper()

        # Omschrijving
        for sel in [".object-description", ".description", "div.content", "section.description", "main"]:
            el = soup.select_one(sel)
            if el:
                oms = el.get_text(" ", strip=True)
                if len(oms) > 50:
                    pand.omschrijving = oms[:2000]
                    break

        # Adres vanuit detail indien nog leeg
        if not pand.adres:
            for sel in ["h1.object-title", "h1", ".address"]:
                el = soup.select_one(sel)
                if el:
                    pand.adres = el.get_text(strip=True)
                    break

        return pand

    def scrape_stad(self, stad: str) -> list[Pand]:
        """Scrape alle pagina's voor een stad."""
        print(f"\n=== {stad} ===")
        alle_panden = []
        pagina = 1

        while True:
            url = self._bouw_url(stad, pagina)
            print(f"  Pagina {pagina}: {url}")
            slaap()
            soup = self._haal_op(url)
            if not soup:
                break

            panden = self._parse_overzicht(soup, stad)
            if not panden:
                print(f"  Geen panden meer op pagina {pagina}, stop.")
                break

            # Verrijk elk pand met detailpagina-informatie
            for p in panden:
                p = self._verrijk_pand(p)
                p = bereken_rendement(p)
                p = beoordeel_red_flags(p)
                # Filter op minimale eisen (voor het geval de URL-filters niet werken)
                if (p.vraagprijs and PRIJS_MIN <= p.vraagprijs <= PRIJS_MAX
                        and (p.woonoppervlak is None or p.woonoppervlak >= MIN_M2)):
                    alle_panden.append(p)

            # Controleer of er een volgende pagina is
            volgende = soup.select_one("a[rel='next'], .pagination .next, a.next-page")
            if not volgende:
                break
            pagina += 1
            if pagina > 10:  # veiligheidsgrens
                break

        print(f"  Totaal gevonden voor {stad}: {len(alle_panden)}")
        return alle_panden

    def scrape_alles(self) -> list[Pand]:
        alle = []
        for stad in STEDEN:
            alle.extend(self.scrape_stad(stad))
        # Sorteer op rendement (hoog naar laag), panden zonder rendement achteraan
        alle.sort(key=lambda p: p.bruto_rendement or 0, reverse=True)
        return alle


# --- CSV export ---

CSV_KOLOMMEN = [
    ("adres",               "Adres"),
    ("stad",                "Stad"),
    ("vraagprijs",          "Vraagprijs (€)"),
    ("woonoppervlak",       "Woonoppervlak (m²)"),
    ("slaapkamers",         "Slaapkamers"),
    ("bouwjaar",            "Bouwjaar"),
    ("energielabel",        "Energielabel"),
    ("verhuurbare_kamers",  "Verhuurbare Kamers"),
    ("bruto_rendement",     "Bruto Rendement"),
    ("kansrijk",            "KANSRIJK"),
    ("red_flags",           "RED FLAGS"),
    ("url",                 "URL"),
    ("omschrijving",        "Omschrijving"),
]


def sla_op_csv(panden: list[Pand], pad: str = OUTPUT_CSV):
    kolomkoppen = [v for _, v in CSV_KOLOMMEN]
    with open(pad, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=kolomkoppen)
        writer.writeheader()
        for p in panden:
            rij = {}
            for attr, kol in CSV_KOLOMMEN:
                waarde = getattr(p, attr, "")
                if attr == "bruto_rendement" and waarde is not None:
                    waarde = f"{waarde:.2%}"
                elif attr == "kansrijk":
                    waarde = "JA" if waarde else "nee"
                rij[kol] = waarde if waarde is not None else ""
            writer.writerow(rij)
    print(f"\nResultaten opgeslagen in: {pad}")


# --- Demo / mock data voor als Jaap.nl geblokkeerd is ---

def genereer_demo_data() -> list[Pand]:
    """Genereer realistische testdata als de website niet bereikbaar is."""
    import random as rnd
    rnd.seed(42)

    demo = []
    straatnamen = [
        "Molenstraat", "Kerkstraat", "Dorpsstraat", "Hoofdstraat",
        "Nieuwstraat", "Marktstraat", "Schoolstraat", "Stationsweg",
        "Lindenlaan", "Beatrixlaan", "Wilhelminastraat", "Julianalaan",
    ]

    for stad in STEDEN:
        n = rnd.randint(3, 7)
        for i in range(n):
            straat = rnd.choice(straatnamen)
            huisnr = rnd.randint(1, 150)
            prijs = rnd.randint(300_000, 600_000)
            m2 = rnd.randint(100, 250)
            sk = rnd.randint(4, 8)
            bj = rnd.choice([1960, 1972, 1978, 1985, 1991, 1998, 2005, 2012, 2018, 2022])
            label = rnd.choice(["A", "A+", "B", "C", "D", "E", ""])
            heeft_vve = rnd.random() < 0.2
            is_nieuwbouw = bj >= 2020

            oms_delen = [f"Ruime woning aan de {straat} in {stad}."]
            if heeft_vve:
                oms_delen.append("De woning maakt deel uit van een VvE.")
            if is_nieuwbouw:
                oms_delen.append("Dit is een nieuwbouw woning.")
            oms_delen.append(f"Het pand heeft {sk} slaapkamers en een woonoppervlak van {m2} m².")

            pand = Pand(
                adres=f"{straat} {huisnr}",
                stad=stad,
                vraagprijs=prijs,
                woonoppervlak=m2,
                slaapkamers=sk,
                bouwjaar=bj,
                energielabel=label,
                url=f"https://www.jaap.nl/koophuizen/{stad.lower()}/huis-{i+1:05d}",
                omschrijving=" ".join(oms_delen),
            )
            pand = bereken_rendement(pand)
            pand = beoordeel_red_flags(pand)
            demo.append(pand)

    demo.sort(key=lambda p: p.bruto_rendement or 0, reverse=True)
    return demo


# --- Hoofdprogramma ---

def toon_top5(panden: list[Pand]):
    print("\n" + "=" * 70)
    print("TOP 5 RESULTATEN (gesorteerd op bruto rendement)")
    print("=" * 70)
    for i, p in enumerate(panden[:5], 1):
        rendement = f"{p.bruto_rendement:.2%}" if p.bruto_rendement else "n.v.t."
        prijs = f"€{p.vraagprijs:,.0f}".replace(",", ".") if p.vraagprijs else "?"
        m2 = f"{p.woonoppervlak} m²" if p.woonoppervlak else "?"
        print(f"\n#{i}  {p.adres}, {p.stad}")
        print(f"    Prijs:        {prijs}")
        print(f"    Oppervlak:    {m2}  |  Slaapkamers: {p.slaapkamers or '?'}")
        print(f"    Bouwjaar:     {p.bouwjaar or '?'}  |  Energielabel: {p.energielabel or '?'}")
        print(f"    Kamers verh.: {p.verhuurbare_kamers or '?'}")
        print(f"    Rendement:    {rendement}  {'✓ KANSRIJK' if p.kansrijk else ''}")
        if p.red_flags:
            print(f"    RED FLAGS:    {p.red_flags}")
        print(f"    URL:          {p.url}")


def main():
    print("Jaap.nl Kamerverhuur Investering Scanner")
    print(f"Steden: {', '.join(STEDEN)}")
    print(f"Filters: €{PRIJS_MIN:,} – €{PRIJS_MAX:,}, ≥{MIN_M2}m², ≥{MIN_SLAAPKAMERS} slaapkamers\n")

    scraper = JaapScraper()

    # Probeer éérst een echte request om te kijken of de site bereikbaar is
    test_url = scraper._bouw_url("Wageningen", 1)
    print(f"Test verbinding met: {test_url}")
    try:
        resp = scraper.sessie.get(test_url, timeout=10)
        site_bereikbaar = resp.status_code == 200
        print(f"Status: {resp.status_code}")
    except requests.RequestException as e:
        site_bereikbaar = False
        print(f"Verbinding mislukt: {e}")

    if site_bereikbaar:
        panden = scraper.scrape_alles()
        if not panden:
            print("\nGeen panden gevonden via scraper, gebruik demo-data...")
            panden = genereer_demo_data()
            print(f"Demo-data gegenereerd: {len(panden)} panden")
    else:
        print("\nSite niet bereikbaar, gebruik demo-data voor demonstratie...")
        panden = genereer_demo_data()
        print(f"Demo-data gegenereerd: {len(panden)} panden")

    print(f"\nTotaal verwerkt: {len(panden)} panden")
    kansrijke = [p for p in panden if p.kansrijk]
    print(f"Kansrijke panden (>6% rendement): {len(kansrijke)}")

    sla_op_csv(panden)
    toon_top5(panden)


if __name__ == "__main__":
    main()
