"""EENMALIGE migratie: Google Sheets + properties.json -> de SQLite-hoofddatabase.

Draai dit één keer op de VPS nadat de nieuwe code is uitgerold. Het leest alle
panden uit properties.json en per pand de volledige sheet (kamers/huurders,
betaalhistorie, aanmeldingen, bezichtigingen, vertrokken huurders) en schrijft
alles naar steenhub.db in state_dir. De Google Sheets blijven onaangeroerd staan
als back-up - er wordt alleen gelezen.

Gebruik (in de app-container):

    docker compose exec app python3 -m scripts.migreer_naar_db          # migreren
    docker compose exec app python3 -m scripts.migreer_naar_db --droog   # alleen tonen, niets schrijven
    docker compose exec app python3 -m scripts.migreer_naar_db --opnieuw # eerst de DB leegmaken, dan migreren

Standaard weigert het script als er al panden in de database staan (voorkomt
dubbele data bij per ongeluk twee keer draaien). Gebruik --opnieuw om bewust
helemaal opnieuw te beginnen.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime

from dotenv import load_dotenv

from kamerverhuur_scanner import db
from kamerverhuur_scanner.config import Config, ConfigError
from kamerverhuur_scanner.db_client import DbClient
from kamerverhuur_scanner.models import Status
from kamerverhuur_scanner.properties import PropertiesError, load_properties
# De ECHTE sheet-lezer (gspread) - alleen hier nog nodig, voor de eenmalige
# overzet. De rest van de app gebruikt 'm niet meer.
from kamerverhuur_scanner.sheet_client import SheetClient as SheetReader
from kamerverhuur_scanner.sheet_client import _normaliseer_maand
from kamerverhuur_scanner.utils import parse_bedrag

# Korte pauze tussen panden: de Sheets-leeslimiet is ~60 reads/min per service-
# account, en de migratie leest per pand een handvol tabbladen. Even ademruimte
# zodat het rollende minuut-venster niet volloopt (alleen bij de echte overzet).
_PAUZE_TUSSEN_PANDEN_SEC = 8


def _migreer_pand(config: Config, pand, droog: bool) -> dict:
    """Leest één pand uit de sheet en schrijft 'm naar de database. Geeft een
    telling terug per soort."""
    reader = SheetReader(config, pand)
    telling = {"kamers": 0, "historie": 0, "aanmeldingen": 0, "bezichtigingen": 0, "vertrokken": 0}

    # 1. Kamers/huurders - via de DbClient (zelfde, geteste schrijfweg als de app).
    kamers = reader.get_kamers()
    client = DbClient(config, pand)
    for k in kamers:
        telling["kamers"] += 1
        if droog:
            continue
        rij = client.voeg_kamer_toe(k.kamer, k.naam)
        client.update_kamer(
            row_index=rij, naam=k.naam, kamer=k.kamer, verwacht_bedrag=k.verwacht_bedrag,
            iban=k.iban, zoekwoord=k.zoekwoord, kale_huurprijs=k.kale_huurprijs,
            servicekosten=k.servicekosten, contract_einddatum=k.contract_einddatum,
            opmerking=k.opmerking, email=k.email, telefoonnummer=k.telefoonnummer,
            geboortedatum=k.geboortedatum, geboorteplaats=k.geboorteplaats,
            studentnummer=k.studentnummer, studierichting=k.studierichting,
            borgsteller_naam=k.borgsteller_naam, borgsteller_relatie=k.borgsteller_relatie,
            contract_startdatum=k.contract_startdatum, borg_bedrag=k.borg_bedrag,
        )
        client.update_aanbod(
            row_index=rij, beschikbaar=k.beschikbaar, omschrijving=k.advertentie_omschrijving,
            map_id=k.advertentie_map_id, prijs=k.advertentie_prijs,
            oppervlakte=k.advertentie_oppervlakte, beschikbaar_per=k.advertentie_beschikbaar_per,
            beschikbaar_tot=k.advertentie_beschikbaar_tot, borg=k.advertentie_borg,
            aanbod_verhuurd=k.aanbod_verhuurd,
        )

    conn = db.verbind(config)
    try:
        # 2. Historie - het hele Historie-tabblad in EEN read uitlezen en in
        #    Python verwerken (niet per kamer apart; dat vrat de Sheets-leeslimiet
        #    op). Zelfde parsing/normalisatie als SheetClient.get_geschiedenis.
        #    Bij een dubbele (kamer, maand) wint de ONDERSTE rij (ON CONFLICT DO
        #    UPDATE), net als dedupliceer_geschiedenis.
        hist_rows = reader._history_worksheet().get_all_values()[1:]
        for row in hist_rows:
            row = row + [""] * (7 - len(row))
            maand = _normaliseer_maand(row[0])
            kamer = row[1].strip()
            if not maand or not kamer:
                continue
            try:
                status = Status(row[5].strip())
            except ValueError:
                continue
            betaaldatum = None
            if row[6].strip():
                try:
                    betaaldatum = datetime.strptime(row[6].strip(), "%d-%m-%Y").date().isoformat()
                except ValueError:
                    betaaldatum = None
            telling["historie"] += 1
            if droog:
                continue
            conn.execute(
                """INSERT INTO historie
                   (pand_slug, maand, kamer, huurder, verwacht_bedrag, ontvangen_bedrag, status, betaaldatum)
                   VALUES (:slug, :maand, :kamer, :huurder, :verwacht, :ontvangen, :status, :betaaldatum)
                   ON CONFLICT(pand_slug, kamer, maand) DO UPDATE SET
                       huurder = excluded.huurder, verwacht_bedrag = excluded.verwacht_bedrag,
                       ontvangen_bedrag = excluded.ontvangen_bedrag, status = excluded.status,
                       betaaldatum = excluded.betaaldatum""",
                {
                    "slug": pand.slug, "maand": maand, "kamer": kamer, "huurder": row[2].strip(),
                    "verwacht": f"{parse_bedrag(row[3]):.2f}", "ontvangen": f"{parse_bedrag(row[4]):.2f}",
                    "status": status.value, "betaaldatum": betaaldatum,
                },
            )

        # 3. Aanmeldingen (19 kolommen, zelfde volgorde als _AANMELDINGEN_HEADER).
        for rij in reader.get_aanmeldingen():
            telling["aanmeldingen"] += 1
            if droog:
                continue
            rij = (list(rij) + [""] * 19)[:19]
            conn.execute(
                """INSERT INTO aanmeldingen
                   (pand_slug, datum, kamer, naam, email, telefoon, huidig_adres, studie,
                    studentnummer, gewenste_ingangsdatum, gewenste_huurduur, inkomstenbron,
                    inkomsten_bedrag, borgsteller, bezichtiging, videobel_nummer,
                    bewijs_inschrijving, borgsteller_naam, borgsteller_relatie, borgsteller_email)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (pand.slug, *rij),
            )

        # 4. Bezichtigingen (10 kolommen).
        for rij in reader.get_bezichtigingen():
            telling["bezichtigingen"] += 1
            if droog:
                continue
            rij = (list(rij) + [""] * 10)[:10]
            conn.execute(
                """INSERT INTO bezichtigingen
                   (pand_slug, datum, tijd_start, tijd_eind, kamer, naam, email, telefoon,
                    manier, bel_nummer, bevestigd_op)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (pand.slug, *rij),
            )

        # 5. Vertrokken huurders - oudste eerst invoegen (zodat de id-volgorde in de
        #    DB de chronologie volgt, net als de sheet-rijvolgorde).
        vertrokken = sorted(reader.get_alle_vertrokken_huurders(), key=lambda v: v.vertrokken_op)
        for v in vertrokken:
            telling["vertrokken"] += 1
            if droog:
                continue
            conn.execute(
                """INSERT INTO vertrokken
                   (pand_slug, kamer, naam, email, telefoonnummer, contract_einddatum, vertrokken_op)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (pand.slug, v.kamer, v.naam, v.email, v.telefoonnummer,
                 v.contract_einddatum, v.vertrokken_op.isoformat()),
            )
        if not droog:
            conn.commit()
    finally:
        conn.close()
    return telling


