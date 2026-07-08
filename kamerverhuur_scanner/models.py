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
    beschikbaar: bool = False  # staat deze kamer op de publieke aanbodpagina?
    advertentie_omschrijving: str | None = None
    advertentie_map_id: str | None = None  # Drive-map met foto's/video's voor de aanbodpagina
    email: str | None = None
    telefoonnummer: str | None = None


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
    """Eén regel betaalgeschiedenis - precies 1 per kamer per kalendermaand
    ("maand", formaat "jjjj-mm"). Wordt bij elke controle bijgewerkt in
    plaats van een nieuwe regel toe te voegen, zodat vaker controleren in
    dezelfde maand de betrouwbaarheidsscore niet vertekent."""
    maand: str
    kamer: str
    huurder: str
    verwacht_bedrag: Decimal
    ontvangen_bedrag: Decimal
    status: Status
    betaaldatum: date | None = None  # datum van de (laatste) betaling, None = nog niet ontvangen


@dataclass(frozen=True)
class Pand:
    slug: str  # korte code in URL's, bv. "mahoniestraat"
    naam: str  # weergavenaam, bv. "Mahoniestraat 15"
    google_sheet_id: str
    google_sheet_worksheet: str
    history_worksheet: str
    google_drive_folder_id: str | None
    bunq_rekening_iban: str
    aanmeldingen_worksheet: str = "Aanmeldingen"
    # Extra BCC-adressen die alleen voor dít pand meegaan bij herinnering/
    # ingebrekestelling-mails (bv. een mede-eigenaar van alleen dit pand) -
    # naast de adressen in EMAIL_BCC (.env), die voor alle panden gelden.
    extra_bcc: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Aanmelding:
    """Eén reactie op een kameraanbod, via het publieke aanmeldformulier."""
    naam: str
    email: str
    telefoon: str
    huidig_adres: str
    studie: str
    studentnummer: str
    gewenste_ingangsdatum: str
    gewenste_huurduur: str
    inkomstenbron: str
    inkomsten_bedrag: str
    borgsteller: str
    bezichtiging: str
    videobel_nummer: str
    bewijs_inschrijving_link: str
