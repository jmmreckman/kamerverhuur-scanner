from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path


@dataclass
class ListingState:
    object_id: str
    url: str
    weergavenaam: str
    eerst_gezien: str  # ISO-datum
    laatst_gezien: str  # ISO-datum
    status: str  # "actief" | "afgevallen" | "onbekend_adres"
    straatnaam: str | None = None
    huisnummer: str | None = None
    wijknaam: str | None = None
    lat: float | None = None
    lon: float | None = None
    afvalreden: str | None = None
    woz_check_nodig: bool = False
    woz_check_url: str | None = None
    opmerking: str | None = None
    prijs: int | None = None
    bag_oppervlakte: int | None = None
    oppervlakte_advertentie: int | None = None
    huurprijsopslag_signalen: list[str] = field(default_factory=list)
    opslag_percentage: float = 0.0
    aantal_kamers_mogelijk: int | None = None
    winst_pm_pp: float | None = None
    eigen_inleg_pp: float | None = None
    # Totale eigen inleg vóór de ophoging (= totale_zelf_in_te_leggen uit
    # investering.py, het "schakelgeld" dat je bij aankoop nodig hebt vóór de
    # hertaxatie/ophoging) - investeerder-onafhankelijk (niet gedeeld door het
    # aantal investeerders). winst_pm_pp/eigen_inleg_pp staan wél al gedeeld door
    # investering.AANTAL_INVESTEERDERS; de kaart-website deelt op basis hiervan
    # zelf om naar 1/2/3 investeerders. None voor woningen die nog van vóór dit
    # veld dateren (wordt bij de volgende scan/backfill ingevuld).
    schakelgeld_totaal: float | None = None
    # Legacy: hoorde bij de inmiddels verwijderde Apify-integratie
    # (pipeline.run_apify_volledig(), zie git-geschiedenis) - niet meer
    # geschreven of gelezen. Blijft hier staan zodat bestaande state.json-
    # bestanden met dit veld gewoon blijven laden (ListingState(**item) zou
    # anders crashen op een onbekend veld).
    weken_gemist_in_volledige_scan: int = 0
    # Gezet zodra een gebruiker deze woning zelf verwijderd heeft (via de
    # "Verwijderen"-link in het dagrapport, of het kruisje op
    # kansen.steenhub.nl) - i.p.v. een automatische afvaller (nulquotum,
    # 50-meter, opkoopbescherming). Zorgt dat de woning nooit vanzelf
    # opnieuw "actief" wordt zolang dit aan staat (zie pipeline.py), ook al
    # blijft hij nog gewoon in het Funda-aanbod staan. afvalreden bevat de
    # (evt. door de gebruiker zelf opgegeven) reden.
    handmatig_verwijderd: bool = False
    # Gezet zodra de gebruiker het aantal kamers zelf heeft aangepast op de
    # kaart-website (de 18m2-vuistregel klopt in de praktijk niet altijd, bv. bij
    # een ongunstige plattegrond). Zolang dit aan staat, laat _backvul_investeringscijfers
    # (pipeline.py) aantal_kamers_mogelijk met rust i.p.v. het te overschrijven met de
    # automatisch berekende waarde - winst_pm_pp/eigen_inleg_pp blijven wel meerekenen
    # met dit handmatige aantal.
    aantal_kamers_handmatig: bool = False
    # Welke stad/gemeente en dus welke set checks op deze woning is toegepast:
    # "rotterdam" (nulquotum/50m/opkoopbescherming) of "den_haag" (toegestane
    # Leefbaarometer-wijk + capaciteit, zie rotterdam_scanner/den_haag.py).
    # Default "rotterdam" zodat bestaande state.json-woningen ongewijzigd blijven.
    stad: str = "rotterdam"
    # Informatieve punten (niet automatisch hard te controleren) die bij de woning
    # horen - voor Den Haag: geluidsisolatie, brandveiligheid, pand-/wijk-quotum,
    # MSW, WOZ-geschrapt. Rotterdam laat dit leeg (gebruikt huurprijsopslag_signalen).
    check_signalen: list[str] = field(default_factory=list)
    # Door de gebruiker (op de rekentool-pagina) aangepaste investeringsuitgangspunten
    # voor déze woning - een dict met de velden van investering.RekenUitgangspunten
    # (percentages als fractie, bv. 0.08). None = nog nooit iets aangepast, dan gelden
    # de standaardaannames + voorgevulde koopsom/aantal kamers. Wordt automatisch
    # opgeslagen zodra de gebruiker iets wijzigt (zie kansen_site/app.py).
    berekening: dict | None = None
    # Door de gebruiker als favoriet gemarkeerd (sterretje op kansen.steenhub.nl).
    # Alleen favorieten worden actief gemonitord op nieuwe kamerverhuurvergunningen
    # binnen 50 m (zie rotterdam_scanner/bekendmakingen.py) - die officiële
    # bekendmakingen lopen vóór op de gemeentekaart die gis.py raadpleegt. Een
    # favoriet blijft gemonitord én zichtbaar op de kaart, ook als de woning
    # inmiddels van Funda is verdwenen ("afgevallen").
    favoriet: bool = False
    # Nieuwe kamerverhuurvergunningen die binnen 50 m van deze (favoriete) woning
    # zijn afgegeven, gevonden in de officiële bekendmakingen. Elke waarschuwing is
    # een dict: publicatie_id, titel, datum (ISO), url, adres, afstand_m. Wordt
    # aangevuld door de dagelijkse check; per publicatie-id maar één keer opgeslagen
    # (en dus maar één keer gemaild), zie bekendmakingen.controleer_favorieten.
    bekendmaking_waarschuwingen: list[dict] = field(default_factory=list)
    # Via welke bron(nen) deze woning ooit is binnengekomen: "funda" (eigen
    # Funda-alertmails) en/of "nvm" (makelaars-/Move.nl-mails). Accumuleert over de
    # tijd, zodat op kansen.steenhub.nl te zien is hoeveel woningen elk kanaal levert,
    # hoeveel overlappen en hoeveel maar via één van de twee binnenkomen (bron-tracking
    # om dekkingsgaten op te sporen). Leeg = van vóór deze functie (telt als onbekend).
    bronnen: list[str] = field(default_factory=list)

    @property
    def primaire_oppervlakte(self) -> int | None:
        """De advertentie-m2 is betrouwbaarder dan de BAG-m2 (BAG geeft soms een
        veel hoger getal, bv. bij een pand dat ooit is samengevoegd/gesplitst
        zonder dat de BAG-registratie is bijgewerkt) en is daarom leidend voor
        kamers/investeringsberekening/weergave. BAG-m2 is alleen nog fallback
        als de advertentie geen oppervlakte vermeldde, en staat verder puur
        ter info."""
        return self.oppervlakte_advertentie or self.bag_oppervlakte

    @property
    def prijs_per_m2(self) -> float | None:
        if self.prijs is None or not self.primaire_oppervlakte:
            return None
        return self.prijs / self.primaire_oppervlakte


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._listings: dict[str, ListingState] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        for object_id, item in raw.get("listings", {}).items():
            self._listings[object_id] = ListingState(**item)

    def save(self) -> None:
        payload = {"listings": {oid: asdict(item) for oid, item in self._listings.items()}}
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def get(self, object_id: str) -> ListingState | None:
        return self._listings.get(object_id)

    def upsert(self, listing: ListingState) -> None:
        existing = self._listings.get(listing.object_id)
        if existing is not None:
            listing.eerst_gezien = existing.eerst_gezien
        self._listings[listing.object_id] = listing

    def all(self) -> list[ListingState]:
        return list(self._listings.values())

    def prune_expired(self, expiry_days: int, today: date | None = None) -> None:
        today = today or date.today()
        keep: dict[str, ListingState] = {}
        for object_id, item in self._listings.items():
            # Een favoriet blijft altijd bewaard, ook als de woning al lang niet
            # meer in een Funda-alert is langsgekomen (laatst_gezien loopt niet mee
            # zolang een woning ongewijzigd te koop blijft). Zo verdwijnt een
            # handmatig gemarkeerde favoriet nooit vanzelf van de kaart - conform
            # de belofte bij het favoriet-veld in ListingState.
            if item.favoriet:
                keep[object_id] = item
                continue
            last_seen = datetime.fromisoformat(item.laatst_gezien).date()
            if (today - last_seen).days <= expiry_days:
                keep[object_id] = item
        self._listings = keep

    def dagen_bekend(self, object_id: str, today: date | None = None) -> int:
        today = today or date.today()
        item = self._listings[object_id]
        eerst = datetime.fromisoformat(item.eerst_gezien).date()
        return (today - eerst).days


def bron_statistieken(items: list[ListingState]) -> dict:
    """Telling per bron over de woningen met een bekende bron, voor de Broninfo-
    sectie op kansen.steenhub.nl. Laat over de tijd zien hoeveel woningen elk
    kanaal (Funda / NVM) levert, hoeveel overlappen en hoeveel maar via één van de
    twee binnenkwamen - zo zie je of je via een van beide wegen structureel iets
    mist. 'onbekende_bron' zijn woningen van vóór de bron-tracking."""
    met_bron = [i for i in items if i.bronnen]
    aantal_funda = sum(1 for i in met_bron if "funda" in i.bronnen)
    aantal_nvm = sum(1 for i in met_bron if "nvm" in i.bronnen)
    aantal_beide = sum(1 for i in met_bron if "funda" in i.bronnen and "nvm" in i.bronnen)
    return {
        "totaal": len(met_bron),
        "funda": aantal_funda,
        "nvm": aantal_nvm,
        "beide": aantal_beide,
        "alleen_funda": aantal_funda - aantal_beide,
        "alleen_nvm": aantal_nvm - aantal_beide,
        "onbekende_bron": sum(1 for i in items if not i.bronnen),
    }