def main(argv: list[str]) -> int:
    load_dotenv()
    droog = "--droog" in argv or "--dry-run" in argv
    opnieuw = "--opnieuw" in argv

    try:
        config = Config.load()
    except ConfigError as exc:
        print(f"Configuratiefout: {exc}", file=sys.stderr)
        return 1

    try:
        panden = load_properties(config.properties_file)
    except PropertiesError as exc:
        print(f"Pandenfout (properties.json): {exc}", file=sys.stderr)
        return 1

    # Veiligheidscheck: niet per ongeluk twee keer migreren.
    bestaande = db.laad_panden(config)
    if bestaande and not opnieuw and not droog:
        print(
            f"De database bevat al {len(bestaande)} pand(en). Migratie afgebroken om "
            "dubbele gegevens te voorkomen. Gebruik --opnieuw om de database eerst leeg "
            "te maken, of --droog om alleen te tonen wat er zou worden gemigreerd.",
            file=sys.stderr,
        )
        return 1

    if opnieuw and not droog:
        conn = db.verbind(config)
        try:
            for tabel in ("huurders", "historie", "aanmeldingen", "bezichtigingen", "vertrokken", "panden"):
                conn.execute(f"DELETE FROM {tabel}")
            conn.commit()
        finally:
            conn.close()
        print("Database leeggemaakt (--opnieuw).")

    print(f"{'DROOG - ' if droog else ''}Migreren van {len(panden)} pand(en) naar {db.db_pad(config)}\n")

    totaal = {"kamers": 0, "historie": 0, "aanmeldingen": 0, "bezichtigingen": 0, "vertrokken": 0}
    for i, pand in enumerate(panden):
        # Korte pauze tussen panden tegen de Sheets-leeslimiet (niet voor de 1e,
        # en niet bij een droge run waar niets weggeschreven wordt maar wél wordt
        # gelezen - dus ook dan even ademen).
        if i > 0:
            time.sleep(_PAUZE_TUSSEN_PANDEN_SEC)
        # Pand-metadata (incl. financiële velden) overzetten.
        if not droog:
            db.zet_pand(config, pand.slug, _pand_naar_gegevens(pand))
        try:
            telling = _migreer_pand(config, pand, droog)
        except Exception as exc:  # noqa: BLE001 - één pand mag de rest niet stoppen
            print(f"  [{pand.slug}] MISLUKT: {exc}", file=sys.stderr)
            continue
        for k, v in telling.items():
            totaal[k] += v
        print(f"  [{pand.slug}] {pand.naam}: " + ", ".join(f"{v} {k}" for k, v in telling.items()))

    print("\nTotaal: " + ", ".join(f"{v} {k}" for k, v in totaal.items()))
    if droog:
        print("\n(droog: er is niets weggeschreven)")
    else:
        print("\nKlaar. Controleer de app; de Google Sheets blijven als back-up staan.")
    return 0


