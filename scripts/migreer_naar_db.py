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

from dotenv import load_dotenv

from kamerverhuur_scanner import db
from kamerverhuur_scanner.config import Config, ConfigError
from kamerverhuur_scanner.db_client import DbClient
from kamerverhuur_scanner.properties import PropertiesError, load_properties
# De ECHTE sheet-lezer (gspread) - alleen hier nog nodig, voor de eenmalige
# overzet. De rest van de app gebruikt 'm niet meer.
from kamerverhuur_scanner.sheet_client import SheetClient as SheetReader
from kamerverhuur_scanner.sheet_client import _normaliseer_maand


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
        # 2. Historie - alle kamernamen die in het Historie-tabblad voorkomen (ook
        #    kamers die niet meer in de Huurders-sheet staan), via de geteste
        #    get_geschiedenis()-parser.
        hist_ws = reader._history_worksheet()
        hist_rows = hist_ws.get_all_values()[1:]
        kamer_namen = {
            row[1].strip() for row in hist_rows
            if len(row) > 1 and row[1].strip() and _normaliseer_maand(row[0] if row else "")
        }
        for kamer in sorted(kamer_namen):
            for r in reader.get_geschiedenis(kamer):
                telling["historie"] += 1
                if droog:
                    continue
                conn.execute(
                    """INSERT OR IGNORE INTO historie
                       (pand_slug, maand, kamer, huurder, verwacht_bedrag, ontvangen_bedrag, status, betaaldatum)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (pand.slug, r.maand, r.kamer, r.huurder, f"{r.verwacht_bedrag:.2f}",
                     f"{r.ontvangen_bedrag:.2f}", r.status.value,
                     r.betaaldatum.isoformat() if r.betaaldatum else None),
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
    for pand in panden:
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
