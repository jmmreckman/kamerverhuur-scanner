"""Blijvend (append-only) archief van álle listings die de scanner ooit heeft gezien.

Waarom apart van StateStore: `StateStore.prune_expired` gooit woningen die ~30 dagen
niet meer in een alert/beschikbaarheidscheck langskwamen weg, zodat de live-kaart
schoon blijft. Maar voor terugzoeken ("stond dit adres de afgelopen 12 maanden te
koop?", of in de toekomst "welke woningen komen stééds terug op Funda?") wil je juist
*niets* kwijtraken. Dit archief bewaart daarom elke woning voor altijd: records worden
bijgewerkt (laatst_gezien/status/prijs/bronnen) maar NOOIT verwijderd.

Het archief wordt elke scan-run bijgewerkt vóórdat StateStore.prune_expired draait (zie
pipeline.py), dus elke woning wordt vastgelegd zolang hij nog in de live-state zit -
ruim binnen de 30-dagen-prune. Terugwerkende kracht is er niet: woningen die al vóór
de invoering van dit archief waren geprund, zijn niet meer te herstellen.

Zie ook CLAUDE.md: dit archief moet altijd bewaard en aangevuld blijven.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

ARCHIEF_BESTANDSNAAM = "listings_archief.json"


def archief_pad_voor(state_path: Path) -> Path:
    """Het archief staat naast state.json in dezelfde data-map (gedeeld volume tussen
    de scanner die schrijft en de kansen-app die leest)."""
    return Path(state_path).parent / ARCHIEF_BESTANDSNAAM


def normaliseer_adres(weergavenaam: str) -> str:
    """Genormaliseerde sleutel om een PDOK-weergavenaam te matchen (lowercase,
    witruimte samengevouwen). Zowel de listings als de opkoop-scan halen hun adres
    uit PDOK, dus dezelfde schrijfwijze -> directe match."""
    return re.sub(r"\s+", " ", (weergavenaam or "").strip().lower())


@dataclass
class ArchiefRecord:
    object_id: str
    weergavenaam: str
    adres_genormaliseerd: str
    eerst_gezien: str          # ISO-datum (vroegst bekende)
    laatst_gezien: str         # ISO-datum (laatst in een alert gezien)
    laatste_status: str        # "actief" | "afgevallen" | "onbekend_adres"
    stad: str = "rotterdam"
    straatnaam: str | None = None
    huisnummer: str | None = None
    wijknaam: str | None = None
    lat: float | None = None
    lon: float | None = None
    prijs: int | None = None
    url: str | None = None
    bronnen: list[str] = field(default_factory=list)
    laatst_beschikbaar: str | None = None   # laatst door de beschikbaarheidscheck "te koop" gezien
    keer_bijgewerkt: int = 1                 # ruwe frequentie: hoe vaak een run dit record raakte
    voor_het_eerst_gearchiveerd: str | None = None

    def laatste_peildatum(self) -> str:
        """De meest recente datum waarop we deze woning 'te koop' wisten: de
        beschikbaarheidscheck is actueler dan laatst_gezien, dus die wint."""
        return self.laatst_beschikbaar or self.laatst_gezien


class ListingArchief:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, ArchiefRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        geldige_velden = set(ArchiefRecord.__dataclass_fields__)
        for object_id, item in raw.get("records", {}).items():
            # Tolerant laden: onbekende velden negeren zodat een nieuwer/ouder
            # bestandsformaat het laden niet laat crashen.
            schoon = {k: v for k, v in item.items() if k in geldige_velden}
            self._records[object_id] = ArchiefRecord(**schoon)

    def save(self) -> None:
        payload = {"records": {oid: asdict(r) for oid, r in self._records.items()}}
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def all(self) -> list[ArchiefRecord]:
        return list(self._records.values())

    def __len__(self) -> int:
        return len(self._records)

    def vul_aan(self, listings, today: date | None = None) -> None:
        """Werk het archief bij met de huidige listings. Nieuwe woningen worden
        toegevoegd; bestaande worden bijgewerkt (ruimste eerst/laatst-gezien-bereik,
        laatste status/prijs, union van bronnen). Er wordt NOOIT iets verwijderd."""
        vandaag = (today or date.today()).isoformat()
        for item in listings:
            oid = item.object_id
            bestaand = self._records.get(oid)
            if bestaand is None:
                self._records[oid] = ArchiefRecord(
                    object_id=oid,
                    weergavenaam=item.weergavenaam,
                    adres_genormaliseerd=normaliseer_adres(item.weergavenaam),
                    eerst_gezien=item.eerst_gezien,
                    laatst_gezien=item.laatst_gezien,
                    laatste_status=item.status,
                    stad=getattr(item, "stad", "rotterdam") or "rotterdam",
                    straatnaam=getattr(item, "straatnaam", None),
                    huisnummer=getattr(item, "huisnummer", None),
                    wijknaam=getattr(item, "wijknaam", None),
                    lat=getattr(item, "lat", None),
                    lon=getattr(item, "lon", None),
                    prijs=getattr(item, "prijs", None),
                    url=getattr(item, "url", None),
                    bronnen=list(getattr(item, "bronnen", []) or []),
                    laatst_beschikbaar=getattr(item, "laatst_beschikbaar", None),
                    keer_bijgewerkt=1,
                    voor_het_eerst_gearchiveerd=vandaag,
                )
                continue

            if item.weergavenaam:
                bestaand.weergavenaam = item.weergavenaam
                bestaand.adres_genormaliseerd = normaliseer_adres(item.weergavenaam)
            bestaand.eerst_gezien = min(bestaand.eerst_gezien, item.eerst_gezien)
            bestaand.laatst_gezien = max(bestaand.laatst_gezien, item.laatst_gezien)
            bestaand.laatste_status = item.status
            if getattr(item, "prijs", None) is not None:
                bestaand.prijs = item.prijs
            if getattr(item, "wijknaam", None):
                bestaand.wijknaam = item.wijknaam
            beschikbaar = getattr(item, "laatst_beschikbaar", None)
            if beschikbaar and (not bestaand.laatst_beschikbaar or beschikbaar > bestaand.laatst_beschikbaar):
                bestaand.laatst_beschikbaar = beschikbaar
            for bron in getattr(item, "bronnen", []) or []:
                if bron not in bestaand.bronnen:
                    bestaand.bronnen.append(bron)
            bestaand.keer_bijgewerkt += 1

    def index_op_adres(self) -> dict[str, ArchiefRecord]:
        """{genormaliseerd adres -> record} om snel op adres te matchen (één keer
        opbouwen, dan per adres O(1) opzoeken)."""
        return {r.adres_genormaliseerd: r for r in self._records.values()}

    def te_koop_geweest_sinds(self, weergavenaam: str, grens_datum_iso: str) -> ArchiefRecord | None:
        """Record als dit adres op/na grens_datum_iso nog 'te koop' (gezien) was,
        anders None. Handig voor een losse lookup; voor veel adressen achter elkaar is
        index_op_adres() zuiniger."""
        rec = self.index_op_adres().get(normaliseer_adres(weergavenaam))
        if rec is None:
            return None
        return rec if rec.laatste_peildatum() >= grens_datum_iso else None