def _pand_naar_gegevens(pand) -> dict:
    """Pand-dataclass -> de gegevens-dict zoals zet_pand die verwacht (dezelfde
    vorm als het pand-formulier). Bedragen/aantal als string of None."""
    def _b(d):
        return f"{d:.2f}" if d is not None else None
    return {
        "naam": pand.naam, "google_sheet_id": pand.google_sheet_id,
        "google_sheet_worksheet": pand.google_sheet_worksheet,
        "history_worksheet": pand.history_worksheet,
        "aanmeldingen_worksheet": pand.aanmeldingen_worksheet,
        "vertrokken_worksheet": pand.vertrokken_worksheet,
        "bunq_rekening_iban": pand.bunq_rekening_iban, "extra_bcc": list(pand.extra_bcc),
        "postcode": pand.postcode, "plaats": pand.plaats,
        "verhuurders": [{"naam": v.naam, "adres": v.adres} for v in pand.verhuurders],
        "rekeninghouder_naam": pand.rekeninghouder_naam, "gedeelde_ruimtes": pand.gedeelde_ruimtes,
        "bijzondere_bepalingen": pand.bijzondere_bepalingen, "gemeente_meldpunt": pand.gemeente_meldpunt,
        "heeft_bold_slot": pand.heeft_bold_slot,
        "onderhoud_reserve_per_maand": _b(pand.onderhoud_reserve_per_maand),
        "energiekosten_per_maand": _b(pand.energiekosten_per_maand),
        "belasting_per_maand": _b(pand.belasting_per_maand),
        "hypotheek_rente_per_maand": _b(pand.hypotheek_rente_per_maand),
        "hypotheek_last_per_maand": _b(pand.hypotheek_last_per_maand),
        "aantal_eigenaren": str(pand.aantal_eigenaren) if pand.aantal_eigenaren else None,
        "sleutels": list(pand.sleutels), "kleur": pand.kleur,
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
