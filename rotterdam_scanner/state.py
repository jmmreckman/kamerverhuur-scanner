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

    @property
    def prijs_per_m2(self) -> float | None:
        if self.prijs is None or not self.bag_oppervlakte:
            return None
        return self.prijs / self.bag_oppervlakte


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
            last_seen = datetime.fromisoformat(item.laatst_gezien).date()
            if (today - last_seen).days <= expiry_days:
                keep[object_id] = item
        self._listings = keep

    def dagen_bekend(self, object_id: str, today: date | None = None) -> int:
        today = today or date.today()
        item = self._listings[object_id]
        eerst = datetime.fromisoformat(item.eerst_gezien).date()
        return (today - eerst).days
