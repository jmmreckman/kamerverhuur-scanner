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
    # Onderstaande velden zijn puur voor het invullen van het huurcontract
    # (zie contract_templates/huurovereenkomst_voorbeeld.html) - vrije tekst,
    # want dit zijn geen bedragen/datums die de site zelf hoeft te berekenen.
    geboortedatum: str | None = None
    geboorteplaats: str | None = None  # bv. "Tatabánya, Hungary"
    studentnummer: str | None = None
    studierichting: str | None = None
    borgsteller_naam: str | None = None
    borgsteller_relatie: str | None = None  # bv. "Father"
    contract_startdatum: str | None = None
    # Waarborgsom die bij de instapmaand betaald is (naast de eerste
    # huur/pro-rata huur) - gebruikt door backfill_geschiedenis()/run_check()
    # om te voorkomen dat de instapmaand als "te veel ontvangen" verschijnt.
    borg_bedrag: Decimal | None = None


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
class Verhuurder:
    """Eén verhuurder/eigenaar zoals genoemd in het huurcontract."""
    naam: str
    adres: str = ""


@dataclass(frozen=True)
class VertrokkenHuurder:
    """Momentopname van een huurder die een kamer heeft verlaten (bv. omdat er
    een nieuwe huurder voor die kamer is ingevoerd) - blijft nog een tijdje
    zichtbaar (grijs/gearchiveerd) op de Huurders-pagina, zodat je nog bij
    hun contactgegevens kunt als er nog iets afgehandeld moet worden."""
    kamer: str
    naam: str
    email: str | None
    telefoonnummer: str | None
    contract_einddatum: str | None
    vertrokken_op: date  # moment waarop deze huurder als 'vertrokken' is gearchiveerd


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
    vertrokken_worksheet: str = "Vertrokken"
    # Extra BCC-adressen die alleen voor dít pand meegaan bij herinnering/
    # ingebrekestelling-mails (bv. een mede-eigenaar van alleen dit pand) -
    # naast de adressen in EMAIL_BCC (.env), die voor alle panden gelden.
    extra_bcc: list[str] = field(default_factory=list)
    # Onderstaande velden zijn puur voor het invullen van het huurcontract
    # (zie contract_templates/huurovereenkomst_voorbeeld.html).
    postcode: str = ""
    plaats: str = ""
    verhuurders: list[Verhuurder] = field(default_factory=list)
    rekeninghouder_naam: str = ""  # naam op de bankrekening waarop de huur binnenkomt
    gedeelde_ruimtes: str = ""  # bv. "keuken, badkamer, woonkamer, tuin"
    bijzondere_bepalingen: str = ""  # huisregels/extra bepalingen, vrije tekst
    gemeente_meldpunt: str = ""  # meldpunt ongewenst verhuurgedrag van de gemeente
    # Bepaalt of de contract-/ondertekenmails de Bold digitale sleutel noemen
    # (zie webapp/contracts.py: bouw_concept_email() en
    # webapp/ondertekenen.py: bouw_betaal_en_tekenmail()) - niet elk pand
    # heeft een Bold slim slot.
    heeft_bold_slot: bool = True


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
    borgsteller_naam: str = ""
    borgsteller_relatie: str = ""
    borgsteller_email: str = ""
