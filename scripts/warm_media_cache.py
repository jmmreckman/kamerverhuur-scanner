"""EENMALIG (of af en toe): warm de WebP-variantcache van de aanbod-foto's op.

De publieke aanbodpagina serveert verkleinde WebP-varianten (thumb=500px voor de
grids, web=1600px voor de detail-/lightboxweergave). Die worden normaal LUI
aangemaakt: de eerste bezoeker die een foto op een bepaald formaat opvraagt,
wacht eenmalig op de conversie; daarna komt 'ie uit de schijfcache. Bestaande
foto's zijn dus nog niet vooraf verkleind.

Dit script loopt alle aanbod-foto's van alle panden langs en genereert beide
varianten alvast, zodat ook de eerste bezoeker meteen de snelle versie krijgt.
Het is veilig en herhaalbaar: het schrijft enkel naar de verborgen .cache-mappen
(precies wat de app zelf ook doet), raakt de originelen niet aan, en slaat een
al-actuele variant over.

Draaien op de VPS (in de app-container, die Pillow + de media heeft):

    docker exec deploy-app-1 python3 -m scripts.warm_media_cache
"""
from __future__ import annotations

import sys

from dotenv import load_dotenv

from kamerverhuur_scanner import db
from kamerverhuur_scanner.config import Config, ConfigError
from kamerverhuur_scanner.db_client import DbClient
from kamerverhuur_scanner.lokale_media import STANDAARD_VARIANT_BREEDTES, LokaleMediaClient

# Dezelfde breedtes die de app serveert én bij upload aanmaakt (één bron van
# waarheid in lokale_media) - anders warm je varianten op die de route nooit
# opvraagt (cache-miss).
_BREEDTES = STANDAARD_VARIANT_BREEDTES


def main() -> int:
    load_dotenv()
    try:
        config = Config.load()
    except ConfigError as exc:
        print(f"Configuratiefout: {exc}", file=sys.stderr)
        return 1

    try:
        panden = db.laad_panden(config)
    except Exception as exc:  # noqa: BLE001
        print(f"Kon panden niet laden: {exc}", file=sys.stderr)
        return 1

    totaal_fotos = totaal_varianten = overgeslagen = fouten = 0
    for pand in panden:
        media = LokaleMediaClient(config, pand, "aanbod")
        try:
            kamers = DbClient(config, pand).get_kamers()
        except Exception as exc:  # noqa: BLE001
            print(f"  [{pand.slug}] kamers laden mislukt: {exc}", file=sys.stderr)
            continue

        pand_fotos = pand_varianten = 0
        for kamer in kamers:
            for bestand in media.list_bestanden(kamer.kamer):
                if not bestand.mimetype.startswith("image/"):
                    overgeslagen += 1
                    continue
                pand_fotos += 1
                for breedte in _BREEDTES:
                    try:
                        resultaat = media.lees_variant(kamer.kamer, bestand.id, breedte)
                    except Exception as exc:  # noqa: BLE001 - één foto mag de rest niet stoppen
                        fouten += 1
                        print(f"    [{pand.slug}/{kamer.kamer}] {bestand.naam} @ {breedte}px: {exc}",
                              file=sys.stderr)
                        continue
                    if resultaat is not None:
                        pand_varianten += 1

        totaal_fotos += pand_fotos
        totaal_varianten += pand_varianten
        if pand_fotos:
            print(f"  [{pand.slug}] {pand.naam}: {pand_fotos} foto's, {pand_varianten} varianten opgewarmd")
        else:
            print(f"  [{pand.slug}] {pand.naam}: geen aanbod-foto's")

    print(f"\nKlaar: {totaal_fotos} foto's, {totaal_varianten} varianten opgewarmd, "
          f"{overgeslagen} niet-afbeeldingen overgeslagen, {fouten} fout(en).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
