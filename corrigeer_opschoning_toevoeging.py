"""Corrigeert een fout in opschonen_ontbrekende_toevoeging.py (zie de afvalreden
hieronder): dat script markeerde ELK adres zonder toevoeging op een huisnummer met
meerdere eenheden als "afgevallen", puur omdat er ergens op dat huisnummer meerdere
eenheden (A/B/C...) bestaan - ook als de destijds gevonden eenheid toevallig al gewoon
de juiste was. Dit script vergelijkt voor elk zo afgevallen record de eenheid die is
opgeslagen (item.huisnummer, bv. "35A") met de eenheid die de echte Funda-advertentie
zelf noemt (uit de URL-slug, bv. ".../voorhaven-35-a/...") - dat is onafhankelijke,
verifieerbare grond, geen giswerk:

  - komen ze overeen (of staat er geen toevoeging in de URL, dus ook geen toevoeging
    verwacht)              -> vals alarm, gewoon terugzetten op "actief".
  - komen ze niet overeen  -> was echt fout; de juiste eenheid (uit de URL) wordt
    automatisch opnieuw toegevoegd via dezelfde pipeline als "Toevoegen" (volledige
    checks: geocode, BAG, gis, opkoop, WOZ) - de foutieve blijft "afgevallen" staan.
  - geen toevoeging in de URL-slug te vinden -> niet automatisch te beoordelen, blijft
    ongemoeid (staat al "afgevallen"; desgewenst handmatig checken/opnieuw toevoegen).

Wijzigt state.json alleen met --uitvoeren; zonder die vlag is het een dry-run.

Gebruik:
  docker compose exec fundazoeker python3 corrigeer_opschoning_toevoeging.py             # dry-run
  docker compose exec fundazoeker python3 corrigeer_opschoning_toevoeging.py --uitvoeren  # daadwerkelijk corrigeren
"""
from __future__ import annotations

import argparse
import re

from rotterdam_scanner import pipeline
from rotterdam_scanner.config import load_config
from rotterdam_scanner.funda_mail import FundaListing
from rotterdam_scanner.state import StateStore

_AFVALREDEN_OPSCHONING = (
    "Automatisch opgeschoond: adres zonder toevoeging opgeslagen op een huisnummer met "
    "meerdere eenheden (bv. A/B/C) - mogelijk aan de verkeerde eenheid gekoppeld, met "
    "foutieve BAG/WOZ/investeringscijfers tot gevolg. Voeg desgewenst opnieuw toe via "
    "'Toevoegen' op de kaart-website, mét de juiste toevoeging."
)

_URL_TOEVOEGING_RE = re.compile(r"-(?P<huisnummer>\d+)(?:-(?P<toevoeging>[a-zA-Z0-9]+))?/\d+/?$")
_HUISNUMMER_SPLITS_RE = re.compile(r"^(?P<nummer>\d+)(?P<toevoeging>.*)$")


def _normaliseer(toevoeging: str) -> str:
    return toevoeging.replace("-", "").upper()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--uitvoeren", action="store_true", help="daadwerkelijk wijzigen (standaard: alleen dry-run tonen)"
    )
    args = parser.parse_args()

    config = load_config()
    state = StateStore(config.state_path)

    herstellen: list = []
    corrigeren: list = []
    onbeoordeeld: list = []

    for item in state.all():
        if item.status != "afgevallen" or item.afvalreden != _AFVALREDEN_OPSCHONING:
            continue

        url_match = _URL_TOEVOEGING_RE.search(item.url)
        url_toevoeging = _normaliseer(url_match.group("toevoeging") or "") if url_match else None

        huisnummer_match = _HUISNUMMER_SPLITS_RE.match(item.huisnummer or "")
        opgeslagen_toevoeging = _normaliseer(huisnummer_match.group("toevoeging")) if huisnummer_match else ""

        if url_match is None:
            onbeoordeeld.append(item)
        elif opgeslagen_toevoeging == url_toevoeging:
            herstellen.append(item)
        else:
            corrigeren.append((item, url_match))

    print(f"{len(herstellen)} woning(en) blijken vals-positief (al correct) -> terug naar 'actief':")
    for item in herstellen:
        print(f"  - {item.object_id} | {item.weergavenaam}")

    print(f"\n{len(corrigeren)} woning(en) echt fout -> juiste eenheid wordt opnieuw toegevoegd:")
    for item, url_match in corrigeren:
        toevoeging = (url_match.group("toevoeging") or "").upper()
        print(f"  - {item.object_id} | {item.weergavenaam} -> {url_match.group('huisnummer')}{toevoeging} | {item.url}")

    if onbeoordeeld:
        print(f"\n{len(onbeoordeeld)} woning(en) konden niet automatisch beoordeeld worden (geen toevoeging in URL-slug), blijven 'afgevallen':")
        for item in onbeoordeeld:
            print(f"  - {item.object_id} | {item.weergavenaam} | {item.url}")

    if not args.uitvoeren:
        print("\nDry-run: er is niets gewijzigd. Draai met --uitvoeren om dit daadwerkelijk te verwerken.")
        return

    for item in herstellen:
        item.status = "actief"
        item.handmatig_verwijderd = False
        item.afvalreden = None
        state.upsert(item)
    state.save()

    nieuwe_listings = []
    for item, url_match in corrigeren:
        huisnummer = url_match.group("huisnummer")
        toevoeging = (url_match.group("toevoeging") or "").upper()
        postcode = item.object_id.split("-", 1)[0]
        nieuwe_listings.append(
            FundaListing(
                object_id=f"{postcode}-{huisnummer}{toevoeging}",
                url=item.url,
                straatnaam=item.straatnaam,
                huisnummer=huisnummer,
                toevoeging=toevoeging,
                postcode=postcode,
                woonplaats="Rotterdam",
            )
        )

    print(f"\n{len(herstellen)} woning(en) hersteld naar 'actief'.")

    if nieuwe_listings:
        resultaat = pipeline.run_handmatig(config, nieuwe_listings)
        print(
            f"{len(resultaat.nieuw_actief)} woning(en) opnieuw toegevoegd met de juiste eenheid "
            f"({len(resultaat.nieuw_afgevallen)} daarvan meteen weer afgevallen op de geo-checks, "
            f"{len(resultaat.nieuw_onbekend_adres)} met onbekend adres)."
        )
        if resultaat.fouten:
            print("Fouten tijdens het opnieuw toevoegen:")
            for fout in resultaat.fouten:
                print(f"  - {fout}")


if __name__ == "__main__":
    main()
