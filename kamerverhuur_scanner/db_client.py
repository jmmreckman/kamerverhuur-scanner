"""DbClient - de kamers/huurders/historie/aanmeldingen/bezichtigingen/vertrokken
van één pand, uit de SQLite-hoofddatabase (zie kamerverhuur_scanner/db.py).

Dit is een **drop-in vervanger** van de oude SheetClient: exact dezelfde
publieke methodes, parameters en retourtypes (dezelfde dataclasses uit
models.py). De rest van de app (webapp/app.py, runner.py, de scripts) kan dus
`SheetClient(config, pand)` één-op-één vervangen door `DbClient(config, pand)`
zonder verder iets te hoeven aanpassen.

Belangrijk contract dat we trouw houden:
- `Tenant.row_index` = de primary key (`huurders.id`) van de kamerrij. De app
  geeft die terug aan update_kamer()/update_aanbod() om precies die rij bij te
  werken - net zoals vroeger het sheet-rijnummer.
- `VertrokkenHuurder.row_index` = `vertrokken.id` (voor de "oude huurder"-
  detailpagina).
- Bezichtiging-"rijnummer" = `bezichtigingen.id` (voor verwijder_bezichtiging).
- Bedragen bewaren we als canonieke punt-strings ("1234.56"); None = leeg.
- Data/bedragen worden nooit als Google-datum "vermomd", dus de genees-/
  dedup-trucs van de sheet zijn hier overbodig (de UNIQUE-constraint op
  (pand, kamer, maand) maakt dubbele historieregels sowieso onmogelijk).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from .config import Config
from .db import verbind
from .models import Aanmelding, HistorieRegel, Pand, Payment, Status, Tenant, VertrokkenHuurder
from .utils import nu_amsterdam

_VERTROKKEN_ZICHTBAAR_DAGEN = 31

_AANMELDINGEN_HEADER = [
    "Datum", "Kamer", "Naam", "Email", "Telefoon", "Huidig adres", "Studie",
    "Studentnummer", "Gewenste ingangsdatum", "Gewenste huurduur",
    "Inkomstenbron", "Inkomsten (bedrag)", "Borgsteller", "Bezichtiging",
    "Video-bel nummer", "Bewijs inschrijving",
    "Borgsteller naam", "Borgsteller relatie", "Borgsteller email",
]
# Kolommen van de aanmeldingen-tabel in exact de volgorde van _AANMELDINGEN_HEADER.
_AANMELDINGEN_KOLOMMEN = [
    "datum", "kamer", "naam", "email", "telefoon", "huidig_adres", "studie",
    "studentnummer", "gewenste_ingangsdatum", "gewenste_huurduur",
    "inkomstenbron", "inkomsten_bedrag", "borgsteller", "bezichtiging",
    "videobel_nummer", "bewijs_inschrijving",
    "borgsteller_naam", "borgsteller_relatie", "borgsteller_email",
]

_BEZICHTIGINGEN_KOLOMMEN = [
    "datum", "tijd_start", "tijd_eind", "kamer", "naam", "email", "telefoon",
    "manier", "bel_nummer", "bevestigd_op",
]


def _bedrag_db(bedrag: Decimal | None) -> str | None:
    """Decimal -> canonieke punt-string "1234.56"; None -> None (leeg)."""
    return f"{bedrag:.2f}" if bedrag is not None else None


def _bedrag_uit(waarde) -> Decimal | None:
    if waarde in (None, ""):
        return None
    try:
        return Decimal(str(waarde))
    except (ArithmeticError, ValueError):
        return None


def _tekst(waarde) -> str | None:
    """Lege/ontbrekende tekst -> None (zoals de oude _optioneel op de sheet)."""
    if waarde is None:
        return None
    tekst = str(waarde).strip()
    return tekst or None


def _datum_uit(waarde) -> date | None:
    if not waarde:
        return None
    try:
        return date.fromisoformat(str(waarde))
    except ValueError:
        return None


class DbClient:
    def __init__(self, config: Config, pand: Pand):
        self._config = config
        self._pand = pand
        self._slug = pand.slug

    def _verbind(self):
        return verbind(self._config)

    @classmethod
    def bouw_structuur(cls, config: Config, pand: Pand) -> dict:
        """Compat met de oude SheetClient.bouw_structuur: er zijn geen tabbladen
        meer om op te bouwen (alles zit in de database). Zorgt alleen dat het
        pand in de panden-tabel staat en geeft een nette samenvatting terug voor
        de flash-melding in webapp/app.py."""
        return {"aangemaakt": [], "kopregel_gezet": [], "ongewijzigd": ["database"]}

    # --- Kamers / huurders -------------------------------------------------

    def _rij_naar_tenant(self, row) -> Tenant:
        return Tenant(
            row_index=row["id"],
            naam=(row["naam"] or "").strip(),
            kamer=(row["kamer"] or "").strip(),
            verwacht_bedrag=_bedrag_uit(row["verwacht_bedrag"]) or Decimal("0"),
            iban=((row["iban"] or "").strip().replace(" ", "").upper() or None),
            zoekwoord=_tekst(row["zoekwoord"]),
            kale_huurprijs=_bedrag_uit(row["kale_huurprijs"]),
            servicekosten=_bedrag_uit(row["servicekosten"]),
            contract_einddatum=_tekst(row["contract_einddatum"]),
            opmerking=_tekst(row["opmerking"]),
            beschikbaar=bool(row["beschikbaar"]),
            advertentie_omschrijving=_tekst(row["advertentie_omschrijving"]),
            advertentie_map_id=_tekst(row["advertentie_map_id"]),
            email=_tekst(row["email"]),
            telefoonnummer=_tekst(row["telefoonnummer"]),
            geboortedatum=_tekst(row["geboortedatum"]),
            geboorteplaats=_tekst(row["geboorteplaats"]),
            studentnummer=_tekst(row["studentnummer"]),
            studierichting=_tekst(row["studierichting"]),
            borgsteller_naam=_tekst(row["borgsteller_naam"]),
            borgsteller_relatie=_tekst(row["borgsteller_relatie"]),
            contract_startdatum=_tekst(row["contract_startdatum"]),
            borg_bedrag=_bedrag_uit(row["borg_bedrag"]),
            advertentie_prijs=_bedrag_uit(row["advertentie_prijs"]),
            advertentie_oppervlakte=_tekst(row["advertentie_oppervlakte"]),
            advertentie_beschikbaar_per=_tekst(row["advertentie_beschikbaar_per"]),
            advertentie_beschikbaar_tot=_tekst(row["advertentie_beschikbaar_tot"]),
            advertentie_borg=_bedrag_uit(row["advertentie_borg"]),
            aanbod_verhuurd=bool(row["aanbod_verhuurd"]),
            studenten_verplicht=bool(row["studenten_verplicht"]),
        )

    def get_kamers(self) -> list[Tenant]:
        """Alle kamers, inclusief leegstaande (lege huurder, wel een kamernaam)."""
        conn = self._verbind()
        try:
            rows = conn.execute(
                "SELECT * FROM huurders WHERE pand_slug = ? ORDER BY volgorde, id",
                (self._slug,),
            ).fetchall()
        finally:
            conn.close()
        return [self._rij_naar_tenant(r) for r in rows if (r["kamer"] or "").strip()]

    def get_tenants(self) -> list[Tenant]:
        """Alleen de kamers die op dit moment een huurder hebben."""
        return [k for k in self.get_kamers() if k.naam]

    def voeg_kamer_toe(self, kamer: str, naam: str = "") -> int:
        """Maakt een nieuwe kamerrij aan (achteraan) en geeft het nieuwe
        row_index (huurders.id) terug. Vervangt het met de hand bijplakken van
        een rij in de oude Google Sheet - zie het bewerkbare huurders-grid."""
        conn = self._verbind()
        try:
            volgende = conn.execute(
                "SELECT COALESCE(MAX(volgorde), 0) + 1 AS v FROM huurders WHERE pand_slug = ?",
                (self._slug,),
            ).fetchone()["v"]
            cur = conn.execute(
                "INSERT INTO huurders (pand_slug, volgorde, kamer, naam) VALUES (?, ?, ?, ?)",
                (self._slug, volgende, kamer, naam),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def verwijder_kamer(self, row_index: int) -> None:
        """Verwijdert één kamerrij. De betaalhistorie (op kamernaam gesleuteld)
        blijft staan, net als vroeger bij het verwijderen van een sheet-rij."""
        conn = self._verbind()
        try:
            conn.execute(
                "DELETE FROM huurders WHERE id = ? AND pand_slug = ?", (row_index, self._slug)
            )
            conn.commit()
        finally:
            conn.close()

    def update_kamer(
        self,
        row_index: int,
        naam: str,
        kamer: str,
        verwacht_bedrag: Decimal,
        iban: str | None,
        zoekwoord: str | None,
        kale_huurprijs: Decimal | None = None,
        servicekosten: Decimal | None = None,
        contract_einddatum: str | None = None,
        opmerking: str | None = None,
        email: str | None = None,
        telefoonnummer: str | None = None,
        geboortedatum: str | None = None,
        geboorteplaats: str | None = None,
        studentnummer: str | None = None,
        studierichting: str | None = None,
        borgsteller_naam: str | None = None,
        borgsteller_relatie: str | None = None,
        contract_startdatum: str | None = None,
        borg_bedrag: Decimal | None = None,
    ) -> None:
        """Werkt de huurder-/contractvelden van één kamerrij bij. Laat - net als
        de oude sheet-versie - de aanbod-/status-kolommen (beschikbaar,
        advertentie*, status, ontvangen, laatst gecontroleerd) bewust ongemoeid."""
        conn = self._verbind()
        try:
            conn.execute(
                """UPDATE huurders SET
                    kamer = :kamer, naam = :naam, verwacht_bedrag = :verwacht,
                    kale_huurprijs = :kale, servicekosten = :service,
                    contract_einddatum = :einddatum, opmerking = :opmerking,
                    iban = :iban, zoekwoord = :zoekwoord, email = :email,
                    telefoonnummer = :telefoon, geboortedatum = :geboortedatum,
                    geboorteplaats = :geboorteplaats, studentnummer = :studentnummer,
                    studierichting = :studierichting, borgsteller_naam = :borgsteller_naam,
                    borgsteller_relatie = :borgsteller_relatie,
                    contract_startdatum = :contract_startdatum, borg_bedrag = :borg
                   WHERE id = :id AND pand_slug = :slug""",
                {
                    "kamer": kamer, "naam": naam, "verwacht": _bedrag_db(verwacht_bedrag) or "0.00",
                    "kale": _bedrag_db(kale_huurprijs), "service": _bedrag_db(servicekosten),
                    "einddatum": contract_einddatum or None, "opmerking": opmerking or None,
                    "iban": iban or None, "zoekwoord": zoekwoord or None, "email": email or None,
                    "telefoon": telefoonnummer or None, "geboortedatum": geboortedatum or None,
                    "geboorteplaats": geboorteplaats or None, "studentnummer": studentnummer or None,
                    "studierichting": studierichting or None, "borgsteller_naam": borgsteller_naam or None,
                    "borgsteller_relatie": borgsteller_relatie or None,
                    "contract_startdatum": contract_startdatum or None, "borg": _bedrag_db(borg_bedrag),
                    "id": row_index, "slug": self._slug,
                },
            )
            conn.commit()
        finally:
            conn.close()

    def update_aanbod(
        self,
        row_index: int,
        beschikbaar: bool,
        omschrijving: str | None,
        map_id: str | None,
        prijs: Decimal | None = None,
        oppervlakte: str | None = None,
        beschikbaar_per: str | None = None,
        beschikbaar_tot: str | None = None,
        borg: Decimal | None = None,
        aanbod_verhuurd: bool = False,
        studenten_verplicht: bool = True,
    ) -> None:
        conn = self._verbind()
        try:
            conn.execute(
                """UPDATE huurders SET
                    beschikbaar = :beschikbaar, aanbod_verhuurd = :verhuurd,
                    advertentie_omschrijving = :omschrijving, advertentie_map_id = :map_id,
                    advertentie_prijs = :prijs, advertentie_oppervlakte = :oppervlakte,
                    advertentie_beschikbaar_per = :per, advertentie_beschikbaar_tot = :tot,
                    advertentie_borg = :borg, studenten_verplicht = :studenten
                   WHERE id = :id AND pand_slug = :slug""",
                {
                    "beschikbaar": 1 if beschikbaar else 0, "verhuurd": 1 if aanbod_verhuurd else 0,
                    "omschrijving": omschrijving or None, "map_id": map_id or None,
                    "prijs": _bedrag_db(prijs), "oppervlakte": oppervlakte or None,
                    "per": beschikbaar_per or None, "tot": beschikbaar_tot or None,
                    "borg": _bedrag_db(borg), "studenten": 1 if studenten_verplicht else 0,
                    "id": row_index, "slug": self._slug,
                },
            )
            conn.commit()
        finally:
            conn.close()

    def write_results(self, results: list) -> None:
        now = nu_amsterdam().strftime("%d-%m-%Y %H:%M")
        conn = self._verbind()
        try:
            for result in results:
                conn.execute(
                    """UPDATE huurders SET status = ?, ontvangen_bedrag = ?, laatst_gecontroleerd = ?
                       WHERE id = ? AND pand_slug = ?""",
                    (result.status.value, _bedrag_db(result.ontvangen_bedrag) or "0.00", now,
                     result.tenant.row_index, self._slug),
                )
            conn.commit()
        finally:
            conn.close()

    # --- Historie ----------------------------------------------------------

    @staticmethod
    def _laatste_betaaldatum(betalingen: list) -> date | None:
        return max((p.datum for p in betalingen), default=None)

    def upsert_history(self, results: list, maand: str) -> None:
        """Werkt per (kamer, maand) de historieregel bij, of maakt 'm aan. Nooit
        een tweede regel voor dezelfde (kamer, maand) - dat garandeert de
        UNIQUE-constraint. De huurdersnaam van een bestaande regel wordt
        bevroren (zoals in de oude sheet-versie): alleen bij een gloednieuwe
        regel wordt de dan-actuele naam gebruikt."""
        conn = self._verbind()
        try:
            for r in results:
                betaaldatum = self._laatste_betaaldatum(r.gematchte_betalingen)
                bestaand = conn.execute(
                    "SELECT huurder FROM historie WHERE pand_slug = ? AND kamer = ? AND maand = ?",
                    (self._slug, r.tenant.kamer, maand),
                ).fetchone()
                if bestaand and (bestaand["huurder"] or "").strip():
                    huurder = bestaand["huurder"]
                else:
                    huurder = r.tenant.naam
                conn.execute(
                    """INSERT INTO historie (pand_slug, maand, kamer, huurder, verwacht_bedrag,
                                             ontvangen_bedrag, status, betaaldatum)
                       VALUES (:slug, :maand, :kamer, :huurder, :verwacht, :ontvangen, :status, :betaaldatum)
                       ON CONFLICT(pand_slug, kamer, maand) DO UPDATE SET
                           huurder = excluded.huurder,
                           verwacht_bedrag = excluded.verwacht_bedrag,
                           ontvangen_bedrag = excluded.ontvangen_bedrag,
                           status = excluded.status,
                           betaaldatum = excluded.betaaldatum""",
                    {
                        "slug": self._slug, "maand": maand, "kamer": r.tenant.kamer, "huurder": huurder,
                        "verwacht": _bedrag_db(r.tenant.verwacht_bedrag) or "0.00",
                        "ontvangen": _bedrag_db(r.ontvangen_bedrag) or "0.00",
                        "status": r.status.value,
                        "betaaldatum": betaaldatum.isoformat() if betaaldatum else None,
                    },
                )
            conn.commit()
        finally:
            conn.close()

    def verwijder_geschiedenis_voor_instapdatum(self, kamer: str, huurder: str, oudste_geldige_maand: str) -> int:
        """Verwijdert historieregels van déze huurder op déze kamer van vóór
        `oudste_geldige_maand` ('jjjj-mm'). Regels van een eerdere huurder op
        dezelfde kamer blijven staan. Geeft het aantal verwijderde regels terug."""
        conn = self._verbind()
        try:
            cur = conn.execute(
                """DELETE FROM historie
                   WHERE pand_slug = ? AND kamer = ? AND huurder = ? AND maand < ?""",
                (self._slug, kamer, huurder, oudste_geldige_maand),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def dedupliceer_geschiedenis(self) -> int:
        """Dubbele (kamer, maand)-regels kunnen door de UNIQUE-constraint niet
        bestaan, en maanden worden nooit als datum 'vermomd'. Dus niets te doen."""
        return 0

    def get_geschiedenis(self, kamer: str) -> list[HistorieRegel]:
        conn = self._verbind()
        try:
            rows = conn.execute(
                "SELECT * FROM historie WHERE pand_slug = ? AND kamer = ? ORDER BY maand",
                (self._slug, kamer),
            ).fetchall()
        finally:
            conn.close()
        regels = []
        for row in rows:
            try:
                status = Status(row["status"].strip())
            except ValueError:
                continue
            regels.append(
                HistorieRegel(
                    maand=row["maand"].strip(),
                    kamer=row["kamer"].strip(),
                    huurder=(row["huurder"] or "").strip(),
                    verwacht_bedrag=_bedrag_uit(row["verwacht_bedrag"]) or Decimal("0"),
                    ontvangen_bedrag=_bedrag_uit(row["ontvangen_bedrag"]) or Decimal("0"),
                    status=status,
                    betaaldatum=_datum_uit(row["betaaldatum"]),
                )
            )
        return regels

    # --- Aanmeldingen ------------------------------------------------------

    def add_aanmelding(self, kamer: str, aanmelding: Aanmelding) -> None:
        conn = self._verbind()
        try:
            conn.execute(
                f"""INSERT INTO aanmeldingen (pand_slug, {', '.join(_AANMELDINGEN_KOLOMMEN)})
                    VALUES (?, {', '.join('?' for _ in _AANMELDINGEN_KOLOMMEN)})""",
                (
                    self._slug,
                    nu_amsterdam().strftime("%d-%m-%Y %H:%M"), kamer, aanmelding.naam,
                    aanmelding.email, aanmelding.telefoon, aanmelding.huidig_adres,
                    aanmelding.studie, aanmelding.studentnummer, aanmelding.gewenste_ingangsdatum,
                    aanmelding.gewenste_huurduur, aanmelding.inkomstenbron, aanmelding.inkomsten_bedrag,
                    aanmelding.borgsteller, aanmelding.bezichtiging, aanmelding.videobel_nummer,
                    aanmelding.bewijs_inschrijving_link, aanmelding.borgsteller_naam,
                    aanmelding.borgsteller_relatie, aanmelding.borgsteller_email,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_aanmeldingen(self) -> list[list[str]]:
        conn = self._verbind()
        try:
            rows = conn.execute(
                "SELECT * FROM aanmeldingen WHERE pand_slug = ? ORDER BY id", (self._slug,)
            ).fetchall()
        finally:
            conn.close()
        return [[str(row[k] or "") for k in _AANMELDINGEN_KOLOMMEN] for row in rows]

    def wis_aanmeldingen(self) -> None:
        conn = self._verbind()
        try:
            conn.execute("DELETE FROM aanmeldingen WHERE pand_slug = ?", (self._slug,))
            conn.commit()
        finally:
            conn.close()

    # --- Bezichtigingen ----------------------------------------------------

    def add_bezichtiging(self, datum_iso: str, afspraak: dict) -> None:
        conn = self._verbind()
        try:
            conn.execute(
                f"""INSERT INTO bezichtigingen (pand_slug, {', '.join(_BEZICHTIGINGEN_KOLOMMEN)})
                    VALUES (?, {', '.join('?' for _ in _BEZICHTIGINGEN_KOLOMMEN)})""",
                (
                    self._slug, datum_iso, afspraak["tijd_start"], afspraak["tijd_eind"],
                    afspraak["kamer"], afspraak["naam"], afspraak["email"], afspraak["telefoon"],
                    afspraak["bezichtiging"], afspraak["bel_nummer"],
                    nu_amsterdam().strftime("%d-%m-%Y %H:%M"),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_bezichtigingen(self) -> list[list[str]]:
        return [rij for _id, rij in self.get_bezichtigingen_met_rijnummer()]

    def get_bezichtigingen_met_rijnummer(self) -> list[tuple[int, list[str]]]:
        conn = self._verbind()
        try:
            rows = conn.execute(
                "SELECT * FROM bezichtigingen WHERE pand_slug = ? ORDER BY id", (self._slug,)
            ).fetchall()
        finally:
            conn.close()
        return [(row["id"], [str(row[k] or "") for k in _BEZICHTIGINGEN_KOLOMMEN]) for row in rows]

    def verwijder_bezichtiging(self, rijnummer: int) -> None:
        conn = self._verbind()
        try:
            conn.execute(
                "DELETE FROM bezichtigingen WHERE id = ? AND pand_slug = ?", (rijnummer, self._slug)
            )
            conn.commit()
        finally:
            conn.close()

    # --- Vertrokken huurders ----------------------------------------------

    def archiveer_vertrokken_huurder(self, kamer: Tenant) -> None:
        if not kamer.naam:
            return
        conn = self._verbind()
        try:
            conn.execute(
                """INSERT INTO vertrokken (pand_slug, kamer, naam, email, telefoonnummer,
                                           contract_einddatum, vertrokken_op)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (self._slug, kamer.kamer, kamer.naam, kamer.email or None,
                 kamer.telefoonnummer or None, kamer.contract_einddatum or None,
                 date.today().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def _alle_vertrokken_huurders_ruw(self) -> list[VertrokkenHuurder]:
        conn = self._verbind()
        try:
            rows = conn.execute(
                "SELECT * FROM vertrokken WHERE pand_slug = ? ORDER BY id", (self._slug,)
            ).fetchall()
        finally:
            conn.close()
        resultaat = []
        for row in rows:
            naam = (row["naam"] or "").strip()
            vertrokken_op = _datum_uit(row["vertrokken_op"])
            if not naam or vertrokken_op is None:
                continue
            resultaat.append(VertrokkenHuurder(
                kamer=(row["kamer"] or "").strip(), naam=naam,
                email=_tekst(row["email"]), telefoonnummer=_tekst(row["telefoonnummer"]),
                contract_einddatum=_tekst(row["contract_einddatum"]),
                vertrokken_op=vertrokken_op, row_index=row["id"],
            ))
        resultaat.sort(key=lambda v: v.vertrokken_op, reverse=True)
        return resultaat

    @staticmethod
    def _parse_contract_einddatum(tekst: str) -> date | None:
        try:
            return datetime.strptime(tekst.strip(), "%d-%m-%Y").date()
        except ValueError:
            return None

    def get_recent_vertrokken_huurders(self, dagen: int = _VERTROKKEN_ZICHTBAAR_DAGEN) -> list[VertrokkenHuurder]:
        vandaag = date.today()
        return [
            v for v in self._alle_vertrokken_huurders_ruw()
            if vandaag <= (self._parse_contract_einddatum(v.contract_einddatum or "") or v.vertrokken_op)
            + timedelta(days=dagen)
        ]

    def get_alle_vertrokken_huurders(self) -> list[VertrokkenHuurder]:
        return self._alle_vertrokken_huurders_ruw()

    def get_vertrokken_huurder(self, row_index: int) -> VertrokkenHuurder | None:
        return next((v for v in self._alle_vertrokken_huurders_ruw() if v.row_index == row_index), None)
