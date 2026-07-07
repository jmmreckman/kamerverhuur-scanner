"""Datamodellen die door de sheet-, bunq- en matching-modules gedeeld worden."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum


class Status(str, Enum):
    BETAALD = "Betaald"
    TE_WEINIG = "Te weinig ontvangen"
    TE_VEEL = "Te veel ontvangen"
    NIET_ONTVANGEN = "Nog niet ontvangen"


@dataclass(frozen=True)
class Tenant:
    row_index: int  # rijnummer in de Google Sheet (voor terugschrijven)
    naam: str  # leeg = kamer staat leeg (geen huurder)
    kamer: str
    verwacht_bedrag: Decimal  # totale huur (kale huur + servicekosten) - dit moet binnenkomen
    iban: str | None = None
    zoekwoord: str | None = None
    kale_huurprijs: Decimal | None = None
    servicekosten: Decimal | None = None
    contract_einddatum: str | None = None  # vrije tekst: kan een datum zijn of "onbepaalde tijd"
    opmerking: str | None = None


@dataclass(frozen=True)
class Payment:
    bedrag: Decimal
    valuta: str
    tegenpartij_naam: str
    tegenpartij_iban: str | None
    omschrijving: str
    datum: date


@dataclass
class TenantResult:
    tenant: Tenant
    ontvangen_bedrag: Decimal
    status: Status
    gematchte_betalingen: list[Payment] = field(default_factory=list)


@dataclass(frozen=True)
class HistorieRegel:
    datum: date
    kamer: str
    huurder: str
    verwacht_bedrag: Decimal
    ontvangen_bedrag: Decimal
    status: Status


@dataclass(frozen=True)
class Pand:
    slug: str  # korte code in URL's, bv. "mahoniestraat"
    naam: str  # weergavenaam, bv. "Mahoniestraat 15"
    google_sheet_id: str
    google_sheet_worksheet: str
    history_worksheet: str
    google_drive_folder_id: str | None
    bunq_rekening_iban: str
